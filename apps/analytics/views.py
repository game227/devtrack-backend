import datetime as dt
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.activities.models import Activity
from apps.activities.queries import project_timeline_queryset
from apps.activities.serializers import ActivitySerializer
from apps.cycles.models import Cycle
from apps.issues.models import Issue
from apps.projects.models import Label, Project
from apps.workspaces.models import Membership, Workspace
from apps.workspaces.permissions import get_membership

from .health import compute_project_health

User = get_user_model()
DONE_STATUS = Issue.Status.DONE
DEADLINE_WINDOW_DAYS = 30
SEARCH_LIMIT = 10


class DashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        workspace_id = request.query_params.get("workspace")
        if not workspace_id:
            raise ValidationError({"workspace": "This query parameter is required."})
        workspace = get_object_or_404(Workspace, pk=workspace_id)
        if get_membership(request.user, workspace) is None:
            raise PermissionDenied("You are not a member of this workspace.")

        projects = Project.objects.filter(workspace=workspace)
        project_status_counts = dict(
            projects.values("status").annotate(count=Count("id")).values_list("status", "count")
        )
        projects_summary = {
            "total": projects.count(),
            "active": project_status_counts.get(Project.Status.ACTIVE, 0),
            "planned": project_status_counts.get(Project.Status.PLANNED, 0),
            "paused": project_status_counts.get(Project.Status.PAUSED, 0),
            "completed": project_status_counts.get(Project.Status.COMPLETED, 0),
            "archived": project_status_counts.get(Project.Status.ARCHIVED, 0),
        }

        issues = Issue.objects.filter(project__workspace=workspace)
        issues_total = issues.count()
        issues_done = issues.filter(status=DONE_STATUS).count()
        issues_summary = {
            "total": issues_total,
            "open": issues_total - issues_done,
            "done": issues_done,
        }

        today = timezone.localdate()
        upcoming = (
            issues.exclude(status=DONE_STATUS)
            .filter(due_date__isnull=False, due_date__lte=today + timedelta(days=DEADLINE_WINDOW_DAYS))
            .select_related("project")
            .order_by("due_date")[:10]
        )
        upcoming_deadlines = [
            {
                "id": issue.id,
                "title": issue.title,
                "project": {"id": issue.project_id, "name": issue.project.name},
                "due_date": issue.due_date,
                "is_overdue": issue.due_date < today,
            }
            for issue in upcoming
        ]

        project_progress = []
        for project in projects.annotate(
            issue_count=Count("issues"),
            done_count=Count("issues", filter=Q(issues__status=DONE_STATUS)),
        ):
            progress = (
                round(project.done_count / project.issue_count * 100)
                if project.issue_count
                else 0
            )
            project_progress.append(
                {
                    "id": project.id,
                    "name": project.name,
                    "status": project.status,
                    "progress_percent": progress,
                }
            )

        recent_activity = (
            Activity.objects.filter(workspace=workspace)
            .select_related("actor", "content_type")[:10]
        )

        return Response(
            {
                "workspace": {"id": workspace.id, "name": workspace.name},
                "projects": projects_summary,
                "issues": issues_summary,
                "upcoming_deadlines": upcoming_deadlines,
                "project_progress": project_progress,
                "recent_activity": ActivitySerializer(recent_activity, many=True).data,
            }
        )


class SearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.query_params.get("q", "").strip()
        workspace_id = request.query_params.get("workspace")
        if not workspace_id:
            raise ValidationError({"workspace": "This query parameter is required."})
        if not query:
            raise ValidationError({"q": "This query parameter is required."})

        workspace = get_object_or_404(Workspace, pk=workspace_id)
        if get_membership(request.user, workspace) is None:
            raise PermissionDenied("You are not a member of this workspace.")

        projects = Project.objects.filter(workspace=workspace, name__icontains=query)[:SEARCH_LIMIT]
        issues = Issue.objects.filter(project__workspace=workspace, title__icontains=query)[:SEARCH_LIMIT]
        member_user_ids = Membership.objects.filter(workspace=workspace).values_list("user_id", flat=True)
        users = User.objects.filter(id__in=member_user_ids, username__icontains=query)[:SEARCH_LIMIT]
        labels = Label.objects.filter(workspace=workspace, name__icontains=query)[:SEARCH_LIMIT]
        cycles = Cycle.objects.filter(project__workspace=workspace, name__icontains=query)[:SEARCH_LIMIT]

        return Response(
            {
                "projects": [{"id": p.id, "name": p.name, "status": p.status} for p in projects],
                "issues": [
                    {"id": i.id, "title": i.title, "type": i.type, "status": i.status} for i in issues
                ],
                "users": [{"id": u.id, "username": u.username, "avatar": _avatar_url(u)} for u in users],
                "labels": [{"id": l.id, "name": l.name, "color": l.color} for l in labels],
                "cycles": [{"id": c.id, "name": c.name, "project": c.project_id} for c in cycles],
            }
        )


def _avatar_url(user):
    return user.avatar.url if user.avatar else None


class ProjectHealthView(APIView):
    """Rule-based project health score — no AI, per spec §22. The formula lives in health.py."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        if get_membership(request.user, project.workspace) is None:
            raise PermissionDenied("You are not a member of this project's workspace.")
        return Response(compute_project_health(project))


DEVELOPER_ACTIVITY_DAYS = 14


class DeveloperAnalyticsView(APIView):
    """Per spec §23 — scoped to one workspace both requester and target share."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        target_user = get_object_or_404(User, pk=pk)
        workspace_id = request.query_params.get("workspace")
        if not workspace_id:
            raise ValidationError({"workspace": "This query parameter is required."})
        workspace = get_object_or_404(Workspace, pk=workspace_id)

        if get_membership(request.user, workspace) is None:
            raise PermissionDenied("You are not a member of this workspace.")
        if get_membership(target_user, workspace) is None:
            raise PermissionDenied("That user is not a member of this workspace.")

        issues_in_workspace = Issue.objects.filter(project__workspace=workspace)
        projects_count = Project.objects.filter(
            Q(workspace=workspace) & (Q(owner=target_user) | Q(members__user=target_user))
        ).distinct().count()
        tasks_completed = issues_in_workspace.filter(assignee=target_user, status=DONE_STATUS).count()
        issues_resolved = issues_in_workspace.filter(reporter=target_user, status=DONE_STATUS).count()
        open_assigned = issues_in_workspace.filter(assignee=target_user).exclude(status=DONE_STATUS).count()

        # The last DEVELOPER_ACTIVITY_DAYS whole days (today included), every one of them present —
        # a quiet day is a 0, not a gap the chart has to guess about.
        today = timezone.localdate()
        first_day = today - timedelta(days=DEVELOPER_ACTIVITY_DAYS - 1)
        since = timezone.make_aware(dt.datetime.combine(first_day, dt.time.min))
        counts = {
            row["day"]: row["count"]
            for row in Activity.objects.filter(workspace=workspace, actor=target_user, created_at__gte=since)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(count=Count("id"))
        }
        daily_activity = [
            {"date": day, "count": counts.get(day, 0)}
            for day in (first_day + timedelta(days=offset) for offset in range(DEVELOPER_ACTIVITY_DAYS))
        ]

        return Response(
            {
                "user": {"id": target_user.id, "username": target_user.username, "avatar": _avatar_url(target_user)},
                "workspace": {"id": workspace.id, "name": workspace.name},
                "projects_count": projects_count,
                "tasks_completed": tasks_completed,
                "issues_resolved": issues_resolved,
                "open_assigned": open_assigned,
                "daily_activity": daily_activity,
            }
        )
