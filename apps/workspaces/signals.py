from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Membership, Workspace

User = get_user_model()


@receiver(post_save, sender=User)
def create_personal_workspace(sender, instance, created, **kwargs):
    if not created:
        return
    workspace = Workspace.objects.create(
        name=f"{instance.username}'s Workspace",
        owner=instance,
        is_personal=True,
    )
    Membership.objects.create(workspace=workspace, user=instance, role=Membership.Role.OWNER)
