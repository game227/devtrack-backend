from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    bio = models.TextField(blank=True)
    # Profile-facing job title (e.g. "Senior Backend Developer") — distinct
    # from Membership.role, which is the workspace permission level.
    title = models.CharField(max_length=150, blank=True)
