from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('orders', '0004_alter_returnrequest_options')]

    operations = [
        migrations.AddField(
            model_name='order',
            name='razorpay_receipt',
            field=models.CharField(
                max_length=40, unique=True, null=True, blank=True, editable=False,
            ),
        ),
    ]
