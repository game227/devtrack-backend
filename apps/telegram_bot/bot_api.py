"""The API the Telegram bot service calls on a user's behalf.

Every view resolves to the linked DevTrack user (see BotServiceAuthentication) and applies the same
rules the web app does: workspace membership to see anything, and only an issue's creator may change
its status. The bot never gets more than the user themself could do.
"""

import datetime as dt

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status as http
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.health import compute_project_health
from apps.comments.models import Comment
from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace
from apps.workspaces.permissions import get_membership

from .bot_auth import BotServiceAuthentication

LIST_LIMIT = 10
DUE_SOON_DAYS = 3
PRIORITY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3, "none": 4}


class BotView(APIView):
    authentication_classes = [BotServiceAuthentication]
    permission_classes = [IsAuthenticated]


def _workspace_ids(user):
    return Membership.objects.filter(user=user).values_list("workspace_id", flat=True)


def _issue_brief(issue, today=None, viewer=None):
    today = today or timezone.localdate()
    return {
        # Whether `viewer` may change this issue (only its creator can) — lets the bot offer a
        # "Done" button only where it would work.
        "can_edit": viewer is not None and issue.reporter_id == viewer.id,
        "id": issue.id,
        "title": issue.title,
        "status": issue.status,
        "priority": issue.priority,
        "type": issue.type,
        "due_date": issue.due_date,
        "overdue": bool(issue.due_date and issue.status != Issue.Status.DONE and issue.due_date < today),
        "project": {"id": issue.project_id, "name": issue.project.name},
        "assignee": issue.assignee.username if issue.assignee_id else None,
        "path": f"/issues/{issue.id}",
    }


def _visible_issue(user, issue_id):
    """The issue if the user belongs to its workspace; 404 otherwise (never leak that it exists)."""
    issue = get_object_or_404(Issue.objects.select_related("project", "assignee"), pk=issue_id)
    if get_membership(user, issue.project.workspace) is None:
        raise PermissionDenied("You are not a member of this workspace.")
    return issue


def urgency_key(issue, today):
    """Overdue first, then due soon, then the rest; earliest due date, then priority, within a group."""
    if issue.due_date and issue.due_date < today:
        group = 0
    elif issue.due_date and (issue.due_date - today).days <= DUE_SOON_DAYS:
        group = 1
    else:
        group = 2
    return (group, issue.due_date or dt.date.max, PRIORITY_RANK.get(issue.priority, 4), issue.id)


class BotMeView(BotView):
    def get(self, request):
        workspaces = Workspace.objects.filter(pk__in=_workspace_ids(request.user)).order_by("name")
        return Response(
            {
                "id": request.user.id,
                "username": request.user.username,
                "workspaces": [{"id": w.id, "name": w.name} for w in workspaces],
            }
        )


class BotIssuesView(BotView):
    """GET ?scope=mine|overdue|soon — the user's open assigned issues, most urgent first."""

    SCOPES = ("mine", "overdue", "soon")

    def get(self, request):
        scope = request.query_params.get("scope", "mine")
        if scope not in self.SCOPES:
            raise ValidationError({"scope": f"Must be one of {', '.join(self.SCOPES)}."})
        today = timezone.localdate()
        issues = (
            Issue.objects.filter(assignee=request.user, project__workspace_id__in=_workspace_ids(request.user))
            .exclude(status=Issue.Status.DONE)
            .select_related("project", "assignee")
        )
        if scope == "overdue":
            issues = issues.filter(due_date__lt=today)
        elif scope == "soon":
            issues = issues.filter(due_date__lte=today + dt.timedelta(days=DUE_SOON_DAYS))
        ordered = sorted(issues, key=lambda issue: urgency_key(issue, today))
        return Response({"total": len(ordered), "issues": [_issue_brief(i, today, request.user) for i in ordered[:LIST_LIMIT]]})

    def post(self, request):
        """Create an issue (reporter = the user) in a project they can see."""
        title = str(request.data.get("title", "")).strip()
        if not title:
            raise ValidationError({"title": "This field is required."})
        if len(title) > 200:
            raise ValidationError({"title": "Ensure this field has no more than 200 characters."})
        try:
            project_id = int(request.data.get("project"))
        except (TypeError, ValueError):
            raise ValidationError({"project": "A project id is required."})
        project = get_object_or_404(Project.objects.select_related("workspace"), pk=project_id)
        if get_membership(request.user, project.workspace) is None:
            raise PermissionDenied("You are not a member of this workspace.")
        issue = Issue(project=project, title=title, reporter=request.user)
        issue._actor = request.user
        issue.save()
        return Response(_issue_brief(issue, viewer=request.user), status=http.HTTP_201_CREATED)


class BotProjectsView(BotView):
    def get(self, request):
        projects = (
            Project.objects.filter(workspace_id__in=_workspace_ids(request.user))
            .exclude(status=Project.Status.ARCHIVED)
            .order_by("workspace__name", "name")
        )
        rows = []
        for project in projects:
            issues = Issue.objects.filter(project=project)
            total = issues.count()
            done = issues.filter(status=Issue.Status.DONE).count()
            rows.append(
                {
                    "id": project.id,
                    "name": project.name,
                    "status": project.status,
                    "open": total - done,
                    "done": done,
                    "progress": round(done / total * 100) if total else 0,
                }
            )
        return Response({"projects": rows})


class BotProjectHealthView(BotView):
    def get(self, request, pk):
        project = get_object_or_404(Project.objects.select_related("workspace"), pk=pk)
        if get_membership(request.user, project.workspace) is None:
            raise PermissionDenied("You are not a member of this workspace.")
        return Response({"project": {"id": project.id, "name": project.name}, **compute_project_health(project)})


class BotIssueDetailView(BotView):
    def get(self, request, pk):
        issue = _visible_issue(request.user, pk)
        return Response({**_issue_brief(issue, viewer=request.user), "description": issue.description[:400]})


class BotIssueStatusView(BotView):
    def post(self, request, pk):
        issue = _visible_issue(request.user, pk)
        new_status = request.data.get("status")
        if new_status not in Issue.Status.values:
            raise ValidationError({"status": f"Must be one of {', '.join(Issue.Status.values)}."})
        # Same rule as the web app: only the person who created an issue changes it.
        if issue.reporter_id != request.user.id:
            raise PermissionDenied("Only the person who created this issue can edit it.")
        issue._actor = request.user
        issue.status = new_status
        issue.save(update_fields=["status", "updated_at"])
        return Response(_issue_brief(issue, viewer=request.user))


class BotIssueCommentView(BotView):
    def post(self, request, pk):
        issue = _visible_issue(request.user, pk)
        body = str(request.data.get("body", "")).strip()
        if not body:
            raise ValidationError({"body": "This field is required."})
        Comment.objects.create(author=request.user, body=body[:2000], content_object=issue)
        return Response(_issue_brief(issue, viewer=request.user), status=http.HTTP_201_CREATED)
