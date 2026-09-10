from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django import forms
from django.forms.models import BaseInlineFormSet
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .models import (
    Account,
    AccountGroup,
    BillSundry,
    Item,
    Journal,
    JournalLine,
    Payment,
    PaymentLine,
    Purchase,
    PurchaseBillSundry,
    PurchaseItem,
    PurchaseType,
    Receipt,
    ReceiptLine,
    Sale,
    SaleBillSundry,
    SaleItem,
    SaleType,
    Unit,
)
from .money import ZERO, money
from .excel_service import (
    OPENPYXL_AVAILABLE,
    generate_item_template,
    import_items_from_excel,
    generate_account_template,
    import_accounts_from_excel,
    generate_account_group_template,
    import_account_groups_from_excel,
    generate_sale_template,
    import_sales_from_excel,
    generate_purchase_template,
    import_purchases_from_excel,
    generate_payment_template,
    import_payments_from_excel,
    generate_receipt_template,
    import_receipts_from_excel,
    generate_journal_template,
    import_journals_from_excel,
    excel_download_response,
)
from .reports import (
    account_ledger,
    balance_sheet,
    journal_register,
    payment_register,
    period_from_request,
    profit_loss,
    purchase_register,
    receipt_register,
    sales_register,
    stock_figures,
    trial_balance,
)

admin.site.site_header = "ERP"
admin.site.site_title = "ERP Admin"
admin.site.index_title = "Masters, Vouchers & Reports"
admin.site.index_template = "admin/erp_index.html"


def _report_context(request, title, extra):
    date_from, date_to = period_from_request(request)
    ctx = {
        **admin.site.each_context(request),
        "title": title,
        "date_from": date_from,
        "date_to": date_to,
    }
    ctx.update(extra)
    return ctx


def profit_loss_view(request):
    date_from, date_to = period_from_request(request)
    data = profit_loss(date_from, date_to)
    return TemplateResponse(
        request,
        "admin/masters/report_profit_loss.html",
        _report_context(request, "Profit & Loss", data),
    )


def balance_sheet_view(request):
    date_from, date_to = period_from_request(request)
    data = balance_sheet(date_from, date_to)
    return TemplateResponse(
        request,
        "admin/masters/report_balance_sheet.html",
        _report_context(request, "Balance Sheet", data),
    )


def trial_balance_view(request):
    date_from, date_to = period_from_request(request)
    rows, total_dr, total_cr = trial_balance(date_from, date_to)
    return TemplateResponse(
        request,
        "admin/masters/report_trial_balance.html",
        _report_context(
            request,
            "Trial Balance",
            {"rows": rows, "total_dr": total_dr, "total_cr": total_cr},
        ),
    )


def sales_register_view(request):
    date_from, date_to = period_from_request(request)
    rows, total = sales_register(date_from, date_to)
    return TemplateResponse(
        request,
        "admin/masters/report_register.html",
        _report_context(
            request,
            "Sales Register",
            {"rows": rows, "total": total, "party_label": "Customer"},
        ),
    )


def purchase_register_view(request):
    date_from, date_to = period_from_request(request)
    rows, total = purchase_register(date_from, date_to)
    return TemplateResponse(
        request,
        "admin/masters/report_register.html",
        _report_context(
            request,
            "Purchase Register",
            {"rows": rows, "total": total, "party_label": "Supplier"},
        ),
    )


def stock_summary_view(request):
    date_from, date_to = period_from_request(request)
    data = stock_figures(date_from, date_to)
    return TemplateResponse(
        request,
        "admin/masters/report_stock.html",
        _report_context(request, "Stock Summary", data),
    )


def payment_register_view(request):
    date_from, date_to = period_from_request(request)
    rows, total = payment_register(date_from, date_to)
    return TemplateResponse(
        request,
        "admin/masters/report_cash.html",
        _report_context(
            request,
            "Payment Register",
            {"rows": rows, "total": total, "party_label": "Paid to"},
        ),
    )


def receipt_register_view(request):
    date_from, date_to = period_from_request(request)
    rows, total = receipt_register(date_from, date_to)
    return TemplateResponse(
        request,
        "admin/masters/report_cash.html",
        _report_context(
            request,
            "Receipt Register",
            {"rows": rows, "total": total, "party_label": "Received from"},
        ),
    )


def journal_register_view(request):
    date_from, date_to = period_from_request(request)
    rows, total = journal_register(date_from, date_to)
    return TemplateResponse(
        request,
        "admin/masters/report_journal.html",
        _report_context(
            request,
            "Journal Register",
            {"rows": rows, "total": total},
        ),
    )


def ledger_view(request, account_id=None):
    date_from, date_to = period_from_request(request)
    if account_id is None:
        account_id = request.GET.get("account")
        if account_id:
            return redirect(
                f"{reverse('admin:erp_ledger', args=[account_id])}"
                f"?from={date_from:%Y-%m-%d}&to={date_to:%Y-%m-%d}"
            )
        return TemplateResponse(
            request,
            "admin/masters/report_ledger.html",
            _report_context(
                request,
                "Ledger",
                {
                    "accounts": Account.objects.select_related("account_group"),
                    "data": None,
                },
            ),
        )
    account = get_object_or_404(Account, pk=account_id)
    data = account_ledger(account, date_from, date_to)
    return TemplateResponse(
        request,
        "admin/masters/report_ledger.html",
        _report_context(
            request,
            f"Ledger — {account.account_name}",
            {
                "accounts": Account.objects.select_related("account_group"),
                "data": data,
            },
        ),
    )


def item_detail_view(request, item_id):
    item = get_object_or_404(Item, pk=item_id)
    return JsonResponse({
        "success": True,
        "main_unit_id": item.main_unit.id if item.main_unit else None,
        "main_unit_name": item.main_unit.name if item.main_unit else "",
        "tax": float(item.tax),
        "sale_price": float(item.sale_price),
        "purchase_price": float(item.purchase_price),
    })


ITEM_COLUMN_GUIDE = [
    {"name": "Item Name *", "type": "Text", "required": True, "description": "Unique item name. E.g., 'Laptop Dell Inspiron 15'"},
    {"name": "Item Group", "type": "Text", "required": False, "description": "Category or group of the item. E.g., 'Electronics', 'Hardware'"},
    {"name": "Main Unit *", "type": "Text", "required": True, "description": "Primary measurement unit (e.g. PCS, NOS, KGS, MTR). Auto-created if new."},
    {"name": "Alt Unit", "type": "Text", "required": False, "description": "Alternative measurement unit (e.g. BOX, CARTON)."},
    {"name": "Conversion Factor", "type": "Number", "required": False, "description": "1 Main Unit = Conversion Alt Units (default 1)."},
    {"name": "HSN Code", "type": "Digits", "required": False, "description": "Harmonized System of Nomenclature code (digits only)."},
    {"name": "Tax Rate %", "type": "Number", "required": False, "description": "GST tax percentage rate (e.g. 0, 5, 12, 18, 28)."},
    {"name": "Sale Price", "type": "Number", "required": False, "description": "Default selling rate per main unit."},
    {"name": "Purchase Price", "type": "Number", "required": False, "description": "Default buying rate per main unit."},
    {"name": "MRP", "type": "Number", "required": False, "description": "Maximum Retail Price per unit."},
    {"name": "Opening Qty", "type": "Number", "required": False, "description": "Opening stock quantity on hand."},
    {"name": "Opening Value", "type": "Number", "required": False, "description": "Total valuation of opening stock."},
]

ACCOUNT_COLUMN_GUIDE = [
    {"name": "Account Name *", "type": "Text", "required": True, "description": "Unique ledger / party name. E.g., 'Apex Infotech Pvt Ltd'"},
    {"name": "Account Group *", "type": "Text", "required": True, "description": "Existing Account Group name (e.g., 'Sundry Debtors', 'Sundry Creditors', 'Bank Accounts')."},
    {"name": "Opening Balance", "type": "Number", "required": False, "description": "Opening debit or credit balance (default 0)."},
    {"name": "Opening Type (DR/CR)", "type": "Text", "required": False, "description": "DR for Debit (receivable/asset) or CR for Credit (payable/liability). Default DR."},
    {"name": "Address", "type": "Text", "required": False, "description": "Billing/Office address of the party."},
    {"name": "State", "type": "Text", "required": False, "description": "State name (e.g., 'Maharashtra', 'Karnataka', 'Delhi')."},
    {"name": "GSTIN", "type": "Text", "required": False, "description": "15-digit GST identification number."},
    {"name": "Is Registered (Yes/No)", "type": "Text", "required": False, "description": "Enter 'Yes' if registered under GST, otherwise 'No'."},
    {"name": "Mobile No", "type": "Text", "required": False, "description": "Contact phone or mobile number."},
]


def item_template_view(request):
    if not OPENPYXL_AVAILABLE:
        messages.error(request, "openpyxl is not installed. Please install it using: pip install openpyxl")
        return HttpResponseRedirect(reverse("admin:erp_item_import"))
    buffer = generate_item_template()
    return excel_download_response(buffer, "Item_Import_Template.xlsx")


def item_import_view(request):
    ctx = {
        **admin.site.each_context(request),
        "title": "Import Items from Excel",
        "model_name": "Item",
        "model_name_plural": "Items",
        "changelist_url": reverse("admin:masters_item_changelist"),
        "template_url": reverse("admin:erp_item_template"),
        "column_guide": ITEM_COLUMN_GUIDE,
        "package_missing": not OPENPYXL_AVAILABLE,
        "result": None,
    }
    if request.method == "POST":
        if not OPENPYXL_AVAILABLE:
            messages.error(request, "openpyxl is not installed. Please install it using: pip install openpyxl")
            return TemplateResponse(request, "admin/masters/import_excel.html", ctx)
        excel_file = request.FILES.get("excel_file")
        if not excel_file:
            messages.error(request, "Please choose an Excel file to upload.")
            return TemplateResponse(request, "admin/masters/import_excel.html", ctx)
        update_existing = request.POST.get("update_existing") == "1"
        result = import_items_from_excel(excel_file, update_existing=update_existing)
        ctx["result"] = result
        if result["errors"]:
            messages.warning(
                request,
                f"Import completed with {len(result['errors'])} error(s). Please review details below."
            )
        else:
            messages.success(
                request,
                f"Successfully processed items! Added: {result['created']}, Updated: {result['updated']}, Skipped: {result['skipped']}."
            )
    return TemplateResponse(request, "admin/masters/import_excel.html", ctx)


def account_template_view(request):
    if not OPENPYXL_AVAILABLE:
        messages.error(request, "openpyxl is not installed. Please install it using: pip install openpyxl")
        return HttpResponseRedirect(reverse("admin:erp_account_import"))
    buffer = generate_account_template()
    return excel_download_response(buffer, "Account_Import_Template.xlsx")


def account_import_view(request):
    ctx = {
        **admin.site.each_context(request),
        "title": "Import Accounts from Excel",
        "model_name": "Account",
        "model_name_plural": "Accounts",
        "changelist_url": reverse("admin:masters_account_changelist"),
        "template_url": reverse("admin:erp_account_template"),
        "column_guide": ACCOUNT_COLUMN_GUIDE,
        "package_missing": not OPENPYXL_AVAILABLE,
        "result": None,
    }
    if request.method == "POST":
        if not OPENPYXL_AVAILABLE:
            messages.error(request, "openpyxl is not installed. Please install it using: pip install openpyxl")
            return TemplateResponse(request, "admin/masters/import_excel.html", ctx)
        excel_file = request.FILES.get("excel_file")
        if not excel_file:
            messages.error(request, "Please choose an Excel file to upload.")
            return TemplateResponse(request, "admin/masters/import_excel.html", ctx)
        update_existing = request.POST.get("update_existing") == "1"
        result = import_accounts_from_excel(excel_file, update_existing=update_existing)
        ctx["result"] = result
        if result["errors"]:
            messages.warning(
                request,
                f"Import completed with {len(result['errors'])} error(s). Please review details below."
            )
        else:
            messages.success(
                request,
                f"Successfully processed accounts! Added: {result['created']}, Updated: {result['updated']}, Skipped: {result['skipped']}."
            )
    return TemplateResponse(request, "admin/masters/import_excel.html", ctx)


def account_group_template_view(request):
    if not OPENPYXL_AVAILABLE:
        messages.error(request, "openpyxl is not installed. Please install it using: pip install openpyxl")
        return HttpResponseRedirect(reverse("admin:erp_account_group_import"))
    return excel_download_response(generate_account_group_template(), "Account_Group_Import_Template.xlsx")


def account_group_import_view(request):
    ctx = {
        **admin.site.each_context(request),
        "title": "Import Account Groups from Excel",
        "model_name": "Account Group",
        "model_name_plural": "Account Groups",
        "changelist_url": reverse("admin:masters_accountgroup_changelist"),
        "template_url": reverse("admin:erp_account_group_template"),
        "column_guide": ACCOUNT_GROUP_COLUMN_GUIDE,
        "package_missing": not OPENPYXL_AVAILABLE,
        "result": None,
    }
    if request.method == "POST":
        if not OPENPYXL_AVAILABLE:
            messages.error(request, "openpyxl is not installed. Please install it using: pip install openpyxl")
        elif not (excel_file := request.FILES.get("excel_file")):
            messages.error(request, "Please choose an Excel file to upload.")
        else:
            result = import_account_groups_from_excel(excel_file, update_existing=request.POST.get("update_existing") == "1")
            ctx["result"] = result
            if result["errors"]:
                messages.warning(request, f"Import completed with {len(result['errors'])} error(s). Please review details below.")
            else:
                messages.success(request, f"Successfully processed account groups! Added: {result['created']}, Updated: {result['updated']}, Skipped: {result['skipped']}.")
    return TemplateResponse(request, "admin/masters/import_excel.html", ctx)


SALE_COLUMN_GUIDE = [
    {"name": "Date *", "type": "Date", "required": True, "description": "Voucher date (e.g. '2026-09-01' or DD-MM-YYYY)."},
    {"name": "Invoice No *", "type": "Text", "required": True, "description": "Invoice number (e.g. 'INV-001'). Multiple rows with the same invoice no become a multi-item voucher."},
    {"name": "Party (Customer) *", "type": "Text", "required": True, "description": "Customer Account Name. Must already exist in database."},
    {"name": "Sale Type", "type": "Text", "required": False, "description": "Sale Type name (e.g. 'Local Sale'). If left blank, uses selected default on upload."},
    {"name": "Item Name *", "type": "Text", "required": True, "description": "Stock item name. Must already exist in database."},
    {"name": "Unit", "type": "Text", "required": False, "description": "Unit name (e.g. PCS). If blank, uses item's main unit."},
    {"name": "Quantity *", "type": "Number", "required": True, "description": "Billed quantity (must be > 0)."},
    {"name": "Rate", "type": "Number", "required": False, "description": "Item rate. If blank, defaults to item master Sale Price. Enter 0 to import a zero rate."},
    {"name": "Discount", "type": "Number", "required": False, "description": "Discount amount for this line (default 0)."},
    {"name": "Tax Rate %", "type": "Number", "required": False, "description": "Tax percentage. If blank, defaults to item master tax rate."},
    {"name": "Bill Sundry 1", "type": "Text", "required": False, "description": "Overall bill sundry 1 (e.g. 'Freight & Forwarding Charges'). Must exist in database."},
    {"name": "Sundry Amount 1", "type": "Number", "required": False, "description": "Amount for sundry 1, or 0 for auto-formula."},
    {"name": "Bill Sundry 2", "type": "Text", "required": False, "description": "Overall bill sundry 2 (e.g. 'Rounded Off', 'Packaging Charges')."},
    {"name": "Sundry Amount 2", "type": "Number", "required": False, "description": "Amount for sundry 2, or 0 for auto-formula."},
    {"name": "Bill Sundry 3", "type": "Text", "required": False, "description": "Overall bill sundry 3 (optional)."},
    {"name": "Sundry Amount 3", "type": "Number", "required": False, "description": "Amount for sundry 3, or 0 for auto-formula."},
    {"name": "Narration", "type": "Text", "required": False, "description": "Remarks or notes on the invoice."},
]

PURCHASE_COLUMN_GUIDE = [
    {"name": "Date *", "type": "Date", "required": True, "description": "Voucher date (e.g. '2026-09-01' or DD-MM-YYYY)."},
    {"name": "Invoice No *", "type": "Text", "required": True, "description": "Purchase bill/invoice number (e.g. 'PUR-501'). Multiple rows with the same invoice no become a multi-item voucher."},
    {"name": "Party (Supplier) *", "type": "Text", "required": True, "description": "Supplier Account Name. Must already exist in database."},
    {"name": "Purchase Type", "type": "Text", "required": False, "description": "Purchase Type name (e.g. 'Local Purchase'). If left blank, uses selected default on upload."},
    {"name": "Item Name *", "type": "Text", "required": True, "description": "Stock item name. Must already exist in database."},
    {"name": "Unit", "type": "Text", "required": False, "description": "Unit name (e.g. PCS). If blank, uses item's main unit."},
    {"name": "Quantity *", "type": "Number", "required": True, "description": "Billed quantity (must be > 0)."},
    {"name": "Rate", "type": "Number", "required": False, "description": "Item rate. If blank, defaults to item master Purchase Price. Enter 0 to import a zero rate."},
    {"name": "Discount", "type": "Number", "required": False, "description": "Discount amount for this line (default 0)."},
    {"name": "Tax Rate %", "type": "Number", "required": False, "description": "Tax percentage. If blank, defaults to item master tax rate."},
    {"name": "Bill Sundry 1", "type": "Text", "required": False, "description": "Overall bill sundry 1 (e.g. 'Freight & Forwarding Charges'). Must exist in database."},
    {"name": "Sundry Amount 1", "type": "Number", "required": False, "description": "Amount for sundry 1, or 0 for auto-formula."},
    {"name": "Bill Sundry 2", "type": "Text", "required": False, "description": "Overall bill sundry 2 (e.g. 'Rounded Off', 'Insurance Charges')."},
    {"name": "Sundry Amount 2", "type": "Number", "required": False, "description": "Amount for sundry 2, or 0 for auto-formula."},
    {"name": "Bill Sundry 3", "type": "Text", "required": False, "description": "Overall bill sundry 3 (optional)."},
    {"name": "Sundry Amount 3", "type": "Number", "required": False, "description": "Amount for sundry 3, or 0 for auto-formula."},
    {"name": "Narration", "type": "Text", "required": False, "description": "Remarks or notes on the invoice."},
]

ACCOUNT_GROUP_COLUMN_GUIDE = [
    {"name": "Group Name *", "type": "Text", "required": True, "description": "Unique account group name, e.g. 'Bank Accounts'."},
    {"name": "Primary (Y/N) *", "type": "Y / N", "required": True, "description": "Enter Y for a top-level Primary group, or N for a Secondary group under another group."},
    {"name": "Parent Group", "type": "Text", "required": False, "description": "Required for a Secondary group. It may be an existing group or another group in this file."},
    {"name": "Nature", "type": "Asset / Liability / Income / Expense / Equity", "required": False, "description": "Required for Primary groups. Secondary groups inherit the Nature of their Parent Group."},
]

CASH_VOUCHER_COLUMN_GUIDE = [
    {"name": "Date *", "type": "Date", "required": True, "description": "Voucher date. Enter it on the first row for each voucher."},
    {"name": "Voucher No *", "type": "Text", "required": True, "description": "Voucher number. Repeat it on every party line that belongs to this voucher."},
    {"name": "Through (Cash/Bank) *", "type": "Text", "required": True, "description": "Cash or bank account. Enter it on the first row; it must belong to Cash-in-hand or Bank Accounts."},
    {"name": "Party / Expense *", "type": "Text", "required": True, "description": "Payment party or expense account. Required on every line."},
    {"name": "Amount *", "type": "Number", "required": True, "description": "Positive amount for this party line."},
    {"name": "Narration", "type": "Text", "required": False, "description": "Voucher narration; enter it on the first row."},
]

RECEIPT_COLUMN_GUIDE = [
    {**column, "name": "Party / Income *", "description": "Receipt party or income account. Required on every line."}
    if column["name"] == "Party / Expense *" else column
    for column in CASH_VOUCHER_COLUMN_GUIDE
]

JOURNAL_COLUMN_GUIDE = [
    {"name": "Date *", "type": "Date", "required": True, "description": "Voucher date. Enter it on the first row for each voucher."},
    {"name": "Voucher No *", "type": "Text", "required": True, "description": "Voucher number. Repeat it on every journal line."},
    {"name": "Account *", "type": "Text", "required": True, "description": "Ledger account name. Required on every line."},
    {"name": "Debit", "type": "Number", "required": True, "description": "Positive debit amount. Enter either Debit or Credit, never both."},
    {"name": "Credit", "type": "Number", "required": True, "description": "Positive credit amount. Enter either Credit or Debit, never both."},
    {"name": "Remarks", "type": "Text", "required": False, "description": "Optional note for this individual line."},
    {"name": "Narration", "type": "Text", "required": False, "description": "Voucher narration; enter it on the first row."},
]


def sale_template_view(request):
    if not OPENPYXL_AVAILABLE:
        messages.error(request, "openpyxl is not installed. Please install it using: pip install openpyxl")
        return HttpResponseRedirect(reverse("admin:erp_sale_import"))
    buffer = generate_sale_template()
    return excel_download_response(buffer, "Sale_Voucher_Import_Template.xlsx")


def sale_import_view(request):
    sale_types = SaleType.objects.all().order_by("name")
    ctx = {
        **admin.site.each_context(request),
        "title": "Import Sale Vouchers from Excel",
        "model_name": "Sale Voucher",
        "model_name_plural": "Sales",
        "type_label": "Default Sale Type",
        "type_choices": sale_types,
        "changelist_url": reverse("admin:masters_sale_changelist"),
        "template_url": reverse("admin:erp_sale_template"),
        "column_guide": SALE_COLUMN_GUIDE,
        "package_missing": not OPENPYXL_AVAILABLE,
        "show_type_selector": True,
        "result": None,
    }
    if request.method == "POST":
        if not OPENPYXL_AVAILABLE:
            messages.error(request, "openpyxl is not installed. Please install it using: pip install openpyxl")
            return TemplateResponse(request, "admin/masters/import_voucher_excel.html", ctx)
        excel_file = request.FILES.get("excel_file")
        if not excel_file:
            messages.error(request, "Please choose an Excel file to upload.")
            return TemplateResponse(request, "admin/masters/import_voucher_excel.html", ctx)
        default_type_id = request.POST.get("default_type_id") or None
        update_existing = request.POST.get("update_existing") == "1"
        result = import_sales_from_excel(
            excel_file,
            default_sale_type_id=default_type_id,
            update_existing=update_existing,
        )
        ctx["result"] = result
        if result["errors"]:
            messages.warning(
                request,
                f"Import completed with {len(result['errors'])} error(s). Please review details below."
            )
        else:
            messages.success(
                request,
                f"Successfully processed sales vouchers! Created: {result['vouchers_created']}, Updated: {result['vouchers_updated']}, Skipped: {result['vouchers_skipped']} ({result['items_count']} item lines)."
            )
    return TemplateResponse(request, "admin/masters/import_voucher_excel.html", ctx)


def purchase_template_view(request):
    if not OPENPYXL_AVAILABLE:
        messages.error(request, "openpyxl is not installed. Please install it using: pip install openpyxl")
        return HttpResponseRedirect(reverse("admin:erp_purchase_import"))
    buffer = generate_purchase_template()
    return excel_download_response(buffer, "Purchase_Voucher_Import_Template.xlsx")


def purchase_import_view(request):
    purchase_types = PurchaseType.objects.all().order_by("name")
    ctx = {
        **admin.site.each_context(request),
        "title": "Import Purchase Vouchers from Excel",
        "model_name": "Purchase Voucher",
        "model_name_plural": "Purchases",
        "type_label": "Default Purchase Type",
        "type_choices": purchase_types,
        "changelist_url": reverse("admin:masters_purchase_changelist"),
        "template_url": reverse("admin:erp_purchase_template"),
        "column_guide": PURCHASE_COLUMN_GUIDE,
        "package_missing": not OPENPYXL_AVAILABLE,
        "show_type_selector": True,
        "result": None,
    }
    if request.method == "POST":
        if not OPENPYXL_AVAILABLE:
            messages.error(request, "openpyxl is not installed. Please install it using: pip install openpyxl")
            return TemplateResponse(request, "admin/masters/import_voucher_excel.html", ctx)
        excel_file = request.FILES.get("excel_file")
        if not excel_file:
            messages.error(request, "Please choose an Excel file to upload.")
            return TemplateResponse(request, "admin/masters/import_voucher_excel.html", ctx)
        default_type_id = request.POST.get("default_type_id") or None
        update_existing = request.POST.get("update_existing") == "1"
        result = import_purchases_from_excel(
            excel_file,
            default_purchase_type_id=default_type_id,
            update_existing=update_existing,
        )
        ctx["result"] = result
        if result["errors"]:
            messages.warning(
                request,
                f"Import completed with {len(result['errors'])} error(s). Please review details below."
            )
        else:
            messages.success(
                request,
                f"Successfully processed purchase vouchers! Created: {result['vouchers_created']}, Updated: {result['vouchers_updated']}, Skipped: {result['vouchers_skipped']} ({result['items_count']} item lines)."
            )
    return TemplateResponse(request, "admin/masters/import_voucher_excel.html", ctx)


def _cash_import_view(request, *, title, model_name, model_plural, changelist_url, template_url, column_guide, import_func):
    ctx = {
        **admin.site.each_context(request),
        "title": title,
        "model_name": model_name,
        "model_name_plural": model_plural,
        "changelist_url": changelist_url,
        "template_url": template_url,
        "column_guide": column_guide,
        "package_missing": not OPENPYXL_AVAILABLE,
        "show_type_selector": False,
        "result": None,
    }
    if request.method == "POST":
        if not OPENPYXL_AVAILABLE:
            messages.error(request, "openpyxl is not installed. Please install it using: pip install openpyxl")
        elif not (excel_file := request.FILES.get("excel_file")):
            messages.error(request, "Please choose an Excel file to upload.")
        else:
            result = import_func(excel_file, update_existing=request.POST.get("update_existing") == "1")
            ctx["result"] = result
            if result["errors"]:
                messages.warning(request, f"Import completed with {len(result['errors'])} error(s). Please review details below.")
            else:
                messages.success(request, f"Successfully processed {model_plural.lower()}! Created: {result['vouchers_created']}, Updated: {result['vouchers_updated']}, Skipped: {result['vouchers_skipped']} ({result['items_count']} lines).")
    return TemplateResponse(request, "admin/masters/import_voucher_excel.html", ctx)


def payment_template_view(request):
    return excel_download_response(generate_payment_template(), "Payment_Voucher_Import_Template.xlsx")


def payment_import_view(request):
    return _cash_import_view(request, title="Import Payment Vouchers from Excel", model_name="Payment Voucher", model_plural="Payments", changelist_url=reverse("admin:masters_payment_changelist"), template_url=reverse("admin:erp_payment_template"), column_guide=CASH_VOUCHER_COLUMN_GUIDE, import_func=import_payments_from_excel)


def receipt_template_view(request):
    return excel_download_response(generate_receipt_template(), "Receipt_Voucher_Import_Template.xlsx")


def receipt_import_view(request):
    return _cash_import_view(request, title="Import Receipt Vouchers from Excel", model_name="Receipt Voucher", model_plural="Receipts", changelist_url=reverse("admin:masters_receipt_changelist"), template_url=reverse("admin:erp_receipt_template"), column_guide=RECEIPT_COLUMN_GUIDE, import_func=import_receipts_from_excel)


def journal_template_view(request):
    return excel_download_response(generate_journal_template(), "Journal_Voucher_Import_Template.xlsx")


def journal_import_view(request):
    return _cash_import_view(request, title="Import Journal Vouchers from Excel", model_name="Journal Voucher", model_plural="Journal Vouchers", changelist_url=reverse("admin:masters_journal_changelist"), template_url=reverse("admin:erp_journal_template"), column_guide=JOURNAL_COLUMN_GUIDE, import_func=import_journals_from_excel)


if not getattr(admin.site, "_erp_urls_patched", False):
    _original_get_urls = admin.site.get_urls

    def _get_urls():
        return [
            path(
                "reports/profit-loss/",
                admin.site.admin_view(profit_loss_view),
                name="erp_profit_loss",
            ),
            path(
                "reports/balance-sheet/",
                admin.site.admin_view(balance_sheet_view),
                name="erp_balance_sheet",
            ),
            path(
                "reports/trial-balance/",
                admin.site.admin_view(trial_balance_view),
                name="erp_trial_balance",
            ),
            path(
                "reports/sales-register/",
                admin.site.admin_view(sales_register_view),
                name="erp_sales_register",
            ),
            path(
                "reports/purchase-register/",
                admin.site.admin_view(purchase_register_view),
                name="erp_purchase_register",
            ),
            path(
                "reports/payment-register/",
                admin.site.admin_view(payment_register_view),
                name="erp_payment_register",
            ),
            path(
                "reports/receipt-register/",
                admin.site.admin_view(receipt_register_view),
                name="erp_receipt_register",
            ),
            path(
                "reports/journal-register/",
                admin.site.admin_view(journal_register_view),
                name="erp_journal_register",
            ),
            path(
                "reports/stock-summary/",
                admin.site.admin_view(stock_summary_view),
                name="erp_stock_summary",
            ),
            path(
                "reports/ledger/",
                admin.site.admin_view(ledger_view),
                name="erp_ledger_index",
            ),
            path(
                "reports/ledger/<int:account_id>/",
                admin.site.admin_view(ledger_view),
                name="erp_ledger",
            ),
            path(
                "masters/item-detail/<int:item_id>/",
                admin.site.admin_view(item_detail_view),
                name="erp_item_detail",
            ),
            path(
                "masters/item/template/",
                admin.site.admin_view(item_template_view),
                name="erp_item_template",
            ),
            path(
                "masters/item/import/",
                admin.site.admin_view(item_import_view),
                name="erp_item_import",
            ),
            path(
                "masters/account/template/",
                admin.site.admin_view(account_template_view),
                name="erp_account_template",
            ),
            path(
                "masters/account/import/",
                admin.site.admin_view(account_import_view),
                name="erp_account_import",
            ),
            path(
                "masters/account-group/template/",
                admin.site.admin_view(account_group_template_view),
                name="erp_account_group_template",
            ),
            path(
                "masters/account-group/import/",
                admin.site.admin_view(account_group_import_view),
                name="erp_account_group_import",
            ),
            path(
                "masters/sale/template/",
                admin.site.admin_view(sale_template_view),
                name="erp_sale_template",
            ),
            path(
                "masters/sale/import/",
                admin.site.admin_view(sale_import_view),
                name="erp_sale_import",
            ),
            path(
                "masters/purchase/template/",
                admin.site.admin_view(purchase_template_view),
                name="erp_purchase_template",
            ),
            path(
                "masters/purchase/import/",
                admin.site.admin_view(purchase_import_view),
                name="erp_purchase_import",
            ),
            path("masters/payment/template/", admin.site.admin_view(payment_template_view), name="erp_payment_template"),
            path("masters/payment/import/", admin.site.admin_view(payment_import_view), name="erp_payment_import"),
            path("masters/receipt/template/", admin.site.admin_view(receipt_template_view), name="erp_receipt_template"),
            path("masters/receipt/import/", admin.site.admin_view(receipt_import_view), name="erp_receipt_import"),
            path("masters/journal/template/", admin.site.admin_view(journal_template_view), name="erp_journal_template"),
            path("masters/journal/import/", admin.site.admin_view(journal_import_view), name="erp_journal_import"),
        ] + _original_get_urls()

    admin.site.get_urls = _get_urls
    admin.site._erp_urls_patched = True


# =========================================================
# INLINES
# =========================================================

class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 1
    autocomplete_fields = ("item", "unit")
    readonly_fields = ("basic_amount", "amount_after_discount", "tax_amount", "net_amount")
    fields = (
        "item",
        "unit",
        "quantity",
        "rate",
        "discount",
        "tax",
        "basic_amount",
        "amount_after_discount",
        "tax_amount",
        "net_amount",
    )


class SaleBillSundryInline(admin.TabularInline):
    model = SaleBillSundry
    extra = 1
    autocomplete_fields = ("bill_sundry",)


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 1
    autocomplete_fields = ("item", "unit")
    readonly_fields = ("basic_amount", "amount_after_discount", "tax_amount", "net_amount")
    fields = (
        "item",
        "unit",
        "quantity",
        "rate",
        "discount",
        "tax",
        "basic_amount",
        "amount_after_discount",
        "tax_amount",
        "net_amount",
    )


class PurchaseBillSundryInline(admin.TabularInline):
    model = PurchaseBillSundry
    extra = 1
    autocomplete_fields = ("bill_sundry",)


class JournalLineForm(forms.ModelForm):
    class Meta:
        model = JournalLine
        fields = ("account", "debit", "credit", "remarks")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].required = False
        self.fields["debit"].required = False
        self.fields["credit"].required = False

    def has_changed(self):
        if not self.is_bound:
            return False
        if self.instance and self.instance.pk:
            return super().has_changed()
        account = (self.data.get(self.add_prefix("account")) or "").strip()
        remarks = (self.data.get(self.add_prefix("remarks")) or "").strip()
        raw_dr = self.data.get(self.add_prefix("debit")) or 0
        raw_cr = self.data.get(self.add_prefix("credit")) or 0
        try:
            debit = money(raw_dr)
        except Exception:
            return True
        try:
            credit = money(raw_cr)
        except Exception:
            return True
        if not account and not remarks and debit == 0 and credit == 0:
            return False
        return super().has_changed()


class JournalLineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        total_dr = ZERO
        total_cr = ZERO
        filled = 0
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            account = form.cleaned_data.get("account")
            debit = money(form.cleaned_data.get("debit"))
            credit = money(form.cleaned_data.get("credit"))
            if not account and debit == 0 and credit == 0:
                continue
            if not account:
                raise ValidationError("Each journal line needs an account.")
            if debit < 0 or credit < 0:
                raise ValidationError("Debit and credit amounts cannot be negative.")
            if debit and credit:
                raise ValidationError(
                    "A line cannot have both debit and credit. Voucher was not saved."
                )
            if debit == 0 and credit == 0:
                raise ValidationError("Enter debit or credit on each used line.")
            filled += 1
            total_dr += debit
            total_cr += credit
        if filled < 2:
            raise ValidationError("Enter at least two journal lines.")
        if total_dr == 0:
            raise ValidationError("Journal amount cannot be zero.")
        if total_dr != total_cr:
            raise ValidationError(
                f"Debit ({total_dr}) and Credit ({total_cr}) must be equal. "
                "Voucher was not saved."
            )


class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 8
    form = JournalLineForm
    formset = JournalLineFormSet
    autocomplete_fields = ("account",)
    fields = ("account", "debit", "credit", "remarks")


class CashVoucherLineFormSet(BaseInlineFormSet):
    """Require at least one positive party amount on a cash voucher."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        filled = 0
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            account = form.cleaned_data.get("account")
            amount = money(form.cleaned_data.get("amount"))
            if not account and amount == 0:
                continue
            if not account:
                raise ValidationError("Each payment or receipt line needs an account.")
            if amount <= 0:
                raise ValidationError("Each payment or receipt amount must be greater than zero.")
            filled += 1
        if not filled:
            raise ValidationError("Enter at least one payment or receipt line.")


class PaymentLineInline(admin.TabularInline):
    model = PaymentLine
    extra = 3
    min_num = 1
    formset = CashVoucherLineFormSet
    autocomplete_fields = ("account",)
    fields = ("account", "amount")


class ReceiptLineInline(admin.TabularInline):
    model = ReceiptLine
    extra = 3
    min_num = 1
    formset = CashVoucherLineFormSet
    autocomplete_fields = ("account",)
    fields = ("account", "amount")


@admin.register(AccountGroup)
class AccountGroupAdmin(admin.ModelAdmin):
    change_list_template = "admin/masters/accountgroup/change_list.html"
    list_display = ("name", "primary_group", "under_group", "nature")
    search_fields = ("name",)
    list_filter = ("primary_group", "nature")
    autocomplete_fields = ("under_group",)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    change_list_template = "admin/masters/account/change_list.html"
    list_display = (
        "account_name",
        "account_group",
        "opening",
        "opening_type",
        "mobile_no",
        "gst",
        "is_registered",
        "ledger_link",
    )
    search_fields = ("account_name", "mobile_no", "gst")
    list_filter = ("account_group", "opening_type", "state", "is_registered")
    list_editable = ("is_registered",)
    autocomplete_fields = ("account_group",)

    @admin.display(description="Ledger")
    def ledger_link(self, obj):
        url = reverse("admin:erp_ledger", args=[obj.pk])
        return format_html('<a href="{}">View</a>', url)


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "print_name", "decimal_places")
    search_fields = ("name", "print_name")


@admin.register(SaleType)
class SaleTypeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "sales_account",
        "tax_account",
        "tax_account_2",
        "tax_split_percent",
        "affect_stock",
        "tax_inclusive",
    )
    search_fields = ("name",)
    autocomplete_fields = ("sales_account", "tax_account", "tax_account_2")
    fieldsets = (
        (None, {"fields": ("name", "sales_account", "affect_stock", "tax_inclusive")}),
        (
            "Tax posting",
            {
                "fields": ("tax_account", "tax_account_2", "tax_split_percent"),
                "description": (
                    "Local: Tax Account = CGST, Tax Account 2 = SGST, split 50/50. "
                    "Interstate: Tax Account = IGST and leave Tax Account 2 blank."
                ),
            },
        ),
    )


@admin.register(PurchaseType)
class PurchaseTypeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "purchase_account",
        "tax_account",
        "tax_account_2",
        "tax_split_percent",
        "affect_stock",
        "tax_inclusive",
    )
    search_fields = ("name",)
    autocomplete_fields = ("purchase_account", "tax_account", "tax_account_2")
    fieldsets = (
        (None, {"fields": ("name", "purchase_account", "affect_stock", "tax_inclusive")}),
        (
            "Tax posting",
            {
                "fields": ("tax_account", "tax_account_2", "tax_split_percent"),
                "description": (
                    "Local: Tax Account = CGST, Tax Account 2 = SGST, split 50/50. "
                    "Interstate: Tax Account = IGST and leave Tax Account 2 blank."
                ),
            },
        ),
    )


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    change_list_template = "admin/masters/item/change_list.html"
    list_display = (
        "item_name",
        "item_group",
        "hsn",
        "main_unit",
        "alt_unit",
        "tax",
        "sale_price",
        "purchase_price",
        "mrp",
        "opening_main",
        "opening_value",
    )
    search_fields = ("item_name", "item_group", "hsn")
    list_filter = ("item_group", "main_unit")
    autocomplete_fields = ("main_unit", "alt_unit")


@admin.register(BillSundry)
class BillSundryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "type",
        "amount_of",
        "default_value",
        "apply_on",
        "posting_account_sale",
        "posting_account_purchase",
    )
    search_fields = ("name",)
    list_filter = ("type", "amount_of", "apply_on")
    autocomplete_fields = ("posting_account_sale", "posting_account_purchase")
    fieldsets = (
        (
            None,
            {
                "fields": ("name", "type"),
            },
        ),
        (
            "Posting Accounts",
            {
                "fields": ("posting_account_sale", "posting_account_purchase"),
                "description": (
                    "Select the ledger to post when this sundry is used on a "
                    "Sale voucher and on a Purchase voucher respectively."
                ),
            },
        ),
        (
            "How it is applied",
            {
                "fields": ("amount_of", "default_value", "apply_on"),
                "description": (
                    "Percentage is calculated on the selected base: "
                    "item basic (qty \u00d7 rate), item amount after discount, "
                    "tax, item net, running bill amount, or previous sundry."
                ),
            },
        ),
    )


class VoucherAdminMixin:
    readonly_fields = (
        "item_basic_amount",
        "item_discount_amount",
        "item_amount",
        "tax_amount",
        "sundry_amount",
        "net_amount",
    )

    def item_basic_amount(self, obj):
        return obj.totals()["item_basic_amount"] if obj.pk else 0

    def item_discount_amount(self, obj):
        return obj.totals()["item_discount_amount"] if obj.pk else 0

    def item_amount(self, obj):
        return obj.totals()["item_amount"] if obj.pk else 0

    def tax_amount(self, obj):
        return obj.totals()["tax_amount"] if obj.pk else 0

    def sundry_amount(self, obj):
        return obj.totals()["sundry_amount"] if obj.pk else 0

    def net_amount(self, obj):
        return obj.totals()["net_amount"] if obj.pk else 0

    item_basic_amount.short_description = "Item basic"
    item_discount_amount.short_description = "Item discount"
    item_amount.short_description = "Item amount"
    tax_amount.short_description = "Tax"
    sundry_amount.short_description = "Bill sundry"
    net_amount.short_description = "Net amount"


@admin.register(Sale)
class SaleAdmin(VoucherAdminMixin, admin.ModelAdmin):
    change_list_template = "admin/masters/sale/change_list.html"
    list_display = ("invoice_no", "date", "sale_type", "account", "net_amount_list")
    search_fields = ("invoice_no", "account__account_name")
    list_filter = ("date", "sale_type")
    autocomplete_fields = ("account", "sale_type")
    inlines = [SaleItemInline, SaleBillSundryInline]
    fieldsets = (
        (None, {"fields": ("date", "invoice_no", "sale_type", "account", "narration")}),
        (
            "Totals",
            {
                "fields": (
                    "item_basic_amount",
                    "item_discount_amount",
                    "item_amount",
                    "tax_amount",
                    "sundry_amount",
                    "net_amount",
                )
            },
        ),
    )

    class Media:
        js = ("masters/js/voucher_helper.js",)

    @admin.display(description="Net")
    def net_amount_list(self, obj):
        return obj.net_amount


@admin.register(Purchase)
class PurchaseAdmin(VoucherAdminMixin, admin.ModelAdmin):
    change_list_template = "admin/masters/purchase/change_list.html"
    list_display = ("invoice_no", "date", "purchase_type", "account", "net_amount_list")
    search_fields = ("invoice_no", "account__account_name")
    list_filter = ("date", "purchase_type")
    autocomplete_fields = ("account", "purchase_type")
    inlines = [PurchaseItemInline, PurchaseBillSundryInline]
    fieldsets = (
        (
            None,
            {"fields": ("date", "invoice_no", "purchase_type", "account", "narration")},
        ),
        (
            "Totals",
            {
                "fields": (
                    "item_basic_amount",
                    "item_discount_amount",
                    "item_amount",
                    "tax_amount",
                    "sundry_amount",
                    "net_amount",
                )
            },
        ),
    )

    class Media:
        js = ("masters/js/voucher_helper.js",)

    @admin.display(description="Net")
    def net_amount_list(self, obj):
        return obj.net_amount


CASH_BANK_GROUPS = ("Cash-in-hand", "Bank Accounts")


class CashVoucherAdmin(admin.ModelAdmin):
    list_display = ("voucher_no", "date", "parties", "through", "total_amount_list")
    search_fields = ("voucher_no", "lines__account__account_name", "narration")
    list_filter = ("date",)
    autocomplete_fields = ("through",)
    readonly_fields = ("total_amount",)
    fieldsets = (
        (None, {"fields": ("date", "voucher_no", "through", "narration", "total_amount")}),
    )

    @admin.display(description="Parties")
    def parties(self, obj):
        return obj.parties_summary()

    @admin.display(description="Total")
    def total_amount_list(self, obj):
        return obj.total_amount

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "through":
            kwargs["queryset"] = Account.objects.filter(
                account_group__name__in=CASH_BANK_GROUPS
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Payment)
class PaymentAdmin(CashVoucherAdmin):
    change_list_template = "admin/masters/payment/change_list.html"
    inlines = [PaymentLineInline]


@admin.register(Receipt)
class ReceiptAdmin(CashVoucherAdmin):
    change_list_template = "admin/masters/receipt/change_list.html"
    inlines = [ReceiptLineInline]


@admin.register(Journal)
class JournalAdmin(admin.ModelAdmin):
    change_list_template = "admin/masters/journal/change_list.html"
    list_display = (
        "voucher_no",
        "date",
        "total_debit_list",
        "lines_summary_display",
        "narration",
    )
    search_fields = ("voucher_no", "narration", "lines__account__account_name")
    list_filter = ("date",)
    inlines = [JournalLineInline]
    readonly_fields = ("total_debit", "total_credit", "difference")
    fieldsets = (
        (None, {"fields": ("date", "voucher_no", "narration")}),
        (
            "Totals",
            {
                "fields": ("total_debit", "total_credit", "difference"),
                "description": "Debit and credit must be equal or the voucher will not save.",
            },
        ),
    )

    class Media:
        js = ("masters/js/journal_helper.js",)

    def _totals(self, obj):
        if not obj or not obj.pk:
            return {"debit": ZERO, "credit": ZERO, "difference": ZERO}
        return obj.totals()

    @admin.display(description="Debit")
    def total_debit(self, obj):
        return self._totals(obj)["debit"]

    @admin.display(description="Credit")
    def total_credit(self, obj):
        return self._totals(obj)["credit"]

    @admin.display(description="Difference")
    def difference(self, obj):
        return self._totals(obj)["difference"]

    @admin.display(description="Amount")
    def total_debit_list(self, obj):
        return f"{obj.totals()['debit']:,.2f}"

    @admin.display(description="Particulars")
    def lines_summary_display(self, obj):
        return obj.lines_summary()
