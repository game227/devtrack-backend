from datetime import timedelta

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.lookup import body_value, parse_id
from apps.issues.models import Issue
from apps.notifications.models import Notification
from apps.workspaces.models import Invitation, Membership, Workspace
from apps.workspaces.permissions import get_membership
from apps.workspaces.serializers import UserBriefSerializer

from . import presence, stream
from .models import AREAS, WorkspaceClock

# A change committed just after a check, but stamped just before it, would otherwise slip between two
# checks; looking back a little re-reports such a change once rather than missing it.
OVERLAP = timedelta(seconds=3)


def changes_since(user, workspace, since):
    """The areas of `workspace` (and of `user`'s own inbox) that changed after `since`."""
    window = since - OVERLAP
    changed = []
    clock = WorkspaceClock.objects.filter(workspace=workspace).first()
    if clock is not None:
        changed += [area for area in AREAS if (getattr(clock, f"{area}_at") or window) > window]
    if Notification.objects.filter(recipient=user, created_at__gt=window).exists():
        changed.append("notifications")
    if Invitation.objects.filter(user=user, created_at__gt=window).exists():
        changed.append("invitations")
    return changed


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

        changed = changes_since(request.user, workspace, since)
        return Response({"cursor": now.isoformat(), "changed": changed})


class StreamTicketView(APIView):
    """POST {workspace} -> a single-use ticket that opens the event stream for 60 seconds.

    EventSource cannot send an Authorization header, and a JWT in a URL would end up in logs; the
    ticket is short-lived, single-use and good for one workspace only.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        workspace = get_object_or_404(Workspace, pk=parse_id(body_value(request, "workspace"), "workspace"))
        if get_membership(request.user, workspace) is None:
            raise PermissionDenied("You are not a member of this workspace.")
        return Response({"ticket": stream.issue_ticket(request.user.pk, workspace.pk), "expires_in": stream.TICKET_SECONDS})


class PresenceView(APIView):
    """POST {issue} every ~20 s while the issue is open -> who else has it open right now."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        issue = get_object_or_404(Issue.objects.select_related("project__workspace"), pk=parse_id(body_value(request, "issue"), "issue"))
        if get_membership(request.user, issue.project.workspace) is None:
            raise NotFound()
        viewer_ids = presence.beat(issue.pk, request.user.pk)
        members = set(Membership.objects.filter(workspace=issue.project.workspace, user_id__in=viewer_ids).values_list("user_id", flat=True))
        viewers = get_user_model().objects.filter(pk__in=members).order_by("username")
        return Response({"viewers": UserBriefSerializer(viewers, many=True, context={"request": request}).data})
