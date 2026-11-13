from django.db import models
from django.utils import timezone

AREAS = ("issues", "projects", "members")


class WorkspaceClock(models.Model):
    """When each part of a workspace last changed. Clients ask "what changed since my last look?" and
    refetch only that, instead of polling every list. No data is exposed here: a client still reads
    everything through the normal, permission-checked endpoints."""

    workspace = models.OneToOneField("workspaces.Workspace", on_delete=models.CASCADE, primary_key=True, related_name="clock")
    issues_at = models.DateTimeField(null=True, blank=True)
    projects_at = models.DateTimeField(null=True, blank=True)
    members_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"clock of workspace {self.workspace_id}"


def touch(workspace_id, area):
    """Mark `area` of a workspace as changed now (one UPDATE; the row is created on first use)."""
    if not workspace_id or area not in AREAS:
        return
    now = timezone.now()
    if not WorkspaceClock.objects.filter(workspace_id=workspace_id).update(**{f"{area}_at": now}):
        WorkspaceClock.objects.get_or_create(workspace_id=workspace_id, defaults={f"{area}_at": now})
