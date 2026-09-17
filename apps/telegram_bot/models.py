from django.conf import settings
from django.db import models


class TelegramAccount(models.Model):
    """One DevTrack user's linked Telegram chat — used to deliver password-reset
    links (and, later, other notifications) outside of email."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="telegram_account"
    )
    chat_id = models.BigIntegerField(unique=True)
    telegram_username = models.CharField(max_length=255, blank=True)
    linked_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} -> telegram:{self.telegram_username or self.chat_id}"
