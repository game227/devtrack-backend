from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.activities.models import Activity
from apps.activities.serializers import ActivitySerializer
from apps.cycles.models import Cycle
from apps.issues.models import Issue
from apps.projects.models import Label, Project
from apps.workspaces.models import Membership, Workspace
from apps.workspaces.permissions import get_membership

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


STALE_IN_PROGRESS_DAYS = 7
ACTIVITY_DECAY_DAYS = 14


class ProjectHealthView(APIView):
    """Rule-based project health score — no AI, per spec §22."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        if get_membership(request.user, project.workspace) is None:
            raise PermissionDenied("You are not a member of this project's workspace.")

        today = timezone.localdate()
        issues = Issue.objects.filter(project=project)
        total = issues.count()
        done = issues.filter(status=DONE_STATUS).count()

        task_progress = round(done / total * 100) if total else 100

        with_deadline = issues.exclude(due_date__isnull=True)
        overdue_issues = with_deadline.exclude(status=DONE_STATUS).filter(due_date__lt=today)
        deadline_health = (
            round((with_deadline.count() - overdue_issues.count()) / with_deadline.count() * 100)
            if with_deadline.exists()
            else 100
        )

        open_bugs = issues.filter(type=Issue.Type.BUG).exclude(status=DONE_STATUS)
        bug_rate_health = round(100 - open_bugs.count() / total * 100) if total else 100

        last_activity = Activity.objects.filter(workspace=project.workspace).order_by("-created_at").first()
        reference_date = last_activity.created_at.date() if last_activity else project.created_at.date()
        days_stale = (today - reference_date).days
        activity_health = max(0, min(100, round(100 - days_stale * (100 / ACTIVITY_DECAY_DAYS))))

        overall = round((task_progress + deadline_health + bug_rate_health + activity_health) / 4)
        if overall >= 80:
            status_label = "healthy"
        elif overall >= 50:
            status_label = "needs_attention"
        else:
            status_label = "at_risk"

        risks = []
        stale_cutoff = today - timedelta(days=STALE_IN_PROGRESS_DAYS)
        stale_in_progress = issues.filter(status=Issue.Status.IN_PROGRESS, updated_at__date__lt=stale_cutoff)
        if stale_in_progress.exists():
            risks.append(
                f"{stale_in_progress.count()} task(s) have been in progress for more than "
                f"{STALE_IN_PROGRESS_DAYS} days."
            )
        if overdue_issues.exists():
            risks.append(f"{overdue_issues.count()} issue(s) are past their due date.")
        urgent_bugs = open_bugs.filter(priority__in=[Issue.Priority.HIGH, Issue.Priority.URGENT])
        if urgent_bugs.exists():
            risks.append(f"{urgent_bugs.count()} unresolved high/urgent priority bug(s).")

        return Response(
            {
                "score": overall,
                "status": status_label,
                "factors": {
                    "task_progress": task_progress,
                    "development_activity": activity_health,
                    "deadline": deadline_health,
                    "bug_rate": bug_rate_health,
                },
                "risks": risks,
            }
        )
