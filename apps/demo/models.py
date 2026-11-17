from django.conf import settings
from django.db import models


class DemoAccount(models.Model):
    """Marks a throwaway account made by "Try the demo". It and everything it owns go at `expires_at`."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="demo")
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"demo {self.user_id} until {self.expires_at:%Y-%m-%d %H:%M}"
