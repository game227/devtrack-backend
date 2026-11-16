from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle

from apps.common.filters import StableOrderingFilter
from apps.common.lookup import body_value, parse_id
from apps.projects.models import Project
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import get_membership

from .export import issues_csv_response
from .filters import IssueFilter
from .models import Issue, SavedView
from .permissions import CanDeleteIssue, CanEditIssue, IsIssueWorkspaceMember
from .serializers import IssueSerializer, SavedViewSerializer


class IssueScopeMixin:
    """The issues of one project (?project=) or of a whole workspace (?workspace=), for its members only.

    Shared by the issue list and the CSV export, so both answer exactly the same filters.
    """

    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, StableOrderingFilter]
    filterset_class = IssueFilter
    ordering_fields = ["completed_at", "created_at", "updated_at", "number", "due_date"]

    def get_queryset(self):
        project_id = self.request.query_params.get("project")
        workspace_id = self.request.query_params.get("workspace")
        base = Issue.objects.select_related("assignee", "reporter").prefetch_related("labels")

        if project_id:
            project = get_object_or_404(Project, pk=parse_id(project_id, "project"))
            if get_membership(self.request.user, project.workspace) is None:
                raise PermissionDenied("You are not a member of this project's workspace.")
            return base.filter(project=project)

        if workspace_id:
            workspace = get_object_or_404(Workspace, pk=parse_id(workspace_id, "workspace"))
            if get_membership(self.request.user, workspace) is None:
                raise PermissionDenied("You are not a member of this workspace.")
            return base.filter(project__workspace=workspace)

        raise ValidationError({"project": "Either 'project' or 'workspace' query parameter is required."})


class IssueListCreateView(IssueScopeMixin, generics.ListCreateAPIView):
    serializer_class = IssueSerializer

    def get_target_project(self):
        """The project a new issue goes into, resolved and authorized *before* the body is validated."""
        if not hasattr(self, "_target_project"):
            project = get_object_or_404(
                Project.objects.select_related("workspace"),
                pk=parse_id(body_value(self.request, "project"), "project"),
            )
            if get_membership(self.request.user, project.workspace) is None:
                raise PermissionDenied("You are not a member of this project's workspace.")
            self._target_project = project
        return self._target_project

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.method == "POST":
            context["project"] = self.get_target_project()
        return context

    def perform_create(self, serializer):
        serializer.save(project=self.get_target_project(), reporter=self.request.user)


class IssueDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Issue.objects.select_related("assignee", "reporter", "project__workspace").prefetch_related("labels")
    serializer_class = IssueSerializer

    def perform_update(self, serializer):
        # Lets the activity/notification signals attribute the change to whoever
        # made it rather than to the issue's original reporter.
        serializer.instance._actor = self.request.user
        serializer.save()

    def get_permissions(self):
        if self.request.method == "DELETE":
            return [IsAuthenticated(), CanDeleteIssue()]
        # Edits: the creator may change anything, the assignee only status and priority (see
        # CanEditIssue). Anyone in the workspace can still read the issue.
        if self.request.method in ("PUT", "PATCH"):
            return [IsAuthenticated(), CanEditIssue()]
        return [IsAuthenticated(), IsIssueWorkspaceMember()]


class IssueExportThrottle(UserRateThrottle):
    scope = "issue_export"


class IssueExportView(IssueScopeMixin, generics.GenericAPIView):
    """GET: the same issues the list would return (same filters), as a CSV file."""

    throttle_classes = [IssueExportThrottle]

    def get(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        if request.query_params.get("project"):
            project = Project.objects.get(pk=parse_id(request.query_params["project"], "project"))
            scope_name = slugify(project.name) or f"project-{project.pk}"
        else:
            workspace = Workspace.objects.get(pk=parse_id(request.query_params["workspace"], "workspace"))
            scope_name = slugify(workspace.name) or f"workspace-{workspace.pk}"
        filename = f"{scope_name[:40]}-issues-{timezone.localdate():%Y-%m-%d}.csv"
        response = issues_csv_response(queryset, request.query_params.get("lang", "en"), filename)
        response["Cache-Control"] = "no-store"
        return response


class SavedViewListCreateView(generics.ListCreateAPIView):
    """Your saved filter sets for one workspace's list (?workspace=) or one project's list (?project=)."""

    serializer_class = SavedViewSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def _scope(self):
        if self.request.method == "GET":
            project_id = self.request.query_params.get("project")
            workspace_id = self.request.query_params.get("workspace")
        else:
            project_id = body_value(self.request, "project")
            workspace_id = body_value(self.request, "workspace")
        if project_id not in (None, ""):
            project = get_object_or_404(Project.objects.select_related("workspace"), pk=parse_id(project_id, "project"))
            workspace = project.workspace
        else:
            if workspace_id in (None, ""):
                raise ValidationError({"workspace": "Either 'project' or 'workspace' is required."})
            project = None
            workspace = get_object_or_404(Workspace, pk=parse_id(workspace_id, "workspace"))
        if get_membership(self.request.user, workspace) is None:
            raise PermissionDenied("You are not a member of this workspace.")
        return workspace, project

    def get_queryset(self):
        workspace, project = self._scope()
        return SavedView.objects.filter(owner=self.request.user, workspace=workspace, project=project)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.method == "POST":
            context["workspace"], context["project"] = self._scope()
        return context

    def perform_create(self, serializer):
        workspace, project = serializer.context["workspace"], serializer.context["project"]
        serializer.save(owner=self.request.user, workspace=workspace, project=project)


class SavedViewDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Rename, change or delete one of your own saved views. Other people's do not exist for you."""

    serializer_class = SavedViewSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "delete"]

    def get_queryset(self):
        return SavedView.objects.filter(owner=self.request.user).select_related("workspace", "project")
