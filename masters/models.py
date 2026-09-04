from decimal import Decimal

from django.core.validators import RegexValidator
from django.db import models
from django.db.models.signals import post_migrate
from django.dispatch import receiver

from .money import ZERO, money

HSN_VALIDATOR = RegexValidator(r"^\d*$", "HSN must contain digits only.")


# =========================================================
# ACCOUNT GROUP
# =========================================================

class AccountGroup(models.Model):

    class Nature(models.TextChoices):
        ASSET = "ASSET", "Asset"
        LIABILITY = "LIABILITY", "Liability"
        INCOME = "INCOME", "Income"
        EXPENSE = "EXPENSE", "Expense"
        EQUITY = "EQUITY", "Equity"

    name = models.CharField(max_length=100, unique=True)
    primary_group = models.BooleanField(default=True)
    under_group = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sub_groups",
    )
    nature = models.CharField(
        max_length=12,
        choices=Nature.choices,
        default=Nature.ASSET,
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Account Group"
        verbose_name_plural = "Account Groups"

    def __str__(self):
        return self.name

    def is_balance_sheet(self):
        return self.nature in (
            self.Nature.ASSET,
            self.Nature.LIABILITY,
            self.Nature.EQUITY,
        )

    def is_profit_loss(self):
        return self.nature in (self.Nature.INCOME, self.Nature.EXPENSE)


# =========================================================
# ACCOUNT
# =========================================================

class Account(models.Model):

    class OpeningType(models.TextChoices):
        DR = "DR", "Debit"
        CR = "CR", "Credit"

    account_name = models.CharField(max_length=150, unique=True)
    account_group = models.ForeignKey(
        AccountGroup,
        on_delete=models.PROTECT,
        related_name="accounts",
    )
    opening = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    opening_type = models.CharField(
        max_length=2,
        choices=OpeningType.choices,
        default=OpeningType.DR,
    )
    address = models.TextField(blank=True)
    state = models.CharField(max_length=100, blank=True)
    gst = models.CharField(max_length=20, blank=True)
    is_registered = models.BooleanField(
        default=False,
        verbose_name="Registered",
        help_text="Tick if this party is GST registered.",
    )
    mobile_no = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["account_name"]
        verbose_name = "Account"
        verbose_name_plural = "Accounts"

    def __str__(self):
        return self.account_name

    def clean(self):
        super().clean()
        if self.account_name:
            qs = Account.objects.filter(account_name__iexact=self.account_name)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                from django.core.exceptions import ValidationError
                raise ValidationError({"account_name": "Account with this name already exists (case-insensitive)."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def opening_signed(self):
        value = money(self.opening)
        if self.opening_type == self.OpeningType.CR:
            return -value
        return value


# =========================================================
# UNIT
# =========================================================

class Unit(models.Model):

    name = models.CharField(max_length=50, unique=True)
    print_name = models.CharField(max_length=50, blank=True)
    decimal_places = models.PositiveSmallIntegerField(default=2)

    class Meta:
        ordering = ["name"]
        verbose_name = "Unit"
        verbose_name_plural = "Units"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.print_name:
            self.print_name = self.name
        super().save(*args, **kwargs)


# =========================================================
# SALE TYPE / PURCHASE TYPE
# =========================================================

def tax_split_postings(tax_type, tax_amount):
    """Split item tax across one or two ledgers.

    If tax_account_2 is set (local CGST+SGST), first_percent goes to
    tax_account and the remainder to tax_account_2. Interstate types leave
    tax_account_2 blank so 100% posts to tax_account (IGST).
    """
    tax_amount = money(tax_amount)
    if not tax_amount or tax_type is None:
        return []
    first = tax_type.tax_account
    second = getattr(tax_type, "tax_account_2", None)
    if first and second and first.id != second.id:
        pct = money(getattr(tax_type, "tax_split_percent", None) or Decimal("50"))
        first_amt = money(tax_amount * pct / Decimal("100"))
        second_amt = money(tax_amount - first_amt)
        parts = []
        if first_amt:
            parts.append((first, first_amt))
        if second_amt:
            parts.append((second, second_amt))
        return parts
    if first:
        return [(first, tax_amount)]
    if second:
        return [(second, tax_amount)]
    return []


class SaleType(models.Model):

    name = models.CharField(max_length=100, unique=True)
    sales_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="sale_types",
        help_text="Ledger credited for sales (usually under Sale).",
    )
    tax_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sale_type_tax",
        help_text="First tax ledger (CGST for local, IGST for interstate).",
    )
    tax_account_2 = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sale_type_tax_2",
        help_text="Second tax ledger for local tax (SGST). Leave blank for IGST.",
    )
    tax_split_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("50.00"),
        help_text="Percent of item tax posted to Tax Account. Rest goes to Tax Account 2.",
    )
    affect_stock = models.BooleanField(default=True)
    tax_inclusive = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        verbose_name = "Sale Type"
        verbose_name_plural = "Sale Types"

    def __str__(self):
        return self.name

    def tax_postings(self, tax_amount):
        return tax_split_postings(self, tax_amount)


class PurchaseType(models.Model):

    name = models.CharField(max_length=100, unique=True)
    purchase_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="purchase_types",
        help_text="Ledger debited for purchases (usually under Purchase).",
    )
    tax_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="purchase_type_tax",
        help_text="First tax ledger (CGST for local, IGST for interstate).",
    )
    tax_account_2 = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="purchase_type_tax_2",
        help_text="Second tax ledger for local tax (SGST). Leave blank for IGST.",
    )
    tax_split_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("50.00"),
        help_text="Percent of item tax posted to Tax Account. Rest goes to Tax Account 2.",
    )
    affect_stock = models.BooleanField(default=True)
    tax_inclusive = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        verbose_name = "Purchase Type"
        verbose_name_plural = "Purchase Types"

    def __str__(self):
        return self.name

    def tax_postings(self, tax_amount):
        return tax_split_postings(self, tax_amount)


# =========================================================
# ITEM
# =========================================================

class Item(models.Model):

    item_name = models.CharField(max_length=150, unique=True)
    item_group = models.CharField(max_length=100, blank=True)
    main_unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="items_main",
    )
    alt_unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="items_alt",
    )
    conversion = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        default=1,
        help_text="1 main unit = conversion alt units",
    )
    hsn = models.CharField(
        max_length=8,
        blank=True,
        validators=[HSN_VALIDATOR],
        help_text="HSN code, digits only (4, 6 or 8 digits).",
    )
    tax = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    sale_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    purchase_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    mrp = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    opening_main = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    opening_value = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        ordering = ["item_name"]
        verbose_name = "Item"
        verbose_name_plural = "Items"

    def __str__(self):
        return self.item_name

    def clean(self):
        super().clean()
        if self.item_name:
            qs = Item.objects.filter(item_name__iexact=self.item_name)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                from django.core.exceptions import ValidationError
                raise ValidationError({"item_name": "Item with this name already exists (case-insensitive)."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# =========================================================
# BILL SUNDRY
# =========================================================

class BillSundry(models.Model):

    class SundryType(models.TextChoices):
        ADDITIVE = "ADDITIVE", "Additive"
        SUBTRACTIVE = "SUBTRACTIVE", "Subtractive"

    class AmountOf(models.TextChoices):
        PERCENT = "PERCENT", "Percentage"
        ABSOLUTE = "ABSOLUTE", "Absolute amount"

    class ApplyOn(models.TextChoices):
        ITEM_BASIC = "ITEM_BASIC", "Item basic amount"
        ITEM_DISCOUNT = "ITEM_DISCOUNT", "Item discount amount"
        ITEM_AMOUNT = "ITEM_AMOUNT", "Item amount (after discount)"
        TAX_AMOUNT = "TAX_AMOUNT", "Tax amount"
        ITEM_NET = "ITEM_NET", "Item net amount"
        BILL_AMOUNT = "BILL_AMOUNT", "Bill amount (running total)"
        PREVIOUS_SUNDRY = "PREVIOUS_SUNDRY", "Previous bill sundry"

    name = models.CharField(max_length=100, unique=True)
    type = models.CharField(max_length=12, choices=SundryType.choices)
    amount_of = models.CharField(
        max_length=10,
        choices=AmountOf.choices,
        default=AmountOf.PERCENT,
    )
    default_value = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        default=0,
        help_text="Percentage or default amount, depending on Amount Of.",
    )
    apply_on = models.CharField(
        max_length=20,
        choices=ApplyOn.choices,
        default=ApplyOn.ITEM_BASIC,
    )
    posting_account_sale = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bill_sundries_sale",
        help_text="Ledger posted when this sundry appears on a Sale voucher.",
    )
    posting_account_purchase = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bill_sundries_purchase",
        help_text="Ledger posted when this sundry appears on a Purchase voucher.",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Bill Sundry"
        verbose_name_plural = "Bill Sundries"

    def __str__(self):
        return self.name


# =========================================================
# LINE AMOUNT MIXIN
# =========================================================

class ItemLineMixin(models.Model):

    quantity = models.DecimalField(max_digits=15, decimal_places=2)
    rate = models.DecimalField(max_digits=15, decimal_places=2)
    discount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        abstract = True

    @property
    def basic_amount(self):
        if self.quantity is None or self.rate is None:
            return ZERO
        return money(self.quantity * self.rate)

    @property
    def amount_after_discount(self):
        return money(self.basic_amount - money(self.discount or 0))

    @property
    def tax_amount(self):
        return money(self.amount_after_discount * money(self.tax or 0) / Decimal("100"))

    @property
    def net_amount(self):
        return money(self.amount_after_discount + self.tax_amount)


# =========================================================
# VOUCHER TOTALS
# =========================================================

def _item_totals(lines):
    basic = discount = taxable = tax_amt = ZERO
    for line in lines:
        basic += line.basic_amount
        discount += money(line.discount)
        taxable += line.amount_after_discount
        tax_amt += line.tax_amount
    return {
        "item_basic_amount": money(basic),
        "item_discount_amount": money(discount),
        "item_amount": money(taxable),
        "tax_amount": money(tax_amt),
        "item_net_amount": money(taxable + tax_amt),
    }


def compute_sundry_amount(sundry, entered_amount, bases, previous_sundry, running_bill):
    apply_map = {
        BillSundry.ApplyOn.ITEM_BASIC: bases["item_basic_amount"],
        BillSundry.ApplyOn.ITEM_DISCOUNT: bases["item_discount_amount"],
        BillSundry.ApplyOn.ITEM_AMOUNT: bases["item_amount"],
        BillSundry.ApplyOn.TAX_AMOUNT: bases["tax_amount"],
        BillSundry.ApplyOn.ITEM_NET: bases["item_net_amount"],
        BillSundry.ApplyOn.BILL_AMOUNT: running_bill,
        BillSundry.ApplyOn.PREVIOUS_SUNDRY: previous_sundry,
    }
    base = apply_map.get(sundry.apply_on, bases["item_basic_amount"])
    entered = money(entered_amount)

    if entered:
        amount = entered
    elif sundry.amount_of == BillSundry.AmountOf.ABSOLUTE:
        amount = money(sundry.default_value)
    else:
        amount = money(base * money(sundry.default_value) / Decimal("100"))

    if sundry.type == BillSundry.SundryType.SUBTRACTIVE:
        return money(-amount)
    return money(amount)


def voucher_totals(item_lines, sundry_lines):
    bases = _item_totals(item_lines)
    running = bases["item_net_amount"]
    previous = ZERO
    sundry_total = ZERO
    computed = []
    for line in sundry_lines:
        signed = compute_sundry_amount(
            line.bill_sundry,
            line.amount,
            bases,
            previous,
            running,
        )
        computed.append(signed)
        sundry_total += signed
        running = money(running + signed)
        previous = signed
    bases["sundry_amount"] = money(sundry_total)
    bases["net_amount"] = money(running)
    bases["sundry_signed_amounts"] = computed
    return bases


# =========================================================
# SALE
# =========================================================

class Sale(models.Model):

    date = models.DateField()
    invoice_no = models.CharField(max_length=50)
    sale_type = models.ForeignKey(
        SaleType,
        on_delete=models.PROTECT,
        related_name="sales",
        null=True,
        blank=True,
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="sales",
    )
    narration = models.TextField(blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "Sale"
        verbose_name_plural = "Sales"

    def __str__(self):
        return self.invoice_no

    def save(self, *args, **kwargs):
        if not self.sale_type_id:
            default_type = SaleType.objects.filter(name="Local Sale").first()
            if default_type:
                self.sale_type = default_type
        super().save(*args, **kwargs)

    def totals(self):
        return voucher_totals(list(self.items.all()), list(self.bill_sundries.all()))

    @property
    def item_basic_amount(self):
        return self.totals()["item_basic_amount"]

    @property
    def net_amount(self):
        return self.totals()["net_amount"]


class SaleItem(ItemLineMixin):

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="sale_items")
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sale_items",
    )

    class Meta:
        verbose_name = "Sale Item"
        verbose_name_plural = "Sale Items"

    def __str__(self):
        return f"{self.sale.invoice_no} - {self.item.item_name}"

    def save(self, *args, **kwargs):
        if self.item_id and self.tax == 0:
            self.tax = self.item.tax
        if self.item_id and not self.unit_id:
            self.unit = self.item.main_unit
        super().save(*args, **kwargs)


class SaleBillSundry(models.Model):

    sale = models.ForeignKey(
        Sale,
        on_delete=models.CASCADE,
        related_name="bill_sundries",
    )
    bill_sundry = models.ForeignKey(BillSundry, on_delete=models.PROTECT)
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text="Leave 0 to auto-calculate from bill sundry formula.",
    )

    class Meta:
        verbose_name = "Sale Bill Sundry"
        verbose_name_plural = "Sale Bill Sundries"

    def __str__(self):
        return f"{self.sale.invoice_no} - {self.bill_sundry.name}"


# =========================================================
# PURCHASE
# =========================================================

class Purchase(models.Model):

    date = models.DateField()
    invoice_no = models.CharField(max_length=50)
    purchase_type = models.ForeignKey(
        PurchaseType,
        on_delete=models.PROTECT,
        related_name="purchases",
        null=True,
        blank=True,
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="purchases",
    )
    narration = models.TextField(blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "Purchase"
        verbose_name_plural = "Purchases"

    def __str__(self):
        return self.invoice_no

    def save(self, *args, **kwargs):
        if not self.purchase_type_id:
            default_type = PurchaseType.objects.filter(name="Local Purchase").first()
            if default_type:
                self.purchase_type = default_type
        super().save(*args, **kwargs)

    def totals(self):
        return voucher_totals(list(self.items.all()), list(self.bill_sundries.all()))

    @property
    def item_basic_amount(self):
        return self.totals()["item_basic_amount"]

    @property
    def net_amount(self):
        return self.totals()["net_amount"]


class PurchaseItem(ItemLineMixin):

    purchase = models.ForeignKey(
        Purchase,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        related_name="purchase_items",
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="purchase_items",
    )

    class Meta:
        verbose_name = "Purchase Item"
        verbose_name_plural = "Purchase Items"

    def __str__(self):
        return f"{self.purchase.invoice_no} - {self.item.item_name}"

    def save(self, *args, **kwargs):
        if self.item_id and self.tax == 0:
            self.tax = self.item.tax
        if self.item_id and not self.unit_id:
            self.unit = self.item.main_unit
        super().save(*args, **kwargs)


class PurchaseBillSundry(models.Model):

    purchase = models.ForeignKey(
        Purchase,
        on_delete=models.CASCADE,
        related_name="bill_sundries",
    )
    bill_sundry = models.ForeignKey(BillSundry, on_delete=models.PROTECT)
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text="Leave 0 to auto-calculate from bill sundry formula.",
    )

    class Meta:
        verbose_name = "Purchase Bill Sundry"
        verbose_name_plural = "Purchase Bill Sundries"

    def __str__(self):
        return f"{self.purchase.invoice_no} - {self.bill_sundry.name}"


# =========================================================
# PAYMENT / RECEIPT (cash-bank vouchers for ledger)
# =========================================================

def _next_voucher_no(model, prefix):
    last = model.objects.order_by("-id").values_list("id", flat=True).first()
    n = (last or 0) + 1
    return f"{prefix}{n:04d}"


class Payment(models.Model):
    """Debit party/expense, credit cash/bank."""

    date = models.DateField()
    voucher_no = models.CharField(max_length=50, blank=True)
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="payments",
        help_text="Party or expense ledger (debited).",
    )
    through = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="payments_through",
        help_text="Cash or bank ledger (credited).",
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    narration = models.TextField(blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "Payment"
        verbose_name_plural = "Payments"

    def __str__(self):
        return self.voucher_no or f"Payment {self.pk}"

    def save(self, *args, **kwargs):
        if not self.voucher_no:
            self.voucher_no = _next_voucher_no(Payment, "PMT-")
        super().save(*args, **kwargs)


class Receipt(models.Model):
    """Debit cash/bank, credit party/income."""

    date = models.DateField()
    voucher_no = models.CharField(max_length=50, blank=True)
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="receipts",
        help_text="Party or income ledger (credited).",
    )
    through = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="receipts_through",
        help_text="Cash or bank ledger (debited).",
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    narration = models.TextField(blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "Receipt"
        verbose_name_plural = "Receipts"

    def __str__(self):
        return self.voucher_no or f"Receipt {self.pk}"

    def save(self, *args, **kwargs):
        if not self.voucher_no:
            self.voucher_no = _next_voucher_no(Receipt, "RCT-")
        super().save(*args, **kwargs)


# =========================================================
# JOURNAL
# =========================================================

class Journal(models.Model):
    """Multi-line debit/credit voucher. Totals must match before save."""

    date = models.DateField()
    voucher_no = models.CharField(max_length=50, blank=True)
    narration = models.TextField(blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "Journal Voucher"
        verbose_name_plural = "Journal Vouchers"

    def __str__(self):
        return self.voucher_no or f"Journal {self.pk}"

    def save(self, *args, **kwargs):
        if not self.voucher_no:
            self.voucher_no = _next_voucher_no(Journal, "JRN-")
        super().save(*args, **kwargs)

    def totals(self):
        debit = credit = ZERO
        for line in self.lines.all():
            debit += money(line.debit)
            credit += money(line.credit)
        return {
            "debit": money(debit),
            "credit": money(credit),
            "difference": money(debit - credit),
        }

    def lines_summary(self):
        parts = []
        for line in self.lines.all():
            if line.debit:
                parts.append(f"Dr {line.account.account_name} {line.debit:,.2f}")
            elif line.credit:
                parts.append(f"Cr {line.account.account_name} {line.credit:,.2f}")
        return " | ".join(parts)


class JournalLine(models.Model):

    journal = models.ForeignKey(
        Journal,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="journal_lines",
    )
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    remarks = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Journal Line"
        verbose_name_plural = "Journal Lines"

    def __str__(self):
        return f"{self.journal.voucher_no} - {self.account}"

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        debit = money(self.debit)
        credit = money(self.credit)
        if debit < 0 or credit < 0:
            raise ValidationError("Debit and credit amounts cannot be negative.")
        if debit and credit:
            raise ValidationError("A line cannot have both debit and credit.")
        if debit == 0 and credit == 0:
            raise ValidationError("Enter debit or credit amount.")


# =========================================================
# DEFAULT MASTERS (Busy / Tally style)
# =========================================================

DEFAULT_GROUPS = [
    # name, primary, under, nature
    ("Capital Account", True, None, AccountGroup.Nature.EQUITY),
    ("Current Assets", True, None, AccountGroup.Nature.ASSET),
    ("Current Liabilities", True, None, AccountGroup.Nature.LIABILITY),
    ("Fixed Assets", True, None, AccountGroup.Nature.ASSET),
    ("Investments", True, None, AccountGroup.Nature.ASSET),
    ("Loans (Liability)", True, None, AccountGroup.Nature.LIABILITY),
    ("Pre-Operative Expenses", True, None, AccountGroup.Nature.ASSET),
    ("Profit & Loss", True, None, AccountGroup.Nature.EQUITY),
    ("Revenue Accounts", True, None, AccountGroup.Nature.INCOME),
    ("Suspense Account", True, None, AccountGroup.Nature.ASSET),
    ("Bank Accounts", False, "Current Assets", AccountGroup.Nature.ASSET),
    ("Bank O/D Account", False, "Loans (Liability)", AccountGroup.Nature.LIABILITY),
    ("Cash-in-hand", False, "Current Assets", AccountGroup.Nature.ASSET),
    ("Duties & Taxes", False, "Current Liabilities", AccountGroup.Nature.LIABILITY),
    ("Expenses (Direct/Mfg.)", False, "Revenue Accounts", AccountGroup.Nature.EXPENSE),
    ("Expenses (Indirect/Admn.)", False, "Revenue Accounts", AccountGroup.Nature.EXPENSE),
    ("Income (Direct/Opr.)", False, "Revenue Accounts", AccountGroup.Nature.INCOME),
    ("Income (Indirect)", False, "Revenue Accounts", AccountGroup.Nature.INCOME),
    ("Loans & Advances (Asset)", False, "Current Assets", AccountGroup.Nature.ASSET),
    ("Provisions/Expenses Payable", False, "Current Liabilities", AccountGroup.Nature.LIABILITY),
    ("Purchase", False, "Revenue Accounts", AccountGroup.Nature.EXPENSE),
    ("Reserves & Surplus", False, "Capital Account", AccountGroup.Nature.EQUITY),
    ("Sale", False, "Revenue Accounts", AccountGroup.Nature.INCOME),
    ("Secured Loans", False, "Loans (Liability)", AccountGroup.Nature.LIABILITY),
    ("Securities & Deposits (Asset)", False, "Current Assets", AccountGroup.Nature.ASSET),
    ("Stock-in-hand", False, "Current Assets", AccountGroup.Nature.ASSET),
    ("Sundry Creditors", False, "Current Liabilities", AccountGroup.Nature.LIABILITY),
    ("Sundry Debtors", False, "Current Assets", AccountGroup.Nature.ASSET),
    ("Unsecured Loans", False, "Loans (Liability)", AccountGroup.Nature.LIABILITY),
]

DEFAULT_UNITS = ["NOS", "PCS", "KG", "GMS", "LTR", "MTR", "BOX", "PKT"]

# name, group — opening Dr/Cr follows group nature (asset/expense Dr, else Cr)
DEFAULT_ACCOUNTS = [
    ("Add. Cess Adjustable Agnst. Advance", "Current Assets"),
    ("Add. Cess on GST Input", "Duties & Taxes"),
    ("Add. Cess on GST Output", "Duties & Taxes"),
    ("Advertisement & Publicity", "Expenses (Indirect/Admn.)"),
    ("Bad Debts Written Off", "Expenses (Indirect/Admn.)"),
    ("Bank Charges", "Expenses (Indirect/Admn.)"),
    ("Books & Periodicals", "Expenses (Indirect/Admn.)"),
    ("Capital Equipments", "Fixed Assets"),
    ("Cash", "Cash-in-hand"),
    ("Cess Adjustable Agnst. Advance", "Current Assets"),
    ("Cess Input Available (RCM)", "Current Assets"),
    ("Cess on GST Input", "Duties & Taxes"),
    ("Cess on GST Output", "Duties & Taxes"),
    ("Cess Output (RCM)", "Duties & Taxes"),
    ("CGST Adjustable Agnst. Advance", "Current Assets"),
    ("CGST Input", "Duties & Taxes"),
    ("CGST Input Available (RCM)", "Current Assets"),
    ("CGST Output", "Duties & Taxes"),
    ("CGST Output (RCM)", "Duties & Taxes"),
    ("Charity & Donations", "Expenses (Indirect/Admn.)"),
    ("Commission on Sales", "Expenses (Indirect/Admn.)"),
    ("Computers", "Fixed Assets"),
    ("Conveyance Expenses", "Expenses (Indirect/Admn.)"),
    ("Customer Entertainment Expenses", "Expenses (Indirect/Admn.)"),
    ("Depreciation A/c", "Expenses (Indirect/Admn.)"),
    ("Earnest Money", "Securities & Deposits (Asset)"),
    ("Edu. Cess on TDS", "Duties & Taxes"),
    ("Freight & Forwarding Charges", "Expenses (Indirect/Admn.)"),
    ("Furniture & Fixture", "Fixed Assets"),
    ("IGST Adjustable Agnst. Advance", "Current Assets"),
    ("IGST Input", "Duties & Taxes"),
    ("IGST Input Available (RCM)", "Current Assets"),
    ("IGST Output", "Duties & Taxes"),
    ("IGST Output (RCM)", "Duties & Taxes"),
    ("IGST Refundable Agnst. Export / SEZ Unit", "Current Assets"),
    ("Legal Expenses", "Expenses (Indirect/Admn.)"),
    ("Miscellaneous Expenses", "Expenses (Indirect/Admn.)"),
    ("Office Equipments", "Fixed Assets"),
    ("Office Maintenance Expenses", "Expenses (Indirect/Admn.)"),
    ("Office Rent", "Expenses (Indirect/Admn.)"),
    ("Plant & Machinery", "Fixed Assets"),
    ("Postal Expenses", "Expenses (Indirect/Admn.)"),
    ("Printing & Stationery", "Expenses (Indirect/Admn.)"),
    ("Profit & Loss", "Profit & Loss"),
    ("Purchase", "Purchase"),
    ("Rounded Off", "Expenses (Indirect/Admn.)"),
    ("Salary", "Expenses (Indirect/Admn.)"),
    ("Salary & Bonus Payable", "Provisions/Expenses Payable"),
    ("Sales", "Sale"),
    ("Sales Promotion Expenses", "Expenses (Indirect/Admn.)"),
    ("Service Charges Paid", "Expenses (Indirect/Admn.)"),
    ("Service Charges Receipts", "Income (Indirect)"),
    ("SGST Adjustable Agnst. Advance", "Current Assets"),
    ("SGST Input", "Duties & Taxes"),
    ("SGST Input Available (RCM)", "Current Assets"),
    ("SGST Output", "Duties & Taxes"),
    ("SGST Output (RCM)", "Duties & Taxes"),
    ("SHE Cess on TDS", "Duties & Taxes"),
    ("Staff Welfare Expenses", "Expenses (Indirect/Admn.)"),
    ("Stock", "Stock-in-hand"),
    ("TCS (CGST)", "Duties & Taxes"),
    ("TCS (IGST)", "Duties & Taxes"),
    ("TCS (SGST)", "Duties & Taxes"),
    ("Tax Collected at Source", "Duties & Taxes"),
    ("TDS on Interest", "Duties & Taxes"),
    ("TDS on Professional Services", "Duties & Taxes"),
    ("TDS on Rent", "Duties & Taxes"),
    ("TDS on Salary", "Duties & Taxes"),
    ("Telephone Expenses", "Expenses (Indirect/Admn.)"),
    ("Travelling Expenses", "Expenses (Indirect/Admn.)"),
    ("Water & Electricity Expenses", "Expenses (Indirect/Admn.)"),
]

LEGACY_ACCOUNT_NAMES = {
    "Capital",
    "Bank",
    "Stock-in-hand",
    "Sundry Debtors",
    "Sundry Creditors",
    "GST",
    "Discount Allowed",
    "Discount Received",
    "Freight & Cartage",
    "Freight Charged",
    "Round Off",
    "Profit & Loss A/c",
}


def seed_erp_defaults():
    groups = {}
    for name, primary, under, nature in DEFAULT_GROUPS:
        parent = groups.get(under) if under else None
        obj = AccountGroup.objects.filter(name__iexact=name).first()
        if not obj:
            obj = AccountGroup.objects.create(
                name=name,
                primary_group=primary,
                under_group=parent,
                nature=nature,
            )
            created = True
        else:
            created = False
        if not created:
            changed = False
            if obj.primary_group != primary:
                obj.primary_group = primary
                changed = True
            if obj.under_group_id != (parent.id if parent else None):
                obj.under_group = parent
                changed = True
            if obj.nature != nature:
                obj.nature = nature
                changed = True
            if changed:
                obj.save()
        groups[name] = obj

    debit_natures = {AccountGroup.Nature.ASSET, AccountGroup.Nature.EXPENSE}
    accounts = {}
    for acc_name, group_name in DEFAULT_ACCOUNTS:
        group = groups[group_name]
        opening_type = (
            Account.OpeningType.DR
            if group.nature in debit_natures
            else Account.OpeningType.CR
        )
        obj = Account.objects.filter(account_name__iexact=acc_name).first()
        if not obj:
            obj = Account.objects.create(
                account_name=acc_name,
                account_group=group,
                opening=0,
                opening_type=opening_type,
            )
            created = True
        else:
            created = False
        if not created and obj.account_group_id != group.id:
            obj.account_group = group
            obj.save(update_fields=["account_group"])
        accounts[acc_name] = obj

    for unit_name in DEFAULT_UNITS:
        obj = Unit.objects.filter(name__iexact=unit_name).first()
        if not obj:
            Unit.objects.create(
                name=unit_name,
                print_name=unit_name,
            )

    sales_acc = accounts["Sales"]
    purchase_acc = accounts["Purchase"]
    cgst_out = accounts["CGST Output"]
    sgst_out = accounts["SGST Output"]
    igst_out = accounts["IGST Output"]
    cgst_in = accounts["CGST Input"]
    sgst_in = accounts["SGST Input"]
    igst_in = accounts["IGST Input"]
    half = Decimal("50.00")

    local_sale = SaleType.objects.filter(name__iexact="Local Sale").first()
    if not local_sale:
        local_sale = SaleType.objects.create(
            name="Local Sale",
            sales_account=sales_acc,
            tax_account=cgst_out,
            tax_account_2=sgst_out,
            tax_split_percent=half,
            affect_stock=True,
        )
    else:
        local_sale.sales_account = sales_acc
        local_sale.tax_account = cgst_out
        local_sale.tax_account_2 = sgst_out
        local_sale.tax_split_percent = half
        local_sale.save()

    inter_sale = SaleType.objects.filter(name__iexact="Interstate Sale").first()
    if not inter_sale:
        inter_sale = SaleType.objects.create(
            name="Interstate Sale",
            sales_account=sales_acc,
            tax_account=igst_out,
            tax_account_2=None,
            tax_split_percent=half,
            affect_stock=True,
        )
    else:
        inter_sale.sales_account = sales_acc
        inter_sale.tax_account = igst_out
        inter_sale.tax_account_2 = None
        inter_sale.save()

    local_pur = PurchaseType.objects.filter(name__iexact="Local Purchase").first()
    if not local_pur:
        local_pur = PurchaseType.objects.create(
            name="Local Purchase",
            purchase_account=purchase_acc,
            tax_account=cgst_in,
            tax_account_2=sgst_in,
            tax_split_percent=half,
            affect_stock=True,
        )
    else:
        local_pur.purchase_account = purchase_acc
        local_pur.tax_account = cgst_in
        local_pur.tax_account_2 = sgst_in
        local_pur.tax_split_percent = half
        local_pur.save()

    inter_pur = PurchaseType.objects.filter(name__iexact="Interstate Purchase").first()
    if not inter_pur:
        inter_pur = PurchaseType.objects.create(
            name="Interstate Purchase",
            purchase_account=purchase_acc,
            tax_account=igst_in,
            tax_account_2=None,
            tax_split_percent=half,
            affect_stock=True,
        )
    else:
        inter_pur.purchase_account = purchase_acc
        inter_pur.tax_account = igst_in
        inter_pur.tax_account_2 = None
        inter_pur.save()

    sundries = [
        {
            "name": "Discount",
            "type": BillSundry.SundryType.SUBTRACTIVE,
            "amount_of": BillSundry.AmountOf.PERCENT,
            "default_value": 0,
            "apply_on": BillSundry.ApplyOn.ITEM_BASIC,
            "posting_account_sale": accounts["Miscellaneous Expenses"],
            "posting_account_purchase": accounts["Miscellaneous Expenses"],
        },
        {
            "name": "Freight Charged",
            "type": BillSundry.SundryType.ADDITIVE,
            "amount_of": BillSundry.AmountOf.ABSOLUTE,
            "default_value": 0,
            "apply_on": BillSundry.ApplyOn.BILL_AMOUNT,
            "posting_account_sale": accounts["Service Charges Receipts"],
            "posting_account_purchase": accounts["Freight & Forwarding Charges"],
        },
        {
            "name": "Freight Inward",
            "type": BillSundry.SundryType.ADDITIVE,
            "amount_of": BillSundry.AmountOf.ABSOLUTE,
            "default_value": 0,
            "apply_on": BillSundry.ApplyOn.BILL_AMOUNT,
            "posting_account_sale": accounts["Service Charges Receipts"],
            "posting_account_purchase": accounts["Freight & Forwarding Charges"],
        },
        {
            "name": "Discount Received",
            "type": BillSundry.SundryType.SUBTRACTIVE,
            "amount_of": BillSundry.AmountOf.PERCENT,
            "default_value": 0,
            "apply_on": BillSundry.ApplyOn.ITEM_BASIC,
            "posting_account_sale": accounts["Service Charges Receipts"],
            "posting_account_purchase": accounts["Service Charges Receipts"],
        },
        {
            "name": "GST on Bill",
            "type": BillSundry.SundryType.ADDITIVE,
            "amount_of": BillSundry.AmountOf.PERCENT,
            "default_value": 0,
            "apply_on": BillSundry.ApplyOn.ITEM_AMOUNT,
            "posting_account_sale": cgst_out,
            "posting_account_purchase": cgst_out,
        },
        {
            "name": "Round Off",
            "type": BillSundry.SundryType.ADDITIVE,
            "amount_of": BillSundry.AmountOf.ABSOLUTE,
            "default_value": 0,
            "apply_on": BillSundry.ApplyOn.BILL_AMOUNT,
            "posting_account_sale": accounts["Rounded Off"],
            "posting_account_purchase": accounts["Rounded Off"],
        },
    ]
    for data in sundries:
        obj = BillSundry.objects.filter(name__iexact=data["name"]).first()
        if not obj:
            obj = BillSundry.objects.create(**data)
        else:
            obj.posting_account_sale = data["posting_account_sale"]
            obj.posting_account_purchase = data["posting_account_purchase"]
            obj.save(update_fields=["posting_account_sale", "posting_account_purchase"])

    _retire_legacy_accounts(accounts)


def _repoint_account(old, new):
    from django.db import connection
    from django.db.models.deletion import ProtectedError

    if old is None or new is None or old.id == new.id:
        return
    Sale.objects.filter(account=old).update(account=new)
    Purchase.objects.filter(account=old).update(account=new)
    SaleType.objects.filter(sales_account=old).update(sales_account=new)
    SaleType.objects.filter(tax_account=old).update(tax_account=new)
    SaleType.objects.filter(tax_account_2=old).update(tax_account_2=new)
    PurchaseType.objects.filter(purchase_account=old).update(purchase_account=new)
    PurchaseType.objects.filter(tax_account=old).update(tax_account=new)
    PurchaseType.objects.filter(tax_account_2=old).update(tax_account_2=new)
    BillSundry.objects.filter(posting_account_sale=old).update(posting_account_sale=new)
    BillSundry.objects.filter(posting_account_purchase=old).update(posting_account_purchase=new)
    tables = set(connection.introspection.table_names())
    if "masters_payment" in tables:
        Payment.objects.filter(account=old).update(account=new)
        Payment.objects.filter(through=old).update(through=new)
    if "masters_receipt" in tables:
        Receipt.objects.filter(account=old).update(account=new)
        Receipt.objects.filter(through=old).update(through=new)
    if "masters_journalline" in tables:
        JournalLine.objects.filter(account=old).update(account=new)
    try:
        old.delete()
    except ProtectedError:
        pass


def _retire_legacy_accounts(accounts):
    remap = {
        "GST": accounts["CGST Output"],
        "Discount Allowed": accounts["Miscellaneous Expenses"],
        "Discount Received": accounts["Service Charges Receipts"],
        "Freight Charged": accounts["Service Charges Receipts"],
        "Freight & Cartage": accounts["Freight & Forwarding Charges"],
        "Round Off": accounts["Rounded Off"],
        "Profit & Loss A/c": accounts["Profit & Loss"],
        "Stock-in-hand": accounts["Stock"],
    }
    for old_name, new in remap.items():
        old = Account.objects.filter(account_name=old_name).first()
        _repoint_account(old, new)

    keep = {name for name, _ in DEFAULT_ACCOUNTS}
    from django.db.models.deletion import ProtectedError

    for old_name in LEGACY_ACCOUNT_NAMES:
        if old_name in keep:
            continue
        old = Account.objects.filter(account_name=old_name).first()
        if not old:
            continue
        try:
            old.delete()
        except ProtectedError:
            pass


@receiver(post_migrate)
def create_default_erp_masters(sender, **kwargs):
    if sender.name != "masters":
        return
    seed_erp_defaults()
