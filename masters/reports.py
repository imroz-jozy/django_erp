from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Prefetch, Sum

from .models import (
    Account,
    AccountGroup,
    CreditNote,
    CreditNoteLine,
    DebitNote,
    DebitNoteLine,
    Item,
    Journal,
    JournalLine,
    Payment,
    Purchase,
    PurchaseBillSundry,
    PurchaseItem,
    PurchaseReturn,
    PurchaseReturnBillSundry,
    PurchaseReturnItem,
    Receipt,
    Sale,
    SaleBillSundry,
    SaleItem,
    SaleReturn,
    SaleReturnBillSundry,
    SaleReturnItem,
)
from .money import ZERO, money


def indian_fy(today=None):
    today = today or date.today()
    if today.month >= 4:
        start = date(today.year, 4, 1)
        end = date(today.year + 1, 3, 31)
    else:
        start = date(today.year - 1, 4, 1)
        end = date(today.year, 3, 31)
    return start, end


def parse_date(value, fallback):
    if not value:
        return fallback
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def period_from_request(request):
    start, end = indian_fy()
    start = parse_date(request.GET.get("from"), start)
    end = parse_date(request.GET.get("to"), end)
    return start, end


def _post(ledgers, account, debit=ZERO, credit=ZERO):
    if account is None:
        return
    ledgers[account.id]["account"] = account
    ledgers[account.id]["debit"] += money(debit)
    ledgers[account.id]["credit"] += money(credit)


def build_ledgers(date_from, date_to):
    ledgers = defaultdict(lambda: {"account": None, "debit": ZERO, "credit": ZERO})

    for account in Account.objects.select_related(
        "account_group",
        "account_group__under_group",
        "account_group__under_group__under_group",
    ):
        opening = money(account.opening)
        if account.opening_type == Account.OpeningType.DR:
            _post(ledgers, account, debit=opening)
        else:
            _post(ledgers, account, credit=opening)

    sales = (
        Sale.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related(
            "account",
            "sale_type",
            "sale_type__sales_account",
            "sale_type__tax_account",
            "sale_type__tax_account_2",
        )
        .prefetch_related(
            Prefetch("items", queryset=SaleItem.objects.select_related("item", "item__sale_account")),
            Prefetch(
                "bill_sundries",
                queryset=SaleBillSundry.objects.select_related("bill_sundry", "bill_sundry__posting_account_sale"),
            ),
        )
    )
    for sale in sales:
        totals = sale.totals()
        _post(ledgers, sale.account, debit=totals["net_amount"])
        sales_acc = sale.sale_type.sales_account if sale.sale_type_id else None
        for line in sale.items.all():
            line_acc = line.item.sale_account if (line.item_id and line.item.sale_account_id) else sales_acc
            _post(ledgers, line_acc, credit=line.amount_after_discount)
        if sale.sale_type_id and totals["tax_amount"]:
            for tax_acc, tax_amt in sale.sale_type.tax_postings(totals["tax_amount"]):
                _post(ledgers, tax_acc, credit=tax_amt)
        for line, signed in zip(sale.bill_sundries.all(), totals["sundry_signed_amounts"]):
            acc = line.bill_sundry.posting_account_sale or sales_acc
            if signed >= 0:
                _post(ledgers, acc, credit=signed)
            else:
                _post(ledgers, acc, debit=-signed)

    purchases = (
        Purchase.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related(
            "account",
            "purchase_type",
            "purchase_type__purchase_account",
            "purchase_type__tax_account",
            "purchase_type__tax_account_2",
            "purchase_type__rcm_payable_account",
        )
        .prefetch_related(
            Prefetch("items", queryset=PurchaseItem.objects.select_related("item", "item__purchase_account")),
            Prefetch(
                "bill_sundries",
                queryset=PurchaseBillSundry.objects.select_related(
                    "bill_sundry", "bill_sundry__posting_account_purchase"
                ),
            ),
        )
    )
    for purchase in purchases:
        totals = purchase.totals()
        purchase_acc = (
            purchase.purchase_type.purchase_account if purchase.purchase_type_id else None
        )
        rcm_acc = (
            purchase.purchase_type.rcm_payable_account
            if purchase.purchase_type_id and purchase.is_reverse_charge
            else None
        )
        if rcm_acc and totals["tax_amount"]:
            # Reverse Charge: the supplier didn't collect GST, so they're
            # credited only the taxable value. GST is self-assessed here as
            # a payable liability (this line) in addition to the normal
            # input-credit debit to the tax account(s) below — net cash
            # effect is neutral, but both sides are recorded per GST rules.
            _post(ledgers, purchase.account, credit=money(totals["net_amount"] - totals["tax_amount"]))
            _post(ledgers, rcm_acc, credit=totals["tax_amount"])
        else:
            _post(ledgers, purchase.account, credit=totals["net_amount"])
        for line in purchase.items.all():
            line_acc = (
                line.item.purchase_account if (line.item_id and line.item.purchase_account_id) else purchase_acc
            )
            _post(ledgers, line_acc, debit=line.amount_after_discount)
        if purchase.purchase_type_id and totals["tax_amount"]:
            for tax_acc, tax_amt in purchase.purchase_type.tax_postings(totals["tax_amount"]):
                _post(ledgers, tax_acc, debit=tax_amt)
        for line, signed in zip(purchase.bill_sundries.all(), totals["sundry_signed_amounts"]):
            acc = line.bill_sundry.posting_account_purchase or purchase_acc
            if signed >= 0:
                _post(ledgers, acc, debit=signed)
            else:
                _post(ledgers, acc, credit=-signed)

    sale_returns = (
        SaleReturn.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related(
            "account",
            "sale_type",
            "sale_type__sales_account",
            "sale_type__sales_return_account",
            "sale_type__tax_account",
            "sale_type__tax_account_2",
        )
        .prefetch_related(
            Prefetch("items", queryset=SaleReturnItem.objects.select_related("item", "item__sale_account")),
            Prefetch(
                "bill_sundries",
                queryset=SaleReturnBillSundry.objects.select_related(
                    "bill_sundry", "bill_sundry__posting_account_sale"
                ),
            ),
        )
    )
    for sr in sale_returns:
        totals = sr.totals()
        _post(ledgers, sr.account, credit=totals["net_amount"])
        return_acc = sr.sale_type.effective_sales_return_account if sr.sale_type_id else None
        for line in sr.items.all():
            line_acc = line.item.sale_account if (line.item_id and line.item.sale_account_id) else return_acc
            _post(ledgers, line_acc, debit=line.amount_after_discount)
        if sr.sale_type_id and totals["tax_amount"]:
            for tax_acc, tax_amt in sr.sale_type.tax_postings(totals["tax_amount"]):
                _post(ledgers, tax_acc, debit=tax_amt)
        for line, signed in zip(sr.bill_sundries.all(), totals["sundry_signed_amounts"]):
            acc = line.bill_sundry.posting_account_sale or return_acc
            if signed >= 0:
                _post(ledgers, acc, debit=signed)
            else:
                _post(ledgers, acc, credit=-signed)

    purchase_returns = (
        PurchaseReturn.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related(
            "account",
            "purchase_type",
            "purchase_type__purchase_account",
            "purchase_type__purchase_return_account",
            "purchase_type__tax_account",
            "purchase_type__tax_account_2",
        )
        .prefetch_related(
            Prefetch(
                "items", queryset=PurchaseReturnItem.objects.select_related("item", "item__purchase_account")
            ),
            Prefetch(
                "bill_sundries",
                queryset=PurchaseReturnBillSundry.objects.select_related(
                    "bill_sundry", "bill_sundry__posting_account_purchase"
                ),
            ),
        )
    )
    for pr in purchase_returns:
        totals = pr.totals()
        _post(ledgers, pr.account, debit=totals["net_amount"])
        return_acc = pr.purchase_type.effective_purchase_return_account if pr.purchase_type_id else None
        for line in pr.items.all():
            line_acc = (
                line.item.purchase_account if (line.item_id and line.item.purchase_account_id) else return_acc
            )
            _post(ledgers, line_acc, credit=line.amount_after_discount)
        if pr.purchase_type_id and totals["tax_amount"]:
            for tax_acc, tax_amt in pr.purchase_type.tax_postings(totals["tax_amount"]):
                _post(ledgers, tax_acc, credit=tax_amt)
        for line, signed in zip(pr.bill_sundries.all(), totals["sundry_signed_amounts"]):
            acc = line.bill_sundry.posting_account_purchase or return_acc
            if signed >= 0:
                _post(ledgers, acc, credit=signed)
            else:
                _post(ledgers, acc, debit=-signed)

    credit_notes = (
        CreditNote.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("account")
        .prefetch_related("lines__account")
    )
    for cn in credit_notes:
        total = ZERO
        for line in cn.lines.all():
            _post(ledgers, line.account, debit=line.amount)
            total += money(line.amount)
        _post(ledgers, cn.account, credit=total)

    debit_notes = (
        DebitNote.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("account")
        .prefetch_related("lines__account")
    )
    for dn in debit_notes:
        total = ZERO
        for line in dn.lines.all():
            _post(ledgers, line.account, credit=line.amount)
            total += money(line.amount)
        _post(ledgers, dn.account, debit=total)

    payments = (
        Payment.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("through")
        .prefetch_related("lines__account")
    )
    for pmt in payments:
        total = ZERO
        for line in pmt.lines.all():
            _post(ledgers, line.account, debit=line.amount)
            total += money(line.amount)
        _post(ledgers, pmt.through, credit=total)

    receipts = (
        Receipt.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("through")
        .prefetch_related("lines__account")
    )
    for rec in receipts:
        total = ZERO
        for line in rec.lines.all():
            _post(ledgers, line.account, credit=line.amount)
            total += money(line.amount)
        _post(ledgers, rec.through, debit=total)

    journals = (
        Journal.objects.filter(date__gte=date_from, date__lte=date_to)
        .prefetch_related("lines__account")
    )
    for jv in journals:
        for line in jv.lines.all():
            _post(ledgers, line.account, debit=line.debit, credit=line.credit)

    rows = []
    for data in ledgers.values():
        account = data["account"]
        if account is None:
            continue
        debit = money(data["debit"])
        credit = money(data["credit"])
        balance = money(debit - credit)
        rows.append(
            {
                "account": account,
                "group": account.account_group,
                "nature": account.account_group.nature,
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "dr_cr": "Dr" if balance >= 0 else "Cr",
                "display": abs(balance),
            }
        )
    rows.sort(key=lambda r: (r["group"].name, r["account"].account_name))
    return rows


def group_tree_balances(rows):
    by_group = defaultdict(lambda: {"debit": ZERO, "credit": ZERO, "balance": ZERO, "accounts": []})
    for row in rows:
        g = row["group"]
        by_group[g.id]["group"] = g
        by_group[g.id]["debit"] += row["debit"]
        by_group[g.id]["credit"] += row["credit"]
        by_group[g.id]["balance"] += row["balance"]
        by_group[g.id]["accounts"].append(row)

    groups = {g.id: g for g in AccountGroup.objects.select_related("under_group")}
    totals = {gid: dict(data) for gid, data in by_group.items()}

    def rollup(group):
        key = group.id
        if key not in totals:
            totals[key] = {
                "group": group,
                "debit": ZERO,
                "credit": ZERO,
                "balance": ZERO,
                "accounts": [],
            }
        for child in group.sub_groups.all():
            child_data = rollup(child)
            totals[key]["debit"] += child_data["debit"]
            totals[key]["credit"] += child_data["credit"]
            totals[key]["balance"] += child_data["balance"]
        totals[key]["debit"] = money(totals[key]["debit"])
        totals[key]["credit"] = money(totals[key]["credit"])
        totals[key]["balance"] = money(totals[key]["balance"])
        return totals[key]

    primaries = [g for g in groups.values() if g.primary_group]
    for group in primaries:
        rollup(group)
    return totals


def stock_figures(date_from, date_to):
    """
    Weighted Average Rate (WAR) stock valuation.

    WAR per item = (opening_value + period_purchase_value)
                  / (opening_qty   + period_purchase_qty)

    Closing value  = closing_qty × WAR
    COGS (sale)    = sale_qty    × WAR

    Service items, and any item whose Main Unit is marked 'N/A' (no_quantity),
    carry no quantity and never hold stock, so they are excluded here entirely.
    """
    stock_items = Item.objects.filter(
        item_type=Item.ItemType.GOODS, main_unit__isnull=False, main_unit__no_quantity=False
    )
    stock_item_ids = set(stock_items.values_list("id", flat=True))

    opening_total = money(
        stock_items.aggregate(total=Sum("opening_value"))["total"] or 0
    )

    # Accumulate period purchases per item
    purchase_qty = defaultdict(lambda: ZERO)
    purchase_amt = defaultdict(lambda: ZERO)
    purchase_value_total = ZERO

    # Stock QUANTITY moves by billed + free quantity together (a "10+2"
    # scheme still puts 12 units in the godown); stock VALUE only ever
    # reflects the billed amount, so amount_after_discount is untouched.
    for line in PurchaseItem.objects.filter(
        purchase__date__gte=date_from, purchase__date__lte=date_to, item_id__in=stock_item_ids
    ).select_related("item"):
        purchase_qty[line.item_id] += line.total_quantity
        purchase_amt[line.item_id] += line.amount_after_discount
        purchase_value_total += line.amount_after_discount

    # Accumulate period sales per item
    sale_qty = defaultdict(lambda: ZERO)
    for line in SaleItem.objects.filter(
        sale__date__gte=date_from, sale__date__lte=date_to, item_id__in=stock_item_ids
    ).select_related("item"):
        sale_qty[line.item_id] += line.total_quantity

    # Goods that came back from customers (add back to stock) and goods we
    # sent back to suppliers (remove from stock). Valued at the same WAR as
    # normal opening+purchase stock so the rate itself stays stable.
    sale_return_qty = defaultdict(lambda: ZERO)
    for line in SaleReturnItem.objects.filter(
        sale_return__date__gte=date_from, sale_return__date__lte=date_to, item_id__in=stock_item_ids
    ).select_related("item"):
        sale_return_qty[line.item_id] += line.total_quantity

    purchase_return_qty = defaultdict(lambda: ZERO)
    for line in PurchaseReturnItem.objects.filter(
        purchase_return__date__gte=date_from, purchase_return__date__lte=date_to, item_id__in=stock_item_ids
    ).select_related("item"):
        purchase_return_qty[line.item_id] += line.total_quantity

    stock_rows = []
    closing_qty_value = ZERO
    sale_cogs = ZERO

    for item in stock_items:
        op_qty = money(item.opening_main)
        op_val = money(item.opening_value)
        pur_qty = purchase_qty[item.id]
        pur_val = purchase_amt[item.id]
        sol_qty = sale_qty[item.id]
        sret_qty = sale_return_qty[item.id]
        pret_qty = purchase_return_qty[item.id]

        total_qty_in = op_qty + pur_qty          # total stock received (excl. returns)
        total_val_in = op_val + pur_val          # total value received (excl. returns)

        # Weighted Average Rate
        if total_qty_in > 0:
            war = money(total_val_in / total_qty_in)
        elif item.purchase_price:
            war = money(item.purchase_price)      # fallback to master rate
        else:
            war = ZERO

        closing_qty = (total_qty_in + sret_qty) - (sol_qty + pret_qty)
        closing_val = money(closing_qty * war)
        cogs = money(sol_qty * war)

        closing_qty_value += closing_val
        sale_cogs += cogs

        stock_rows.append(
            {
                "item": item,
                "opening_qty": op_qty,
                "opening_value": op_val,
                "purchase_qty": pur_qty,
                "sale_qty": sol_qty,
                "sale_return_qty": sret_qty,
                "purchase_return_qty": pret_qty,
                "closing_qty": closing_qty,
                "closing_value": closing_val,
                "war": war,                       # weighted average rate
            }
        )

    return {
        "opening_stock": opening_total,
        "purchase_value": money(purchase_value_total),
        "closing_stock": money(closing_qty_value),
        "cogs": money(sale_cogs),
        "rows": stock_rows,
    }


# =========================================================
# GST REPORTS
# =========================================================
# Read-only aggregations for return filing. These do NOT change how tax
# is calculated or posted anywhere else — they only re-read the same
# amounts already computed by ItemLineMixin/voucher_totals and group them
# the way GSTR-1 expects (by HSN+rate, and by B2B/B2C).

def _line_tax_split(sale_type, tax_amount):
    """CGST/SGST vs IGST split for a tax amount, using the same
    tax_split_percent already used for real ledger posting."""
    if tax_amount == 0:
        return ZERO, ZERO, ZERO
    if sale_type and sale_type.is_interstate:
        return ZERO, ZERO, money(tax_amount)
    pct = sale_type.tax_split_percent if sale_type else Decimal("50")
    cgst = money(tax_amount * pct / Decimal("100"))
    sgst = money(tax_amount - cgst)
    return cgst, sgst, ZERO


def _sale_line_facts(sale_qs):
    """Yield one fact dict per Sale item line: voucher info + HSN/rate +
    taxable value + CGST/SGST/IGST/Cess for that line alone."""
    for sale in sale_qs:
        is_b2b = bool(sale.account.gst)
        for line in sale.items.all():
            taxable = line.amount_after_discount
            cgst, sgst, igst = _line_tax_split(sale.sale_type, line.tax_amount)
            cess = money(taxable * money(line.item.cess_rate or 0) / Decimal("100"))
            yield {
                "date": sale.date,
                "voucher_no": sale.invoice_no,
                "account": sale.account,
                "is_b2b": is_b2b,
                "gstin": sale.account.gst,
                "place_of_supply": sale.account.state,
                "hsn": line.item.hsn,
                "rate": money(line.tax),
                "quantity": money(line.quantity),
                "taxable": taxable,
                "cgst": cgst,
                "sgst": sgst,
                "igst": igst,
                "cess": cess,
                "total": money(taxable + cgst + sgst + igst + cess),
            }


def _sale_return_line_facts(sr_qs):
    """Same shape as _sale_line_facts, for Sale Return lines (used to net
    HSN summary and to build the Credit/Debit Notes section)."""
    for sr in sr_qs:
        is_b2b = bool(sr.account.gst)
        for line in sr.items.all():
            taxable = line.amount_after_discount
            cgst, sgst, igst = _line_tax_split(sr.sale_type, line.tax_amount)
            cess = money(taxable * money(line.item.cess_rate or 0) / Decimal("100"))
            yield {
                "date": sr.date,
                "voucher_no": sr.voucher_no,
                "account": sr.account,
                "is_b2b": is_b2b,
                "gstin": sr.account.gst,
                "place_of_supply": sr.account.state,
                "hsn": line.item.hsn,
                "rate": money(line.tax),
                "quantity": money(line.quantity),
                "taxable": taxable,
                "cgst": cgst,
                "sgst": sgst,
                "igst": igst,
                "cess": cess,
                "total": money(taxable + cgst + sgst + igst + cess),
            }


def hsn_summary(date_from, date_to):
    """GSTR-1 Table 12 style: outward supplies grouped by HSN/SAC + rate,
    net of Sale Returns in the same period."""
    sales = (
        Sale.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("account", "sale_type")
        .prefetch_related("items__item")
    )
    sale_returns = (
        SaleReturn.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("account", "sale_type")
        .prefetch_related("items__item")
    )

    groups = {}

    def _add(fact, sign):
        key = (fact["hsn"] or "(no HSN)", fact["rate"])
        row = groups.setdefault(
            key,
            {
                "hsn": key[0],
                "rate": key[1],
                "quantity": ZERO,
                "taxable": ZERO,
                "cgst": ZERO,
                "sgst": ZERO,
                "igst": ZERO,
                "cess": ZERO,
                "total": ZERO,
            },
        )
        row["quantity"] = money(row["quantity"] + sign * fact["quantity"])
        row["taxable"] = money(row["taxable"] + sign * fact["taxable"])
        row["cgst"] = money(row["cgst"] + sign * fact["cgst"])
        row["sgst"] = money(row["sgst"] + sign * fact["sgst"])
        row["igst"] = money(row["igst"] + sign * fact["igst"])
        row["cess"] = money(row["cess"] + sign * fact["cess"])
        row["total"] = money(row["total"] + sign * fact["total"])

    for fact in _sale_line_facts(sales):
        _add(fact, 1)
    for fact in _sale_return_line_facts(sale_returns):
        _add(fact, -1)

    rows = sorted(groups.values(), key=lambda r: (r["hsn"], r["rate"]))
    grand_total = money(sum((r["total"] for r in rows), ZERO))
    return {"rows": rows, "grand_total": grand_total}


def gst_outward_summary(date_from, date_to):
    """GSTR-1 style outward supply summary: B2B invoices (party has a
    GSTIN) listed individually, B2C aggregated by rate, plus a Credit/Debit
    Notes section from Sale Returns and Credit Notes in the period."""
    sales = (
        Sale.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("account", "sale_type")
        .prefetch_related("items__item")
        .order_by("date", "invoice_no")
    )

    b2b_by_invoice = {}
    b2c_by_rate = defaultdict(
        lambda: {"rate": None, "taxable": ZERO, "cgst": ZERO, "sgst": ZERO, "igst": ZERO, "cess": ZERO, "total": ZERO}
    )

    for fact in _sale_line_facts(sales):
        if fact["is_b2b"]:
            key = fact["voucher_no"]
            row = b2b_by_invoice.setdefault(
                key,
                {
                    "date": fact["date"],
                    "voucher_no": fact["voucher_no"],
                    "account": fact["account"],
                    "gstin": fact["gstin"],
                    "place_of_supply": fact["place_of_supply"],
                    "taxable": ZERO,
                    "cgst": ZERO,
                    "sgst": ZERO,
                    "igst": ZERO,
                    "cess": ZERO,
                    "total": ZERO,
                },
            )
            row["taxable"] = money(row["taxable"] + fact["taxable"])
            row["cgst"] = money(row["cgst"] + fact["cgst"])
            row["sgst"] = money(row["sgst"] + fact["sgst"])
            row["igst"] = money(row["igst"] + fact["igst"])
            row["cess"] = money(row["cess"] + fact["cess"])
            row["total"] = money(row["total"] + fact["total"])
        else:
            row = b2c_by_rate[fact["rate"]]
            row["rate"] = fact["rate"]
            row["taxable"] = money(row["taxable"] + fact["taxable"])
            row["cgst"] = money(row["cgst"] + fact["cgst"])
            row["sgst"] = money(row["sgst"] + fact["sgst"])
            row["igst"] = money(row["igst"] + fact["igst"])
            row["cess"] = money(row["cess"] + fact["cess"])
            row["total"] = money(row["total"] + fact["total"])

    b2b_rows = sorted(b2b_by_invoice.values(), key=lambda r: (r["date"], r["voucher_no"]))
    b2c_rows = sorted(b2c_by_rate.values(), key=lambda r: r["rate"])

    # Credit/Debit notes section (GSTR-1 Table 9B): Sale Returns + Credit
    # Notes against B2B parties, which reduce outward tax liability.
    note_rows = []
    sale_returns = (
        SaleReturn.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("account", "sale_type")
        .prefetch_related("items__item")
    )
    by_return_voucher = {}
    for fact in _sale_return_line_facts(sale_returns):
        if not fact["is_b2b"]:
            continue
        row = by_return_voucher.setdefault(
            fact["voucher_no"],
            {
                "type": "Sale Return",
                "date": fact["date"],
                "voucher_no": fact["voucher_no"],
                "account": fact["account"],
                "gstin": fact["gstin"],
                "taxable": ZERO,
                "cgst": ZERO,
                "sgst": ZERO,
                "igst": ZERO,
                "cess": ZERO,
                "total": ZERO,
            },
        )
        row["taxable"] = money(row["taxable"] + fact["taxable"])
        row["cgst"] = money(row["cgst"] + fact["cgst"])
        row["sgst"] = money(row["sgst"] + fact["sgst"])
        row["igst"] = money(row["igst"] + fact["igst"])
        row["cess"] = money(row["cess"] + fact["cess"])
        row["total"] = money(row["total"] + fact["total"])
    note_rows.extend(by_return_voucher.values())

    for cn in (
        CreditNote.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("account")
        .prefetch_related("lines")
    ):
        if not cn.account.gst:
            continue
        note_rows.append(
            {
                "type": "Credit Note",
                "date": cn.date,
                "voucher_no": cn.voucher_no,
                "account": cn.account,
                "gstin": cn.account.gst,
                "taxable": cn.total_amount,
                "cgst": ZERO,
                "sgst": ZERO,
                "igst": ZERO,
                "cess": ZERO,
                "total": cn.total_amount,
            }
        )
    note_rows.sort(key=lambda r: (r["date"], r["voucher_no"]))

    b2b_total = money(sum((r["total"] for r in b2b_rows), ZERO))
    b2c_total = money(sum((r["total"] for r in b2c_rows), ZERO))
    notes_total = money(sum((r["total"] for r in note_rows), ZERO))

    return {
        "b2b_rows": b2b_rows,
        "b2b_total": b2b_total,
        "b2c_rows": b2c_rows,
        "b2c_total": b2c_total,
        "note_rows": note_rows,
        "notes_total": notes_total,
        "grand_total": money(b2b_total + b2c_total - notes_total),
    }


def trial_balance(date_from, date_to):
    rows = build_ledgers(date_from, date_to)
    total_dr = money(sum((r["debit"] for r in rows), ZERO))
    total_cr = money(sum((r["credit"] for r in rows), ZERO))
    return rows, total_dr, total_cr


def nature_total(rows, nature):
    return money(
        sum((r["balance"] for r in rows if r["nature"] == nature), ZERO)
    )


def profit_loss(date_from, date_to):
    rows = build_ledgers(date_from, date_to)
    stock = stock_figures(date_from, date_to)

    def accounts_in(*group_names):
        names = set(group_names)
        selected = []
        for row in rows:
            if row["balance"] == 0:
                continue
            group = row["group"]
            if group.name in names:
                selected.append(row)
                continue
            parent = group.under_group
            if parent and parent.name in names:
                selected.append(row)
        return selected

    sales = accounts_in("Sale", "Income (Direct/Opr.)")
    indirect_income = accounts_in("Income (Indirect)")
    purchases = accounts_in("Purchase")
    direct_exp = accounts_in("Expenses (Direct/Mfg.)")
    indirect_exp = accounts_in("Expenses (Indirect/Admn.)")

    def credit_balance(items):
        # income is credit (negative signed balance)
        return money(sum((-r["balance"] for r in items), ZERO))

    def debit_balance(items):
        return money(sum((r["balance"] for r in items), ZERO))

    sales_total = credit_balance(sales)
    purchase_total = debit_balance(purchases)
    direct_exp_total = debit_balance(direct_exp)
    indirect_income_total = credit_balance(indirect_income)
    indirect_exp_total = debit_balance(indirect_exp)

    opening = stock["opening_stock"]
    closing = stock["closing_stock"]

    debit_trading = money(opening + purchase_total + direct_exp_total)
    credit_trading = money(sales_total + closing)
    gross = money(credit_trading - debit_trading)

    if gross >= 0:
        gross_profit, gross_loss = gross, ZERO
    else:
        gross_profit, gross_loss = ZERO, money(-gross)

    net = money(gross_profit - gross_loss + indirect_income_total - indirect_exp_total)
    if net >= 0:
        net_profit, net_loss = net, ZERO
    else:
        net_profit, net_loss = ZERO, money(-net)

    return {
        "sales": sales,
        "purchases": purchases,
        "direct_exp": direct_exp,
        "indirect_income": indirect_income,
        "indirect_exp": indirect_exp,
        "opening_stock": opening,
        "closing_stock": closing,
        "sales_total": sales_total,
        "purchase_total": purchase_total,
        "direct_exp_total": direct_exp_total,
        "indirect_income_total": indirect_income_total,
        "indirect_exp_total": indirect_exp_total,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_profit": net_profit,
        "net_loss": net_loss,
        "left_total": money(opening + purchase_total + direct_exp_total + gross_profit),
        "right_total": money(sales_total + closing + gross_loss),
    }


def balance_sheet(date_from, date_to):
    rows = build_ledgers(date_from, date_to)
    pl = profit_loss(date_from, date_to)
    stock = stock_figures(date_from, date_to)

    def by_primary(*natures):
        buckets = defaultdict(list)
        for row in rows:
            if row["nature"] not in natures:
                continue
            if row["account"].account_name in ("Stock-in-hand", "Stock"):
                continue
            if row["account"].account_name in ("Profit & Loss A/c", "Profit & Loss"):
                continue
            primary = row["group"]
            while primary.under_group_id:
                primary = primary.under_group
            buckets[primary.name].append(row)
        return buckets

    assets = by_primary(AccountGroup.Nature.ASSET)
    liabilities = by_primary(
        AccountGroup.Nature.LIABILITY, AccountGroup.Nature.EQUITY
    )

    def side_total(buckets, sign="asset"):
        total = ZERO
        groups = []
        for name, items in sorted(buckets.items()):
            group_total = ZERO
            lines = []
            for row in items:
                if sign == "asset":
                    amt = row["balance"]
                else:
                    amt = money(-row["balance"])
                if amt == 0:
                    continue
                group_total += amt
                lines.append({"name": row["account"].account_name, "amount": amt})
            if lines:
                groups.append({"name": name, "lines": lines, "total": money(group_total)})
                total += group_total
        return groups, money(total)

    asset_groups, asset_total = side_total(assets, "asset")
    asset_groups.append(
        {
            "name": "Stock-in-hand",
            "lines": [{"name": "Closing Stock", "amount": stock["closing_stock"]}],
            "total": stock["closing_stock"],
        }
    )
    asset_total = money(asset_total + stock["closing_stock"])

    liab_groups, liab_total = side_total(liabilities, "liability")
    pl_amount = money(pl["net_profit"] - pl["net_loss"])
    liab_groups.append(
        {
            "name": "Profit & Loss",
            "lines": [
                {
                    "name": "Current Period Profit" if pl_amount >= 0 else "Current Period Loss",
                    "amount": pl_amount,
                }
            ],
            "total": pl_amount,
        }
    )
    liab_total = money(liab_total + pl_amount)

    return {
        "assets": asset_groups,
        "liabilities": liab_groups,
        "asset_total": asset_total,
        "liability_total": liab_total,
        "difference": money(asset_total - liab_total),
        "net_profit": pl["net_profit"],
        "net_loss": pl["net_loss"],
    }


def sales_register(date_from, date_to):
    rows = []
    total = ZERO
    qs = (
        Sale.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("account", "sale_type")
        .prefetch_related("items", "bill_sundries__bill_sundry")
    )
    for sale in qs:
        totals = sale.totals()
        total += totals["net_amount"]
        rows.append({"voucher": sale, "totals": totals})
    return rows, money(total)


def purchase_register(date_from, date_to):
    rows = []
    total = ZERO
    qs = (
        Purchase.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("account", "purchase_type")
        .prefetch_related("items", "bill_sundries__bill_sundry")
    )
    for purchase in qs:
        totals = purchase.totals()
        total += totals["net_amount"]
        rows.append({"voucher": purchase, "totals": totals})
    return rows, money(total)


def sale_return_register(date_from, date_to):
    rows = []
    total = ZERO
    qs = (
        SaleReturn.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("account", "sale_type", "against_sale")
        .prefetch_related("items", "bill_sundries__bill_sundry")
    )
    for sr in qs:
        totals = sr.totals()
        total += totals["net_amount"]
        rows.append({"voucher": sr, "totals": totals})
    return rows, money(total)


def purchase_return_register(date_from, date_to):
    rows = []
    total = ZERO
    qs = (
        PurchaseReturn.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("account", "purchase_type", "against_purchase")
        .prefetch_related("items", "bill_sundries__bill_sundry")
    )
    for pr in qs:
        totals = pr.totals()
        total += totals["net_amount"]
        rows.append({"voucher": pr, "totals": totals})
    return rows, money(total)


def credit_note_register(date_from, date_to):
    rows = list(
        CreditNote.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("account", "against_sale")
        .prefetch_related("lines__account")
    )
    total = money(sum((r.total_amount for r in rows), ZERO))
    return rows, total


def debit_note_register(date_from, date_to):
    rows = list(
        DebitNote.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("account", "against_purchase")
        .prefetch_related("lines__account")
    )
    total = money(sum((r.total_amount for r in rows), ZERO))
    return rows, total


def payment_register(date_from, date_to):
    rows = list(
        Payment.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("through")
        .prefetch_related("lines__account")
    )
    total = money(sum((r.total_amount for r in rows), ZERO))
    return rows, total


def receipt_register(date_from, date_to):
    rows = list(
        Receipt.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("through")
        .prefetch_related("lines__account")
    )
    total = money(sum((r.total_amount for r in rows), ZERO))
    return rows, total


def journal_register(date_from, date_to):
    rows = []
    total = ZERO
    qs = (
        Journal.objects.filter(date__gte=date_from, date__lte=date_to)
        .prefetch_related("lines", "lines__account")
    )
    for jv in qs:
        amount = jv.totals()["debit"]
        total += amount
        rows.append(jv)
    return rows, money(total)


def _append_entry(entries, date, vtype, vno, narration, debit, credit):
    debit = money(debit)
    credit = money(credit)
    if debit == 0 and credit == 0:
        return
    entries.append(
        {
            "date": date,
            "vtype": vtype,
            "voucher_no": vno,
            "narration": narration or "",
            "debit": debit,
            "credit": credit,
        }
    )


def _voucher_entries_for_account(account):
    entries = []
    acc_id = account.id

    sales = Sale.objects.select_related(
        "account",
        "sale_type",
        "sale_type__sales_account",
        "sale_type__tax_account",
        "sale_type__tax_account_2",
    ).prefetch_related(
        Prefetch("items", queryset=SaleItem.objects.select_related("item", "item__sale_account")),
        Prefetch(
            "bill_sundries",
            queryset=SaleBillSundry.objects.select_related(
                "bill_sundry", "bill_sundry__posting_account_sale"
            ),
        ),
    )
    for sale in sales:
        totals = sale.totals()
        if sale.account_id == acc_id:
            _append_entry(
                entries, sale.date, "Sale", sale.invoice_no, sale.narration, totals["net_amount"], 0
            )
        sales_acc = sale.sale_type.sales_account if sale.sale_type_id else None
        for line in sale.items.all():
            line_acc = line.item.sale_account if (line.item_id and line.item.sale_account_id) else sales_acc
            if line_acc and line_acc.id == acc_id:
                _append_entry(
                    entries, sale.date, "Sale", sale.invoice_no, sale.narration, 0, line.amount_after_discount
                )
        if sale.sale_type_id and totals["tax_amount"]:
            for tax_acc, tax_amt in sale.sale_type.tax_postings(totals["tax_amount"]):
                if tax_acc and tax_acc.id == acc_id:
                    _append_entry(
                        entries, sale.date, "Sale", sale.invoice_no, sale.narration, 0, tax_amt
                    )
        for line, signed in zip(sale.bill_sundries.all(), totals["sundry_signed_amounts"]):
            acc = line.bill_sundry.posting_account_sale or sales_acc
            if not acc or acc.id != acc_id:
                continue
            if signed >= 0:
                _append_entry(entries, sale.date, "Sale", sale.invoice_no, sale.narration, 0, signed)
            else:
                _append_entry(
                    entries, sale.date, "Sale", sale.invoice_no, sale.narration, -signed, 0
                )

    purchases = Purchase.objects.select_related(
        "account",
        "purchase_type",
        "purchase_type__purchase_account",
        "purchase_type__tax_account",
        "purchase_type__tax_account_2",
        "purchase_type__rcm_payable_account",
    ).prefetch_related(
        Prefetch("items", queryset=PurchaseItem.objects.select_related("item", "item__purchase_account")),
        Prefetch(
            "bill_sundries",
            queryset=PurchaseBillSundry.objects.select_related(
                "bill_sundry", "bill_sundry__posting_account_purchase"
            ),
        ),
    )
    for purchase in purchases:
        totals = purchase.totals()
        purchase_acc = (
            purchase.purchase_type.purchase_account if purchase.purchase_type_id else None
        )
        rcm_acc = (
            purchase.purchase_type.rcm_payable_account
            if purchase.purchase_type_id and purchase.is_reverse_charge
            else None
        )
        if rcm_acc and totals["tax_amount"]:
            party_amount = money(totals["net_amount"] - totals["tax_amount"])
            if purchase.account_id == acc_id:
                _append_entry(
                    entries, purchase.date, "Purchase", purchase.invoice_no, purchase.narration, 0, party_amount
                )
            if rcm_acc.id == acc_id:
                _append_entry(
                    entries,
                    purchase.date,
                    "Purchase (RCM payable)",
                    purchase.invoice_no,
                    purchase.narration,
                    0,
                    totals["tax_amount"],
                )
        elif purchase.account_id == acc_id:
            _append_entry(
                entries,
                purchase.date,
                "Purchase",
                purchase.invoice_no,
                purchase.narration,
                0,
                totals["net_amount"],
            )
        for line in purchase.items.all():
            line_acc = (
                line.item.purchase_account if (line.item_id and line.item.purchase_account_id) else purchase_acc
            )
            if line_acc and line_acc.id == acc_id:
                _append_entry(
                    entries,
                    purchase.date,
                    "Purchase",
                    purchase.invoice_no,
                    purchase.narration,
                    line.amount_after_discount,
                    0,
                )
        if purchase.purchase_type_id and totals["tax_amount"]:
            for tax_acc, tax_amt in purchase.purchase_type.tax_postings(totals["tax_amount"]):
                if tax_acc and tax_acc.id == acc_id:
                    _append_entry(
                        entries,
                        purchase.date,
                        "Purchase",
                        purchase.invoice_no,
                        purchase.narration,
                        tax_amt,
                        0,
                    )
        for line, signed in zip(purchase.bill_sundries.all(), totals["sundry_signed_amounts"]):
            acc = line.bill_sundry.posting_account_purchase or purchase_acc
            if not acc or acc.id != acc_id:
                continue
            if signed >= 0:
                _append_entry(
                    entries,
                    purchase.date,
                    "Purchase",
                    purchase.invoice_no,
                    purchase.narration,
                    signed,
                    0,
                )
            else:
                _append_entry(
                    entries,
                    purchase.date,
                    "Purchase",
                    purchase.invoice_no,
                    purchase.narration,
                    0,
                    -signed,
                )

    sale_returns = SaleReturn.objects.select_related(
        "account",
        "sale_type",
        "sale_type__sales_account",
        "sale_type__sales_return_account",
        "sale_type__tax_account",
        "sale_type__tax_account_2",
    ).prefetch_related(
        Prefetch("items", queryset=SaleReturnItem.objects.select_related("item", "item__sale_account")),
        Prefetch(
            "bill_sundries",
            queryset=SaleReturnBillSundry.objects.select_related(
                "bill_sundry", "bill_sundry__posting_account_sale"
            ),
        ),
    )
    for sr in sale_returns:
        totals = sr.totals()
        if sr.account_id == acc_id:
            _append_entry(
                entries, sr.date, "Sale Return", sr.voucher_no, sr.narration, 0, totals["net_amount"]
            )
        return_acc = sr.sale_type.effective_sales_return_account if sr.sale_type_id else None
        for line in sr.items.all():
            line_acc = line.item.sale_account if (line.item_id and line.item.sale_account_id) else return_acc
            if line_acc and line_acc.id == acc_id:
                _append_entry(
                    entries, sr.date, "Sale Return", sr.voucher_no, sr.narration, line.amount_after_discount, 0
                )
        if sr.sale_type_id and totals["tax_amount"]:
            for tax_acc, tax_amt in sr.sale_type.tax_postings(totals["tax_amount"]):
                if tax_acc and tax_acc.id == acc_id:
                    _append_entry(entries, sr.date, "Sale Return", sr.voucher_no, sr.narration, tax_amt, 0)
        for line, signed in zip(sr.bill_sundries.all(), totals["sundry_signed_amounts"]):
            acc = line.bill_sundry.posting_account_sale or return_acc
            if not acc or acc.id != acc_id:
                continue
            if signed >= 0:
                _append_entry(entries, sr.date, "Sale Return", sr.voucher_no, sr.narration, signed, 0)
            else:
                _append_entry(entries, sr.date, "Sale Return", sr.voucher_no, sr.narration, 0, -signed)

    purchase_returns = PurchaseReturn.objects.select_related(
        "account",
        "purchase_type",
        "purchase_type__purchase_account",
        "purchase_type__purchase_return_account",
        "purchase_type__tax_account",
        "purchase_type__tax_account_2",
    ).prefetch_related(
        Prefetch("items", queryset=PurchaseReturnItem.objects.select_related("item", "item__purchase_account")),
        Prefetch(
            "bill_sundries",
            queryset=PurchaseReturnBillSundry.objects.select_related(
                "bill_sundry", "bill_sundry__posting_account_purchase"
            ),
        ),
    )
    for pr in purchase_returns:
        totals = pr.totals()
        if pr.account_id == acc_id:
            _append_entry(
                entries, pr.date, "Purchase Return", pr.voucher_no, pr.narration, totals["net_amount"], 0
            )
        return_acc = pr.purchase_type.effective_purchase_return_account if pr.purchase_type_id else None
        for line in pr.items.all():
            line_acc = (
                line.item.purchase_account if (line.item_id and line.item.purchase_account_id) else return_acc
            )
            if line_acc and line_acc.id == acc_id:
                _append_entry(
                    entries, pr.date, "Purchase Return", pr.voucher_no, pr.narration, 0, line.amount_after_discount
                )
        if pr.purchase_type_id and totals["tax_amount"]:
            for tax_acc, tax_amt in pr.purchase_type.tax_postings(totals["tax_amount"]):
                if tax_acc and tax_acc.id == acc_id:
                    _append_entry(entries, pr.date, "Purchase Return", pr.voucher_no, pr.narration, 0, tax_amt)
        for line, signed in zip(pr.bill_sundries.all(), totals["sundry_signed_amounts"]):
            acc = line.bill_sundry.posting_account_purchase or return_acc
            if not acc or acc.id != acc_id:
                continue
            if signed >= 0:
                _append_entry(entries, pr.date, "Purchase Return", pr.voucher_no, pr.narration, 0, signed)
            else:
                _append_entry(entries, pr.date, "Purchase Return", pr.voucher_no, pr.narration, -signed, 0)

    for cn in CreditNote.objects.select_related("account").prefetch_related("lines__account"):
        if cn.account_id == acc_id:
            _append_entry(entries, cn.date, "Credit Note", cn.voucher_no, cn.narration, 0, cn.total_amount)
        for line in cn.lines.all():
            if line.account_id == acc_id:
                _append_entry(entries, cn.date, "Credit Note", cn.voucher_no, cn.narration, line.amount, 0)

    for dn in DebitNote.objects.select_related("account").prefetch_related("lines__account"):
        if dn.account_id == acc_id:
            _append_entry(entries, dn.date, "Debit Note", dn.voucher_no, dn.narration, dn.total_amount, 0)
        for line in dn.lines.all():
            if line.account_id == acc_id:
                _append_entry(entries, dn.date, "Debit Note", dn.voucher_no, dn.narration, 0, line.amount)

    for pmt in Payment.objects.select_related("through").prefetch_related("lines__account"):
        for line in pmt.lines.all():
            if line.account_id == acc_id:
                _append_entry(entries, pmt.date, "Payment", pmt.voucher_no, pmt.narration, line.amount, 0)
        if pmt.through_id == acc_id:
            _append_entry(entries, pmt.date, "Payment", pmt.voucher_no, pmt.narration, 0, pmt.total_amount)

    for rec in Receipt.objects.select_related("through").prefetch_related("lines__account"):
        if rec.through_id == acc_id:
            _append_entry(entries, rec.date, "Receipt", rec.voucher_no, rec.narration, rec.total_amount, 0)
        for line in rec.lines.all():
            if line.account_id == acc_id:
                _append_entry(entries, rec.date, "Receipt", rec.voucher_no, rec.narration, 0, line.amount)

    journals = (
        Journal.objects.filter(lines__account_id=acc_id)
        .distinct()
        .prefetch_related(
            Prefetch("lines", queryset=JournalLine.objects.select_related("account"))
        )
    )
    for jv in journals:
        for line in jv.lines.all():
            if line.account_id != acc_id:
                continue
            _append_entry(
                entries,
                jv.date,
                "Journal",
                jv.voucher_no,
                line.remarks or jv.narration,
                line.debit,
                line.credit,
            )

    entries.sort(key=lambda e: (e["date"], e["vtype"], e["voucher_no"]))
    return entries


def account_ledger(account, date_from, date_to):
    opening = money(account.opening)
    opening_dr = opening if account.opening_type == Account.OpeningType.DR else ZERO
    opening_cr = opening if account.opening_type == Account.OpeningType.CR else ZERO
    all_entries = _voucher_entries_for_account(account)

    for entry in all_entries:
        if entry["date"] < date_from:
            opening_dr += entry["debit"]
            opening_cr += entry["credit"]

    period = [e for e in all_entries if date_from <= e["date"] <= date_to]
    running = money(opening_dr - opening_cr)
    rows = []
    for entry in period:
        running = money(running + entry["debit"] - entry["credit"])
        rows.append(
            {
                **entry,
                "balance": abs(running),
                "dr_cr": "Dr" if running >= 0 else "Cr",
            }
        )

    period_dr = money(sum((e["debit"] for e in period), ZERO))
    period_cr = money(sum((e["credit"] for e in period), ZERO))
    closing = money(opening_dr - opening_cr + period_dr - period_cr)
    return {
        "account": account,
        "opening_dr": opening_dr,
        "opening_cr": opening_cr,
        "opening_balance": abs(money(opening_dr - opening_cr)),
        "opening_dr_cr": "Dr" if (opening_dr - opening_cr) >= 0 else "Cr",
        "rows": rows,
        "period_dr": period_dr,
        "period_cr": period_cr,
        "closing_balance": abs(closing),
        "closing_dr_cr": "Dr" if closing >= 0 else "Cr",
    }
