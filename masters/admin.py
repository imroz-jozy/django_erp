from django.contrib import admin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .models import (
    Account,
    AccountGroup,
    BillSundry,
    Item,
    Payment,
    Purchase,
    PurchaseBillSundry,
    PurchaseItem,
    PurchaseType,
    Receipt,
    Sale,
    SaleBillSundry,
    SaleItem,
    SaleType,
    Unit,
)
from .reports import (
    account_ledger,
    balance_sheet,
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


@admin.register(AccountGroup)
class AccountGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "primary_group", "under_group", "nature")
    search_fields = ("name",)
    list_filter = ("primary_group", "nature")
    autocomplete_fields = ("under_group",)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = (
        "account_name",
        "account_group",
        "opening",
        "opening_type",
        "mobile_no",
        "gst",
        "ledger_link",
    )
    search_fields = ("account_name", "mobile_no", "gst")
    list_filter = ("account_group", "opening_type", "state")
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
    list_display = ("name", "sales_account", "tax_account", "affect_stock", "tax_inclusive")
    search_fields = ("name",)
    autocomplete_fields = ("sales_account", "tax_account")


@admin.register(PurchaseType)
class PurchaseTypeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "purchase_account",
        "tax_account",
        "affect_stock",
        "tax_inclusive",
    )
    search_fields = ("name",)
    autocomplete_fields = ("purchase_account", "tax_account")


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = (
        "item_name",
        "item_group",
        "main_unit",
        "alt_unit",
        "tax",
        "sale_price",
        "purchase_price",
        "mrp",
        "opening_main",
        "opening_value",
    )
    search_fields = ("item_name", "item_group")
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
    list_display = ("voucher_no", "date", "account", "through", "amount")
    search_fields = ("voucher_no", "account__account_name", "narration")
    list_filter = ("date",)
    autocomplete_fields = ("account", "through")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "through":
            kwargs["queryset"] = Account.objects.filter(
                account_group__name__in=CASH_BANK_GROUPS
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Payment)
class PaymentAdmin(CashVoucherAdmin):
    pass


@admin.register(Receipt)
class ReceiptAdmin(CashVoucherAdmin):
    pass
