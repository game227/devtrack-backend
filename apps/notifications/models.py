from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Notification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    verb = models.CharField(max_length=30)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    target = GenericForeignKey("content_type", "object_id")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read", "-created_at"])]

    def __str__(self):
        return f"{self.verb} -> {self.recipient}"


class PushSubscription(models.Model):
    """One browser (or installed app) that agreed to receive this user's notifications by Web Push."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    lang = models.CharField(max_length=2, default="en")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"push for {self.user_id}"
