from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Usage: python manage.py bootstrap_parking_permits"

    def handle(self, *args, **options):
        call_command("import_parking_zones")

        call_command("create_vehicle_types")

        call_command(
            "create_parking_zone_prices",
            year=2021,
            data_module="parking_permits_app.data.2021",
        )

        call_command(
            "create_low_emission_criteria",
            year=2021,
            data_module="parking_permits_app.data.2021",
        )
