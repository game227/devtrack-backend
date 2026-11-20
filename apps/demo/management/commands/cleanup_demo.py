from django.core.management.base import BaseCommand

from apps.demo.cleanup import delete_expired


class Command(BaseCommand):
    help = "Delete expired demo accounts and their workspaces (run hourly when DEMO_ENABLED)."

    def handle(self, *args, **options):
        self.stdout.write(f"Removed {delete_expired()} expired demo account(s).")
