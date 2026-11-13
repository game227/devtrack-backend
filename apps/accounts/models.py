from django.contrib.auth.models import AbstractUser
from django.db import models

from .avatars import avatar_upload_path


class User(AbstractUser):
    email = models.EmailField("email address", unique=True, blank=True)
    avatar = models.ImageField(upload_to=avatar_upload_path, blank=True, null=True)
    bio = models.TextField(blank=True)
    # Profile-facing job title (e.g. "Senior Backend Developer") — distinct
    # from Membership.role, which is the workspace permission level.
    title = models.CharField(max_length=150, blank=True)
    email_verified = models.BooleanField(default=False)
