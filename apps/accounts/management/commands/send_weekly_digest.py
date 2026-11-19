from django.core.management.base import BaseCommand

from apps.accounts.digest import send_weekly_digests


class Command(BaseCommand):
    help = "Email workspace owners and admins a weekly summary (run Monday morning)."

    def add_arguments(self, parser):
        parser.add_argument("--lang", choices=["en", "uz", "ru"], default=None)

    def handle(self, *args, lang=None, **options):
        self.stdout.write(f"Sent {send_weekly_digests(lang)} weekly digest(s).")
