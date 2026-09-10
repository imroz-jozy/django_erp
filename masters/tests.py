from datetime import date
from decimal import Decimal
from io import BytesIO

import openpyxl

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.forms.models import inlineformset_factory
from django.test import TestCase, Client
from django.urls import reverse

from masters.models import (
    Account,
    AccountGroup,
    Item,
    Journal,
    JournalLine,
    Purchase,
    Sale,
    Unit,
)
from masters.admin import JournalLineForm, JournalLineFormSet
from masters.excel_service import import_purchases_from_excel, import_sales_from_excel
from masters.reports import (
    account_ledger,
    build_ledgers,
    journal_register,
    _voucher_entries_for_account,
)


class JournalModelTestCase(TestCase):
    def setUp(self):
        self.group, _ = AccountGroup.objects.get_or_create(
            name="Expenses (Indirect/Admn.)",
            defaults={"primary_group": False, "nature": AccountGroup.Nature.EXPENSE},
        )
        self.acc_rent, _ = Account.objects.get_or_create(
            account_name="Rent Expense Test",
            defaults={"account_group": self.group},
        )
        self.acc_cash, _ = Account.objects.get_or_create(
            account_name="Cash in Hand Test",
            defaults={"account_group": self.group},
        )

    def test_voucher_no_auto_generation(self):
        jrn = Journal.objects.create(date=date(2026, 1, 1))
        self.assertTrue(jrn.voucher_no.startswith("JRN-"))
        self.assertEqual(str(jrn), jrn.voucher_no)

    def test_totals_and_lines_summary(self):
        jrn = Journal.objects.create(date=date(2026, 1, 1), narration="Monthly Rent")
        JournalLine.objects.create(
            journal=jrn,
            account=self.acc_rent,
            debit=Decimal("1500.00"),
            credit=Decimal("0.00"),
        )
        JournalLine.objects.create(
            journal=jrn,
            account=self.acc_cash,
            debit=Decimal("0.00"),
            credit=Decimal("1500.00"),
        )
        totals = jrn.totals()
        self.assertEqual(totals["debit"], Decimal("1500.00"))
        self.assertEqual(totals["credit"], Decimal("1500.00"))
        self.assertEqual(totals["difference"], Decimal("0.00"))

        summary = jrn.lines_summary()
        self.assertIn("Dr Rent Expense Test 1,500.00", summary)
        self.assertIn("Cr Cash in Hand Test 1,500.00", summary)


class JournalLineValidationTestCase(TestCase):
    def setUp(self):
        self.group, _ = AccountGroup.objects.get_or_create(
            name="Expenses (Indirect/Admn.)",
            defaults={"primary_group": False, "nature": AccountGroup.Nature.EXPENSE},
        )
        self.account, _ = Account.objects.get_or_create(
            account_name="Office Supplies Test",
            defaults={"account_group": self.group},
        )
        self.journal = Journal.objects.create(date=date(2026, 1, 1))

    def test_line_cannot_have_both_debit_and_credit(self):
        line = JournalLine(
            journal=self.journal,
            account=self.account,
            debit=Decimal("100.00"),
            credit=Decimal("50.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            line.clean()
        self.assertIn("A line cannot have both debit and credit", str(ctx.exception))

    def test_line_cannot_have_both_zero(self):
        line = JournalLine(
            journal=self.journal,
            account=self.account,
            debit=Decimal("0.00"),
            credit=Decimal("0.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            line.clean()
        self.assertIn("Enter debit or credit amount", str(ctx.exception))

    def test_line_cannot_have_negative_amount(self):
        line_neg_dr = JournalLine(
            journal=self.journal,
            account=self.account,
            debit=Decimal("-10.00"),
            credit=Decimal("0.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            line_neg_dr.clean()
        self.assertIn("amounts cannot be negative", str(ctx.exception))

        line_neg_cr = JournalLine(
            journal=self.journal,
            account=self.account,
            debit=Decimal("0.00"),
            credit=Decimal("-25.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            line_neg_cr.clean()
        self.assertIn("amounts cannot be negative", str(ctx.exception))


class JournalFormSetValidationTestCase(TestCase):
    def setUp(self):
        self.group, _ = AccountGroup.objects.get_or_create(
            name="Current Liabilities",
            defaults={"primary_group": True, "nature": AccountGroup.Nature.LIABILITY},
        )
        self.acc1, _ = Account.objects.get_or_create(
            account_name="Vendor A Test",
            defaults={"account_group": self.group},
        )
        self.acc2, _ = Account.objects.get_or_create(
            account_name="Vendor B Test",
            defaults={"account_group": self.group},
        )
        self.journal = Journal.objects.create(date=date(2026, 1, 1))
        self.FormSet = inlineformset_factory(
            Journal,
            JournalLine,
            form=JournalLineForm,
            formset=JournalLineFormSet,
            extra=2,
            can_delete=True,
        )

    def test_balanced_formset_is_valid(self):
        data = {
            "lines-TOTAL_FORMS": "2",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-account": str(self.acc1.pk),
            "lines-0-debit": "500.00",
            "lines-0-credit": "0.00",
            "lines-0-remarks": "Line 1",
            "lines-1-account": str(self.acc2.pk),
            "lines-1-debit": "0.00",
            "lines-1-credit": "500.00",
            "lines-1-remarks": "Line 2",
        }
        formset = self.FormSet(data, instance=self.journal, prefix="lines")
        self.assertTrue(formset.is_valid(), formset.errors)

    def test_unbalanced_formset_raises_validation_error(self):
        data = {
            "lines-TOTAL_FORMS": "2",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-account": str(self.acc1.pk),
            "lines-0-debit": "500.00",
            "lines-0-credit": "0.00",
            "lines-1-account": str(self.acc2.pk),
            "lines-1-debit": "0.00",
            "lines-1-credit": "400.00",
        }
        formset = self.FormSet(data, instance=self.journal, prefix="lines")
        self.assertFalse(formset.is_valid())
        non_form_errors = formset.non_form_errors()
        self.assertTrue(any("must be equal" in err for err in non_form_errors))

    def test_single_line_raises_error(self):
        data = {
            "lines-TOTAL_FORMS": "2",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-account": str(self.acc1.pk),
            "lines-0-debit": "500.00",
            "lines-0-credit": "0.00",
            "lines-1-account": "",
            "lines-1-debit": "",
            "lines-1-credit": "",
        }
        formset = self.FormSet(data, instance=self.journal, prefix="lines")
        self.assertFalse(formset.is_valid())
        self.assertTrue(any("at least two journal lines" in err for err in formset.non_form_errors()))


class JournalReportsTestCase(TestCase):
    def setUp(self):
        self.group, _ = AccountGroup.objects.get_or_create(
            name="Bank Accounts",
            defaults={"primary_group": False, "nature": AccountGroup.Nature.ASSET},
        )
        self.bank_a, _ = Account.objects.get_or_create(
            account_name="HDFC Bank Test",
            defaults={"account_group": self.group},
        )
        self.bank_b, _ = Account.objects.get_or_create(
            account_name="ICICI Bank Test",
            defaults={"account_group": self.group},
        )
        self.uninvolved, _ = Account.objects.get_or_create(
            account_name="SBI Bank Test",
            defaults={"account_group": self.group},
        )
        self.journal = Journal.objects.create(
            date=date(2026, 2, 10),
            narration="Bank transfer",
        )
        JournalLine.objects.create(
            journal=self.journal,
            account=self.bank_a,
            debit=Decimal("10000.00"),
            credit=Decimal("0.00"),
            remarks="Contra transfer to HDFC",
        )
        JournalLine.objects.create(
            journal=self.journal,
            account=self.bank_b,
            debit=Decimal("0.00"),
            credit=Decimal("10000.00"),
            remarks="Contra transfer from ICICI",
        )

    def test_journal_register(self):
        rows, total = journal_register(date(2026, 2, 1), date(2026, 2, 28))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], self.journal)
        self.assertEqual(total, Decimal("10000.00"))

    def test_build_ledgers(self):
        ledgers = build_ledgers(date(2026, 2, 1), date(2026, 2, 28))
        by_acc = {row["account"].id: row for row in ledgers}
        self.assertIn(self.bank_a.id, by_acc)
        self.assertIn(self.bank_b.id, by_acc)
        self.assertEqual(by_acc[self.bank_a.id]["debit"], Decimal("10000.00"))
        self.assertEqual(by_acc[self.bank_b.id]["credit"], Decimal("10000.00"))

    def test_voucher_entries_for_account_and_ledger(self):
        entries_a = _voucher_entries_for_account(self.bank_a)
        self.assertEqual(len(entries_a), 1)
        self.assertEqual(entries_a[0]["vtype"], "Journal")
        self.assertEqual(entries_a[0]["debit"], Decimal("10000.00"))

        entries_b = _voucher_entries_for_account(self.bank_b)
        self.assertEqual(len(entries_b), 1)
        self.assertEqual(entries_b[0]["vtype"], "Journal")
        self.assertEqual(entries_b[0]["credit"], Decimal("10000.00"))

        entries_other = _voucher_entries_for_account(self.uninvolved)
        self.assertEqual(len(entries_other), 0)

        ledger = account_ledger(self.bank_a, date(2026, 2, 1), date(2026, 2, 28))
        self.assertEqual(ledger["period_dr"], Decimal("10000.00"))
        self.assertEqual(ledger["period_cr"], Decimal("0.00"))
        self.assertEqual(ledger["closing_balance"], Decimal("10000.00"))


class JournalAdminViewsTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="adminuser",
            email="admin@example.com",
            password="adminpassword123",
        )
        self.client = Client()
        self.client.login(username="adminuser", password="adminpassword123")

        self.group, _ = AccountGroup.objects.get_or_create(
            name="Current Assets",
            defaults={"primary_group": True, "nature": AccountGroup.Nature.ASSET},
        )
        self.acc1, _ = Account.objects.get_or_create(
            account_name="Account 1 Test",
            defaults={"account_group": self.group},
        )
        self.acc2, _ = Account.objects.get_or_create(
            account_name="Account 2 Test",
            defaults={"account_group": self.group},
        )
        self.journal = Journal.objects.create(
            date=date(2026, 3, 1),
            narration="Test Journal Voucher",
        )
        JournalLine.objects.create(
            journal=self.journal,
            account=self.acc1,
            debit=Decimal("250.00"),
            credit=Decimal("0.00"),
        )
        JournalLine.objects.create(
            journal=self.journal,
            account=self.acc2,
            debit=Decimal("0.00"),
            credit=Decimal("250.00"),
        )

    def test_journal_changelist_view(self):
        url = reverse("admin:masters_journal_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.journal.voucher_no)
        self.assertContains(response, "250.00")

    def test_journal_change_view(self):
        url = reverse("admin:masters_journal_change", args=[self.journal.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "journal_helper.js")

    def test_journal_register_view(self):
        url = reverse("admin:erp_journal_register")
        response = self.client.get(url, {"from": "2026-03-01", "to": "2026-03-31"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.journal.voucher_no)
        self.assertContains(response, "Particulars")


class ExcelImportViewsTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="admin_test",
            password="testpassword",
            email="admin@test.com",
        )
        self.client = Client()
        self.client.force_login(self.admin_user)

    def test_item_import_view_get(self):
        url = reverse("admin:erp_item_import")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Import Items from Excel")
        self.assertContains(response, "Download Item Template")
        self.assertContains(response, "Template Column Reference")

    def test_account_import_view_get(self):
        url = reverse("admin:erp_account_import")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Import Accounts from Excel")
        self.assertContains(response, "Download Account Template")
        self.assertContains(response, "Template Column Reference")

    def test_item_changelist_has_buttons(self):
        url = reverse("admin:masters_item_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Download Excel Template")
        self.assertContains(response, "Import from Excel")

    def test_account_changelist_has_buttons(self):
        url = reverse("admin:masters_account_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Download Excel Template")
        self.assertContains(response, "Import from Excel")

    def test_erp_dashboard_has_import_section(self):
        url = reverse("admin:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Excel Data Import")
        self.assertContains(response, "Import Items")
        self.assertContains(response, "Import Accounts")
        self.assertContains(response, "Import Sales")
        self.assertContains(response, "Import Purchases")

    def test_sale_import_view_get(self):
        url = reverse("admin:erp_sale_import")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Import Sale Vouchers from Excel")
        self.assertContains(response, "Download Sale Voucher Template")
        self.assertContains(response, "Default Sale Type")

    def test_purchase_import_view_get(self):
        url = reverse("admin:erp_purchase_import")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Import Purchase Vouchers from Excel")
        self.assertContains(response, "Download Purchase Voucher Template")
        self.assertContains(response, "Default Purchase Type")

    def test_sale_changelist_has_buttons(self):
        url = reverse("admin:masters_sale_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Download Excel Template")
        self.assertContains(response, "Import from Excel")

    def test_purchase_changelist_has_buttons(self):
        url = reverse("admin:masters_purchase_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Download Excel Template")
        self.assertContains(response, "Import from Excel")


class VoucherExcelImportTestCase(TestCase):
    """Regression tests for Excel's explicit zero values."""

    def setUp(self):
        group = AccountGroup.objects.create(
            name="Excel Import Test Group",
            primary_group=False,
            nature=AccountGroup.Nature.ASSET,
        )
        self.party = Account.objects.create(
            account_name="Excel Import Test Party",
            account_group=group,
        )
        unit = Unit.objects.create(name="EIT-PCS")
        self.item = Item.objects.create(
            item_name="Excel Import Test Item",
            main_unit=unit,
            tax=Decimal("18.00"),
            sale_price=Decimal("100.00"),
            purchase_price=Decimal("80.00"),
        )

    def _workbook(self, party_header, invoice_no):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append([
            "Date *", "Invoice No *", party_header, "Item Name *",
            "Quantity *", "Rate", "Tax Rate %",
        ])
        sheet.append([
            "2026-09-01", invoice_no, self.party.account_name,
            self.item.item_name, 1, 0, 0,
        ])
        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        return output

    def test_sale_import_preserves_explicit_zero_rate_and_tax(self):
        result = import_sales_from_excel(
            self._workbook("Party (Customer) *", "EXCEL-SALE-0")
        )

        self.assertTrue(result["success"], result["errors"])
        line = Sale.objects.get(invoice_no="EXCEL-SALE-0").items.get()
        self.assertEqual(line.rate, Decimal("0.00"))
        self.assertEqual(line.tax, Decimal("0.00"))

    def test_purchase_import_preserves_explicit_zero_rate_and_tax(self):
        result = import_purchases_from_excel(
            self._workbook("Party (Supplier) *", "EXCEL-PURCHASE-0")
        )

        self.assertTrue(result["success"], result["errors"])
        line = Purchase.objects.get(invoice_no="EXCEL-PURCHASE-0").items.get()
        self.assertEqual(line.rate, Decimal("0.00"))
        self.assertEqual(line.tax, Decimal("0.00"))

