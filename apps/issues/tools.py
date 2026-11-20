"""Work tools around issues: share links, recurring issues, bulk changes and time tracking."""

import datetime as dt
import secrets

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.common.lookup import body_value, parse_id
from apps.live.models import touch
from apps.projects.models import Project
from apps.projects.permissions import CanManageProject
from apps.workspaces.models import Membership
from apps.workspaces.permissions import get_membership
from apps.workspaces.serializers import UserBriefSerializer

from .models import Issue, IssueShareLink, RecurringIssue, TimeEntry
from .permissions import ASSIGNEE_EDITABLE_FIELDS
from .serializers import IssueSerializer

SHARE_DAYS = (1, 7, 30)
MAX_BULK = 200


def _issue_for(request, pk):
    issue = get_object_or_404(Issue.objects.select_related("project__workspace"), pk=pk)
    membership = get_membership(request.user, issue.project.workspace)
    if membership is None:
        raise NotFound()
    return issue, membership


def _is_admin(membership):
    return membership.role in (Membership.Role.OWNER, Membership.Role.ADMIN)


# --- Share links -----------------------------------------------------------------------------------


class ShareLinkSerializer(serializers.ModelSerializer):
    created_by = UserBriefSerializer(read_only=True)
    live = serializers.SerializerMethodField()

    class Meta:
        model = IssueShareLink
        fields = ["id", "token", "expires_at", "revoked", "live", "created_by", "created_at"]

    def get_live(self, obj):
        return obj.is_live()


class ShareLinksView(APIView):
    """GET the issue's links; POST {days: 1|7|30} for a new one. The creator, assignee or an admin."""

    permission_classes = [IsAuthenticated]

    def _allowed(self, request, pk):
        issue, membership = _issue_for(request, pk)
        if request.user.id not in (issue.reporter_id, issue.assignee_id) and not _is_admin(membership):
            raise PermissionDenied("Only the issue's creator, its assignee or a workspace admin can share it.")
        return issue

    def get(self, request, pk):
        issue = self._allowed(request, pk)
        return Response(ShareLinkSerializer(issue.share_links.select_related("created_by"), many=True).data)

    def post(self, request, pk):
        issue = self._allowed(request, pk)
        days = body_value(request, "days")
        if days not in SHARE_DAYS:
            raise ValidationError({"days": f"Choose one of {', '.join(map(str, SHARE_DAYS))}."})
        link = IssueShareLink.objects.create(
            issue=issue,
            token=secrets.token_urlsafe(32),
            created_by=request.user,
            expires_at=timezone.now() + dt.timedelta(days=days),
        )
        return Response(ShareLinkSerializer(link).data, status=status.HTTP_201_CREATED)


class ShareLinkRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        link = get_object_or_404(IssueShareLink.objects.select_related("issue__project__workspace"), pk=pk)
        issue, membership = _issue_for(request, link.issue_id)
        if request.user.id not in (issue.reporter_id, issue.assignee_id, link.created_by_id) and not _is_admin(membership):
            raise PermissionDenied("You cannot revoke this link.")
        link.revoked = True
        link.save(update_fields=["revoked"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublicIssueThrottle(AnonRateThrottle):
    scope = "share_view"


class PublicIssueView(APIView):
    """GET a shared issue by its token: only what is safe to show outside the workspace."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [PublicIssueThrottle]

    def get(self, request, token):
        link = IssueShareLink.objects.select_related("issue__project", "issue__assignee").filter(token=token).first()
        if link is None or not link.is_live():
            raise NotFound("This link has expired or was revoked.")
        issue = link.issue
        items = list(issue.checklist_items.values("text", "done"))
        return Response(
            {
                "number": issue.number,
                "title": issue.title,
                "description": issue.description,
                "status": issue.status,
                "priority": issue.priority,
                "type": issue.type,
                "project": issue.project.name,
                "assignee": issue.assignee.username if issue.assignee else None,
                "due_date": issue.due_date,
                "checklist": items,
                "updated_at": issue.updated_at,
                "expires_at": link.expires_at,
            }
        )


# --- Recurring issues ------------------------------------------------------------------------------


class RecurringIssueSerializer(serializers.ModelSerializer):
    assignee = UserBriefSerializer(read_only=True)
    assignee_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = RecurringIssue
        fields = ["id", "title", "description", "type", "priority", "assignee", "assignee_id", "frequency", "next_run", "active", "created_at"]
        read_only_fields = ["created_at"]

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_next_run(self, value):
        if self.instance is None and value < timezone.localdate():
            raise serializers.ValidationError("The first date cannot be in the past.")
        return value

    def validate_assignee_id(self, value):
        if value is None:
            return None
        project = self.context["project"]
        if not Membership.objects.filter(workspace=project.workspace, user_id=value).exists():
            raise serializers.ValidationError("That user is not a member of this workspace.")
        return value

    def create(self, validated_data):
        validated_data["assignee_id"] = validated_data.pop("assignee_id", None)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if "assignee_id" in validated_data:
            instance.assignee_id = validated_data.pop("assignee_id")
        return super().update(instance, validated_data)


class ProjectChildMixin:
    permission_classes = [IsAuthenticated]

    def get_project(self):
        if not hasattr(self, "_project"):
            project = get_object_or_404(Project.objects.select_related("workspace"), pk=self.kwargs["project_pk"])
            if get_membership(self.request.user, project.workspace) is None:
                raise NotFound()
            if self.request.method not in ("GET", "HEAD", "OPTIONS") and not CanManageProject().has_object_permission(self.request, self, project):
                raise PermissionDenied("Only the project's owner or a workspace admin can change this.")
            self._project = project
        return self._project

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["project"] = self.get_project()
        return context


class RecurringListCreateView(ProjectChildMixin, generics.ListCreateAPIView):
    serializer_class = RecurringIssueSerializer
    pagination_class = None

    def get_queryset(self):
        return RecurringIssue.objects.filter(project=self.get_project()).select_related("assignee")

    def perform_create(self, serializer):
        serializer.save(project=self.get_project(), created_by=self.request.user)


class RecurringDetailView(ProjectChildMixin, generics.UpdateAPIView, generics.DestroyAPIView):
    serializer_class = RecurringIssueSerializer
    http_method_names = ["patch", "delete"]

    def get_object(self):
        rule = get_object_or_404(RecurringIssue.objects.select_related("project"), pk=self.kwargs["pk"])
        self.kwargs["project_pk"] = rule.project_id
        self.get_project()
        return rule


def run_recurring(today=None):
    """Open today's issues for every due rule; each rule then moves past today. Returns the count."""
    today = today or timezone.localdate()
    created = 0
    for rule in RecurringIssue.objects.filter(active=True, next_run__lte=today).select_related("project__workspace"):
        with transaction.atomic():
            workspace = rule.project.workspace
            if not Membership.objects.filter(workspace=workspace, user_id=rule.created_by_id).exists():
                # Its author left the workspace: stop rather than open issues in their name.
                rule.active = False
                rule.save(update_fields=["active"])
                continue
            assignee = rule.assignee if rule.assignee and Membership.objects.filter(workspace=workspace, user=rule.assignee).exists() else None
            Issue.objects.create(
                project=rule.project,
                title=rule.title,
                description=rule.description,
                type=rule.type,
                priority=rule.priority,
                assignee=assignee,
                reporter_id=rule.created_by_id,
            )
            created += 1
            while rule.next_run <= today:
                rule.next_run = rule.advance()
            rule.save(update_fields=["next_run"])
    return created


# --- Bulk changes ----------------------------------------------------------------------------------

BULK_FIELDS = {"status", "priority", "assignee_id", "cycle", "milestone"}


class BulkUpdateView(APIView):
    """POST {ids: [...], changes: {...}}: the same change on many issues, each checked like a single edit.

    The creator may change anything here, the assignee only status and priority, others nothing; issues
    the caller may not change are skipped and reported, not failed.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        ids = body_value(request, "ids")
        changes = body_value(request, "changes")
        if not isinstance(ids, list) or not ids or len(ids) > MAX_BULK:
            raise ValidationError({"ids": f"Send between 1 and {MAX_BULK} issue ids."})
        if not isinstance(changes, dict) or not changes or set(changes) - BULK_FIELDS:
            raise ValidationError({"changes": f"Allowed: {', '.join(sorted(BULK_FIELDS))}."})
        ids = [parse_id(value, "ids") for value in ids]
        updated, skipped = [], []
        issues = Issue.objects.filter(pk__in=ids).select_related("project__workspace")
        found = {issue.pk: issue for issue in issues}
        for issue_id in ids:
            issue = found.get(issue_id)
            if issue is None or get_membership(request.user, issue.project.workspace) is None:
                skipped.append({"id": issue_id, "reason": "not_found"})
                continue
            if issue.reporter_id != request.user.id and not (
                issue.assignee_id == request.user.id and set(changes) <= ASSIGNEE_EDITABLE_FIELDS
            ):
                skipped.append({"id": issue_id, "reason": "not_allowed"})
                continue
            serializer = IssueSerializer(issue, data=changes, partial=True, context={"request": request, "project": issue.project})
            if not serializer.is_valid():
                skipped.append({"id": issue_id, "reason": "invalid", "errors": serializer.errors})
                continue
            serializer.instance._actor = request.user
            serializer.save()
            updated.append(issue_id)
        return Response({"updated": updated, "skipped": skipped})


# --- Time tracking ---------------------------------------------------------------------------------


class TimeEntrySerializer(serializers.ModelSerializer):
    user = UserBriefSerializer(read_only=True)

    class Meta:
        model = TimeEntry
        fields = ["id", "user", "minutes", "note", "spent_on", "created_at"]
        read_only_fields = ["created_at"]

    def validate_minutes(self, value):
        if value < 1:
            raise serializers.ValidationError("Log at least one minute.")
        return value

    def validate_spent_on(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("Time cannot be logged for a future day.")
        return value


class TimeEntriesView(generics.ListCreateAPIView):
    """Time logged on an issue. Any workspace member logs their own time and sees everyone's."""

    serializer_class = TimeEntrySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        issue, _ = _issue_for(self.request, self.kwargs["pk"])
        return TimeEntry.objects.filter(issue=issue).select_related("user")

    def perform_create(self, serializer):
        issue, _ = _issue_for(self.request, self.kwargs["pk"])
        serializer.save(issue=issue, user=self.request.user)
        touch(issue.project.workspace_id, "issues")


class TimeEntryDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        entry = get_object_or_404(TimeEntry.objects.select_related("issue__project__workspace"), pk=pk)
        _issue_for(request, entry.issue_id)
        if entry.user_id != request.user.id:
            raise PermissionDenied("You can only remove your own time.")
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
