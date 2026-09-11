from datetime import timedelta

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.activities.models import Activity
from apps.activities.serializers import ActivitySerializer
from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import get_membership

DONE_STATUS = Issue.Status.DONE
DEADLINE_WINDOW_DAYS = 30


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
