# Generated by Django 3.2 on 2022-03-09 12:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parking_permits", "0017_alter_refund_iban"),
    ]

    operations = [
        migrations.AddField(
            model_name="parkingpermit",
            name="description",
            field=models.TextField(blank=True, verbose_name="Description"),
        ),
    ]
