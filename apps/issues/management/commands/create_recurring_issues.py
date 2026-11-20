from django.core.management.base import BaseCommand

from apps.issues.tools import run_recurring


class Command(BaseCommand):
    help = "Open the issues of every recurring rule that is due (run once a day, early morning)."

    def handle(self, *args, **options):
        self.stdout.write(f"Created {run_recurring()} recurring issue(s).")
