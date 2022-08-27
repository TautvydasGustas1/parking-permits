from django.core.management.base import BaseCommand

from parking_permits.cron import automatic_expiration_of_permits


class Command(BaseCommand):
    help = "Mark all expired permits to close state."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Closing of expired permits started..."))
        automatic_expiration_of_permits()
        self.stdout.write(self.style.SUCCESS("Closing of expired permits done."))
