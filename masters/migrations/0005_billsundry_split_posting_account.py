import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0004_remove_purchaseitem_description_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='billsundry',
            name='posting_account',
        ),
        migrations.AddField(
            model_name='billsundry',
            name='posting_account_sale',
            field=models.ForeignKey(
                blank=True,
                help_text='Ledger posted when this sundry appears on a Sale voucher.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='bill_sundries_sale',
                to='masters.account',
            ),
        ),
        migrations.AddField(
            model_name='billsundry',
            name='posting_account_purchase',
            field=models.ForeignKey(
                blank=True,
                help_text='Ledger posted when this sundry appears on a Purchase voucher.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='bill_sundries_purchase',
                to='masters.account',
            ),
        ),
    ]
