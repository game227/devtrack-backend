from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.workspaces.models import Workspace

from .models import DemoAccount


def delete_expired(now=None):
    """Delete expired demo accounts and the workspaces they own. Returns the number of accounts removed."""
    now = now or timezone.now()
    user_ids = list(DemoAccount.objects.filter(expires_at__lte=now).values_list("user_id", flat=True))
    if not user_ids:
        return 0
    with transaction.atomic():
        Workspace.objects.filter(owner_id__in=user_ids).delete()
        get_user_model().objects.filter(pk__in=user_ids).delete()
    return len(user_ids)
