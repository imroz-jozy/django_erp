# Generated manually for Payment and Receipt models

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0002_erp_masters'),
    ]

    operations = [
        migrations.CreateModel(
            name='Payment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('voucher_no', models.CharField(blank=True, max_length=50)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=15)),
                ('narration', models.TextField(blank=True)),
                ('account', models.ForeignKey(help_text='Party or expense ledger (debited).', on_delete=django.db.models.deletion.PROTECT, related_name='payments', to='masters.account')),
                ('through', models.ForeignKey(help_text='Cash or bank ledger (credited).', on_delete=django.db.models.deletion.PROTECT, related_name='payments_through', to='masters.account')),
            ],
            options={
                'verbose_name': 'Payment',
                'verbose_name_plural': 'Payments',
                'ordering': ['-date', '-id'],
            },
        ),
        migrations.CreateModel(
            name='Receipt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('voucher_no', models.CharField(blank=True, max_length=50)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=15)),
                ('narration', models.TextField(blank=True)),
                ('account', models.ForeignKey(help_text='Party or income ledger (credited).', on_delete=django.db.models.deletion.PROTECT, related_name='receipts', to='masters.account')),
                ('through', models.ForeignKey(help_text='Cash or bank ledger (debited).', on_delete=django.db.models.deletion.PROTECT, related_name='receipts_through', to='masters.account')),
            ],
            options={
                'verbose_name': 'Receipt',
                'verbose_name_plural': 'Receipts',
                'ordering': ['-date', '-id'],
            },
        ),
    ]
