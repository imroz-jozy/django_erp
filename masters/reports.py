from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Prefetch, Sum

from .models import (
    Account,
    AccountGroup,
    Item,
    Payment,
    Purchase,
    PurchaseBillSundry,
    PurchaseItem,
    Receipt,
    Sale,
    SaleBillSundry,
    SaleItem,
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
        .select_related("account", "sale_type", "sale_type__sales_account", "sale_type__tax_account")
        .prefetch_related(
            Prefetch("items", queryset=SaleItem.objects.select_related("item")),
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
        _post(ledgers, sales_acc, credit=totals["item_amount"])
        tax_acc = sale.sale_type.tax_account if sale.sale_type_id else None
        if totals["tax_amount"]:
            _post(ledgers, tax_acc, credit=totals["tax_amount"])
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
        )
        .prefetch_related(
            Prefetch("items", queryset=PurchaseItem.objects.select_related("item")),
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
        _post(ledgers, purchase.account, credit=totals["net_amount"])
        purchase_acc = (
            purchase.purchase_type.purchase_account if purchase.purchase_type_id else None
        )
        _post(ledgers, purchase_acc, debit=totals["item_amount"])
        tax_acc = purchase.purchase_type.tax_account if purchase.purchase_type_id else None
        if totals["tax_amount"]:
            _post(ledgers, tax_acc, debit=totals["tax_amount"])
        for line, signed in zip(purchase.bill_sundries.all(), totals["sundry_signed_amounts"]):
            acc = line.bill_sundry.posting_account_purchase or purchase_acc
            if signed >= 0:
                _post(ledgers, acc, debit=signed)
            else:
                _post(ledgers, acc, credit=-signed)

    payments = Payment.objects.filter(date__gte=date_from, date__lte=date_to).select_related(
        "account", "through"
    )
    for pmt in payments:
        _post(ledgers, pmt.account, debit=pmt.amount)
        _post(ledgers, pmt.through, credit=pmt.amount)

    receipts = Receipt.objects.filter(date__gte=date_from, date__lte=date_to).select_related(
        "account", "through"
    )
    for rec in receipts:
        _post(ledgers, rec.through, debit=rec.amount)
        _post(ledgers, rec.account, credit=rec.amount)

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
    """
    opening_total = money(
        Item.objects.aggregate(total=Sum("opening_value"))["total"] or 0
    )

    # Accumulate period purchases per item
    purchase_qty = defaultdict(lambda: ZERO)
    purchase_amt = defaultdict(lambda: ZERO)
    purchase_value_total = ZERO

    for line in PurchaseItem.objects.filter(
        purchase__date__gte=date_from, purchase__date__lte=date_to
    ).select_related("item"):
        purchase_qty[line.item_id] += money(line.quantity)
        purchase_amt[line.item_id] += line.amount_after_discount
        purchase_value_total += line.amount_after_discount

    # Accumulate period sales per item
    sale_qty = defaultdict(lambda: ZERO)
    for line in SaleItem.objects.filter(
        sale__date__gte=date_from, sale__date__lte=date_to
    ).select_related("item"):
        sale_qty[line.item_id] += money(line.quantity)

    stock_rows = []
    closing_qty_value = ZERO
    sale_cogs = ZERO

    for item in Item.objects.all():
        op_qty = money(item.opening_main)
        op_val = money(item.opening_value)
        pur_qty = purchase_qty[item.id]
        pur_val = purchase_amt[item.id]
        sol_qty = sale_qty[item.id]

        total_qty_in = op_qty + pur_qty          # total stock received
        total_val_in = op_val + pur_val          # total value received

        # Weighted Average Rate
        if total_qty_in > 0:
            war = money(total_val_in / total_qty_in)
        elif item.purchase_price:
            war = money(item.purchase_price)      # fallback to master rate
        else:
            war = ZERO

        closing_qty = total_qty_in - sol_qty
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


def payment_register(date_from, date_to):
    rows = list(
        Payment.objects.filter(date__gte=date_from, date__lte=date_to).select_related(
            "account", "through"
        )
    )
    total = money(sum((r.amount for r in rows), ZERO))
    return rows, total


def receipt_register(date_from, date_to):
    rows = list(
        Receipt.objects.filter(date__gte=date_from, date__lte=date_to).select_related(
            "account", "through"
        )
    )
    total = money(sum((r.amount for r in rows), ZERO))
    return rows, total


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
        "account", "sale_type", "sale_type__sales_account", "sale_type__tax_account"
    ).prefetch_related(
        Prefetch("items", queryset=SaleItem.objects.select_related("item")),
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
        if sales_acc and sales_acc.id == acc_id:
            _append_entry(
                entries, sale.date, "Sale", sale.invoice_no, sale.narration, 0, totals["item_amount"]
            )
        tax_acc = sale.sale_type.tax_account if sale.sale_type_id else None
        if tax_acc and tax_acc.id == acc_id and totals["tax_amount"]:
            _append_entry(
                entries, sale.date, "Sale", sale.invoice_no, sale.narration, 0, totals["tax_amount"]
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
    ).prefetch_related(
        Prefetch("items", queryset=PurchaseItem.objects.select_related("item")),
        Prefetch(
            "bill_sundries",
            queryset=PurchaseBillSundry.objects.select_related(
                "bill_sundry", "bill_sundry__posting_account_purchase"
            ),
        ),
    )
    for purchase in purchases:
        totals = purchase.totals()
        if purchase.account_id == acc_id:
            _append_entry(
                entries,
                purchase.date,
                "Purchase",
                purchase.invoice_no,
                purchase.narration,
                0,
                totals["net_amount"],
            )
        purchase_acc = (
            purchase.purchase_type.purchase_account if purchase.purchase_type_id else None
        )
        if purchase_acc and purchase_acc.id == acc_id:
            _append_entry(
                entries,
                purchase.date,
                "Purchase",
                purchase.invoice_no,
                purchase.narration,
                totals["item_amount"],
                0,
            )
        tax_acc = purchase.purchase_type.tax_account if purchase.purchase_type_id else None
        if tax_acc and tax_acc.id == acc_id and totals["tax_amount"]:
            _append_entry(
                entries,
                purchase.date,
                "Purchase",
                purchase.invoice_no,
                purchase.narration,
                totals["tax_amount"],
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

    for pmt in Payment.objects.select_related("account", "through"):
        if pmt.account_id == acc_id:
            _append_entry(entries, pmt.date, "Payment", pmt.voucher_no, pmt.narration, pmt.amount, 0)
        if pmt.through_id == acc_id:
            _append_entry(entries, pmt.date, "Payment", pmt.voucher_no, pmt.narration, 0, pmt.amount)

    for rec in Receipt.objects.select_related("account", "through"):
        if rec.through_id == acc_id:
            _append_entry(entries, rec.date, "Receipt", rec.voucher_no, rec.narration, rec.amount, 0)
        if rec.account_id == acc_id:
            _append_entry(entries, rec.date, "Receipt", rec.voucher_no, rec.narration, 0, rec.amount)

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
