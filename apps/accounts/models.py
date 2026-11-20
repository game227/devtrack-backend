from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower

from apps.integrations.fields import EncryptedCharField

from .avatars import avatar_upload_path


class User(AbstractUser):
    email = models.EmailField("email address", unique=True, blank=True)
    avatar = models.ImageField(upload_to=avatar_upload_path, blank=True, null=True)
    bio = models.TextField(blank=True)
    # Profile-facing job title (e.g. "Senior Backend Developer") — distinct
    # from Membership.role, which is the workspace permission level.
    title = models.CharField(max_length=150, blank=True)
    email_verified = models.BooleanField(default=False)
    # A Monday email with the workspace's projects, overdue work and what got done (owners and admins).
    weekly_digest = models.BooleanField(default=True)
    # Two-factor authentication (TOTP). The secret is encrypted at rest; it is set during setup and only
    # takes effect once a code from the app has confirmed it (totp_enabled). Recovery codes are stored
    # hashed and each works once.
    totp_secret = EncryptedCharField(max_length=500, null=True, blank=True)
    totp_enabled = models.BooleanField(default=False)
    totp_last_step = models.BigIntegerField(null=True, blank=True)
    totp_recovery_codes = models.JSONField(default=list, blank=True)

    class Meta(AbstractUser.Meta):
        # "Jane" and "jane" (or two spellings of one mailbox) must be one account, also under concurrent
        # sign-ups that both pass the serializer's check. Blank emails are left out (accounts created
        # without one).
        constraints = [
            models.UniqueConstraint(Lower("username"), name="accounts_user_username_ci_unique"),
            models.UniqueConstraint(
                Lower("email"), condition=~models.Q(email=""), name="accounts_user_email_ci_unique"
            ),
        ]
