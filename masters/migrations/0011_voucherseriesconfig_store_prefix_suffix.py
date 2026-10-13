from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0010_voucherseriesconfig'),
    ]

    operations = [
        migrations.AddField(
            model_name='voucherseriesconfig',
            name='store_prefix_suffix',
            field=models.BooleanField(
                default=False,
                verbose_name='Store prefix/suffix in voucher number',
                help_text=(
                    "OFF: voucher screens hold only the number (0001); prefix/suffix show on reports. "
                    "ON: the prefix/suffix you set above is saved as part of the voucher number itself "
                    "(e.g. INV-0001/26) on screens, prints and reports."
                ),
            ),
        ),
    ]
