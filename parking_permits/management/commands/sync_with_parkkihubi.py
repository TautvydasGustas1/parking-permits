from django.core.management.base import BaseCommand

from parking_permits.cron import automatic_syncing_of_permits_to_parkkihubi


class Command(BaseCommand):
    help = "Sync permits that has failed or hasn't been yet synced with parkkihubi."

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS("Syncing permits to parkkihubi started...")
        )
        automatic_syncing_of_permits_to_parkkihubi()
        self.stdout.write(self.style.SUCCESS("Permits synced with parkkihubi."))
