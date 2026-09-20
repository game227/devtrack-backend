from django.core.management.base import BaseCommand

from apps.integrations.models import GitHubAccount


class Command(BaseCommand):
    help = (
        "Re-encrypt every stored GitHub access token with the first (primary) key in "
        "FIELD_ENCRYPTION_KEY. Run it after putting a new key first in that setting."
    )

    def handle(self, *args, **options):
        count = 0
        for account in GitHubAccount.objects.all():
            # Loading decrypts with any configured key; saving encrypts with the primary one.
            account.save(update_fields=["access_token", "updated_at"])
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Re-encrypted {count} GitHub token(s) with the primary key."))
