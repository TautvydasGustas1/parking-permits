from django.core.management.base import BaseCommand

from parking_permits.cron import automatic_remove_obsolete_customer_data


class Command(BaseCommand):
    help = "Automatically removing obsolete customer data."

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS("Removing Obsolete customer data started...")
        )
        automatic_remove_obsolete_customer_data()
        self.stdout.write(self.style.SUCCESS("Obsolete customer data removed."))
