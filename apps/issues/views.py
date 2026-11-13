from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.common.filters import StableOrderingFilter
from apps.common.lookup import body_value, parse_id
from apps.projects.models import Project
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import get_membership

from .filters import IssueFilter
from .models import Issue
from .permissions import CanDeleteIssue, CanEditIssue, IsIssueWorkspaceMember
from .serializers import IssueSerializer


class IssueListCreateView(generics.ListCreateAPIView):
    serializer_class = IssueSerializer
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
