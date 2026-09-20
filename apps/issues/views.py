from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.projects.models import Project
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import get_membership

from .filters import IssueFilter
from .models import Issue
from .permissions import CanDeleteIssue, IsIssueWorkspaceMember
from .serializers import IssueSerializer


class IssueListCreateView(generics.ListCreateAPIView):
    serializer_class = IssueSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_class = IssueFilter

    def get_queryset(self):
        project_id = self.request.query_params.get("project")
        workspace_id = self.request.query_params.get("workspace")
        base = Issue.objects.select_related("assignee", "reporter").prefetch_related("labels")

        if project_id:
            project = get_object_or_404(Project, pk=project_id)
            if get_membership(self.request.user, project.workspace) is None:
                raise PermissionDenied("You are not a member of this project's workspace.")
            return base.filter(project=project)

        if workspace_id:
            workspace = get_object_or_404(Workspace, pk=workspace_id)
            if get_membership(self.request.user, workspace) is None:
                raise PermissionDenied("You are not a member of this workspace.")
            return base.filter(project__workspace=workspace)

        raise ValidationError({"project": "Either 'project' or 'workspace' query parameter is required."})

    def perform_create(self, serializer):
        project = get_object_or_404(Project, pk=self.request.data.get("project"))
        if get_membership(self.request.user, project.workspace) is None:
            raise PermissionDenied("You are not a member of this project's workspace.")
        serializer.save(project=project, reporter=self.request.user)


class IssueDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Issue.objects.select_related("assignee", "reporter", "project").prefetch_related("labels")
    serializer_class = IssueSerializer

    def perform_update(self, serializer):
        # Lets the activity/notification signals attribute the change to whoever
        # made it rather than to the issue's original reporter.
        serializer.instance._actor = self.request.user
        serializer.save()

    def get_permissions(self):
        if self.request.method == "DELETE":
            return [IsAuthenticated(), CanDeleteIssue()]
        return [IsAuthenticated(), IsIssueWorkspaceMember()]
