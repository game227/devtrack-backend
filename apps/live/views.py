from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.lookup import parse_id
from apps.notifications.models import Notification
from apps.workspaces.models import Invitation, Workspace
from apps.workspaces.permissions import get_membership

from .models import AREAS, WorkspaceClock

# A change committed just after a check, but stamped just before it, would otherwise slip between two
# checks; looking back a little re-reports such a change once rather than missing it.
OVERLAP = timedelta(seconds=3)


class ChangesView(APIView):
    """GET ?workspace=<id>&since=<cursor> -> {"cursor": ..., "changed": [areas]}.

    The first call (no `since`) only hands out a cursor: the client has just loaded everything. Areas:
    issues, projects, members (of the workspace), notifications and invitations (of the caller).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        workspace = get_object_or_404(Workspace, pk=parse_id(request.query_params.get("workspace"), "workspace"))
        if get_membership(request.user, workspace) is None:
            raise PermissionDenied("You are not a member of this workspace.")
        now = timezone.now()
        since = parse_datetime(request.query_params.get("since") or "")
        if since is None or timezone.is_naive(since):
            return Response({"cursor": now.isoformat(), "changed": []})

        window = since - OVERLAP
        changed = []
        clock = WorkspaceClock.objects.filter(workspace=workspace).first()
        if clock is not None:
            changed += [area for area in AREAS if (getattr(clock, f"{area}_at") or window) > window]
        if Notification.objects.filter(recipient=request.user, created_at__gt=window).exists():
            changed.append("notifications")
        if Invitation.objects.filter(user=request.user, created_at__gt=window).exists():
            changed.append("invitations")
        return Response({"cursor": now.isoformat(), "changed": changed})
