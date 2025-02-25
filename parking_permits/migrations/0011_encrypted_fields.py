# Generated by Django 3.2.13 on 2022-06-18 18:31

from django.db import migrations, models
import encrypted_fields.fields


class Migration(migrations.Migration):

    dependencies = [
        ("parking_permits", "0010_parkingpermit_synced_with_parkkihubi"),
    ]

    operations = [
        migrations.CreateModel(
            name="VehicleUser",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "_national_id_number",
                    encrypted_fields.fields.EncryptedCharField(
                        blank=True, max_length=50
                    ),
                ),
                (
                    "national_id_number",
                    encrypted_fields.fields.SearchField(
                        blank=True,
                        db_index=True,
                        encrypted_field_name="_national_id_number",
                        hash_key="National identification number",
                        max_length=66,
                        null=True,
                    ),
                ),
            ],
            options={
                "verbose_name": "Vehicle user",
                "verbose_name_plural": "Vehicle users",
            },
        ),
        migrations.AlterField(
            model_name="customer",
            name="national_id_number",
            field=encrypted_fields.fields.EncryptedCharField(
                blank=True, max_length=50, verbose_name="National identification number"
            ),
        ),
        migrations.RemoveField(
            model_name="vehicle",
            name="users",
        ),
        migrations.AddField(
            model_name="vehicle",
            name="users",
            field=models.ManyToManyField(to="parking_permits.VehicleUser"),
        ),
    ]
