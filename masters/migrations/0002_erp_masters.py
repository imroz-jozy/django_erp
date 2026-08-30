# Generated manually for ERP masters expansion

import django.db.models.deletion
from django.db import migrations, models


def convert_item_units(apps, schema_editor):
    Unit = apps.get_model("masters", "Unit")
    Item = apps.get_model("masters", "Item")
    nos, _ = Unit.objects.get_or_create(name="NOS", defaults={"print_name": "NOS", "decimal_places": 2})
    for item in Item.objects.all():
        old = (item.main_unit_text or "NOS").strip() or "NOS"
        unit, _ = Unit.objects.get_or_create(
            name=old.upper()[:50],
            defaults={"print_name": old, "decimal_places": 2},
        )
        item.main_unit = unit
        alt = (item.alt_unit_text or "").strip()
        if alt:
            alt_unit, _ = Unit.objects.get_or_create(
                name=alt.upper()[:50],
                defaults={"print_name": alt, "decimal_places": 2},
            )
            item.alt_unit = alt_unit
        item.save(update_fields=["main_unit", "alt_unit"])


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountgroup",
            name="nature",
            field=models.CharField(
                choices=[
                    ("ASSET", "Asset"),
                    ("LIABILITY", "Liability"),
                    ("INCOME", "Income"),
                    ("EXPENSE", "Expense"),
                    ("EQUITY", "Equity"),
                ],
                default="ASSET",
                max_length=12,
            ),
        ),
        migrations.AlterModelOptions(
            name="account",
            options={"ordering": ["account_name"], "verbose_name": "Account", "verbose_name_plural": "Accounts"},
        ),
        migrations.AlterModelOptions(
            name="accountgroup",
            options={"ordering": ["name"], "verbose_name": "Account Group", "verbose_name_plural": "Account Groups"},
        ),
        migrations.AlterModelOptions(
            name="billsundry",
            options={"ordering": ["name"], "verbose_name": "Bill Sundry", "verbose_name_plural": "Bill Sundries"},
        ),
        migrations.AlterModelOptions(
            name="item",
            options={"ordering": ["item_name"], "verbose_name": "Item", "verbose_name_plural": "Items"},
        ),
        migrations.AlterModelOptions(
            name="purchase",
            options={"ordering": ["-date", "-id"], "verbose_name": "Purchase", "verbose_name_plural": "Purchases"},
        ),
        migrations.AlterModelOptions(
            name="purchasebillsundry",
            options={"verbose_name": "Purchase Bill Sundry", "verbose_name_plural": "Purchase Bill Sundries"},
        ),
        migrations.AlterModelOptions(
            name="purchaseitem",
            options={"verbose_name": "Purchase Item", "verbose_name_plural": "Purchase Items"},
        ),
        migrations.AlterModelOptions(
            name="sale",
            options={"ordering": ["-date", "-id"], "verbose_name": "Sale", "verbose_name_plural": "Sales"},
        ),
        migrations.AlterModelOptions(
            name="salebillsundry",
            options={"verbose_name": "Sale Bill Sundry", "verbose_name_plural": "Sale Bill Sundries"},
        ),
        migrations.AlterModelOptions(
            name="saleitem",
            options={"verbose_name": "Sale Item", "verbose_name_plural": "Sale Items"},
        ),
        migrations.CreateModel(
            name="Unit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=50, unique=True)),
                ("print_name", models.CharField(blank=True, max_length=50)),
                ("decimal_places", models.PositiveSmallIntegerField(default=2)),
            ],
            options={
                "verbose_name": "Unit",
                "verbose_name_plural": "Units",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="SaleType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("affect_stock", models.BooleanField(default=True)),
                ("tax_inclusive", models.BooleanField(default=False)),
                (
                    "sales_account",
                    models.ForeignKey(
                        help_text="Ledger credited for sales (usually under Sale).",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sale_types",
                        to="masters.account",
                    ),
                ),
                (
                    "tax_account",
                    models.ForeignKey(
                        blank=True,
                        help_text="Ledger credited for item tax (Duties & Taxes).",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sale_type_tax",
                        to="masters.account",
                    ),
                ),
            ],
            options={
                "verbose_name": "Sale Type",
                "verbose_name_plural": "Sale Types",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="PurchaseType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("affect_stock", models.BooleanField(default=True)),
                ("tax_inclusive", models.BooleanField(default=False)),
                (
                    "purchase_account",
                    models.ForeignKey(
                        help_text="Ledger debited for purchases (usually under Purchase).",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="purchase_types",
                        to="masters.account",
                    ),
                ),
                (
                    "tax_account",
                    models.ForeignKey(
                        blank=True,
                        help_text="Ledger debited for item tax (Duties & Taxes).",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="purchase_type_tax",
                        to="masters.account",
                    ),
                ),
            ],
            options={
                "verbose_name": "Purchase Type",
                "verbose_name_plural": "Purchase Types",
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="billsundry",
            name="amount_of",
            field=models.CharField(
                choices=[("PERCENT", "Percentage"), ("ABSOLUTE", "Absolute amount")],
                default="PERCENT",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="billsundry",
            name="apply_on",
            field=models.CharField(
                choices=[
                    ("ITEM_BASIC", "Item basic amount"),
                    ("ITEM_DISCOUNT", "Item discount amount"),
                    ("ITEM_AMOUNT", "Item amount (after discount)"),
                    ("TAX_AMOUNT", "Tax amount"),
                    ("ITEM_NET", "Item net amount"),
                    ("BILL_AMOUNT", "Bill amount (running total)"),
                    ("PREVIOUS_SUNDRY", "Previous bill sundry"),
                ],
                default="ITEM_BASIC",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="billsundry",
            name="default_value",
            field=models.DecimalField(
                decimal_places=4,
                default=0,
                help_text="Percentage or default amount, depending on Amount Of.",
                max_digits=15,
            ),
        ),
        migrations.AddField(
            model_name="billsundry",
            name="posting_account",
            field=models.ForeignKey(
                blank=True,
                help_text="Ledger for this sundry (discount, freight, round off, etc.).",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bill_sundries",
                to="masters.account",
            ),
        ),
        migrations.AlterField(
            model_name="billsundry",
            name="name",
            field=models.CharField(max_length=100, unique=True),
        ),
        migrations.AddField(
            model_name="sale",
            name="sale_type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sales",
                to="masters.saletype",
            ),
        ),
        migrations.AddField(
            model_name="purchase",
            name="purchase_type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="purchases",
                to="masters.purchasetype",
            ),
        ),
        migrations.AddField(
            model_name="saleitem",
            name="unit",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sale_items",
                to="masters.unit",
            ),
        ),
        migrations.AddField(
            model_name="purchaseitem",
            name="unit",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="purchase_items",
                to="masters.unit",
            ),
        ),
        migrations.RenameField(
            model_name="item",
            old_name="main_unit",
            new_name="main_unit_text",
        ),
        migrations.RenameField(
            model_name="item",
            old_name="alt_unit",
            new_name="alt_unit_text",
        ),
        migrations.AddField(
            model_name="item",
            name="main_unit",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="items_main",
                to="masters.unit",
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="alt_unit",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="items_alt",
                to="masters.unit",
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="conversion",
            field=models.DecimalField(
                decimal_places=4,
                default=1,
                help_text="1 main unit = conversion alt units",
                max_digits=15,
            ),
        ),
        migrations.RunPython(convert_item_units, migrations.RunPython.noop),
        migrations.RemoveField(model_name="item", name="main_unit_text"),
        migrations.RemoveField(model_name="item", name="alt_unit_text"),
        migrations.AlterField(
            model_name="item",
            name="main_unit",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="items_main",
                to="masters.unit",
            ),
        ),
        migrations.AlterField(
            model_name="salebillsundry",
            name="amount",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="Leave 0 to auto-calculate from bill sundry formula.",
                max_digits=15,
            ),
        ),
        migrations.AlterField(
            model_name="purchasebillsundry",
            name="amount",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="Leave 0 to auto-calculate from bill sundry formula.",
                max_digits=15,
            ),
        ),
    ]
