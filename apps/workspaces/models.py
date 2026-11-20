import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Exists, OuterRef
from django.utils import timezone
from django.utils.text import slugify

# An invitation nobody answered within this long has to be sent again.
INVITATION_TTL = timedelta(days=14)


class Workspace(models.Model):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True, blank=True)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_workspaces"
    )
    is_personal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "workspace"
            slug = base
            while Workspace.objects.filter(slug=slug).exists():
                slug = f"{base}-{uuid.uuid4().hex[:6]}"
            self.slug = slug
        super().save(*args, **kwargs)


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspace_memberships"
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("workspace", "user")
        ordering = ["joined_at"]

    def __str__(self):
        return f"{self.user} @ {self.workspace} ({self.role})"


class InvitationQuerySet(models.QuerySet):
    def valid(self):
        """Invitations that can still be accepted: recent, and from someone who is *still* an admin or the
        owner of that workspace (an admin who was removed or demoted takes their open offers with them)."""
        inviter_can_invite = Membership.objects.filter(
            workspace=OuterRef("workspace"),
            user=OuterRef("invited_by"),
            role__in=[Membership.Role.OWNER, Membership.Role.ADMIN],
        )
        return self.filter(Exists(inviter_can_invite), created_at__gte=timezone.now() - INVITATION_TTL)


class Invitation(models.Model):
    """An admin's offer to join a workspace. Nobody becomes a member (and sees the workspace) until they
    accept it themselves; declining or an admin revoking it just deletes it."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="invitations")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspace_invitations"
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_workspace_invitations"
    )
    role = models.CharField(max_length=10, choices=Membership.Role.choices, default=Membership.Role.MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = InvitationQuerySet.as_manager()

    class Meta:
        unique_together = ("workspace", "user")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} invited to {self.workspace}"
