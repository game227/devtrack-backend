from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.projects.models import Project
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
        if not project_id:
            raise ValidationError({"project": "This query parameter is required."})
        project = get_object_or_404(Project, pk=project_id)
        if get_membership(self.request.user, project.workspace) is None:
            raise PermissionDenied("You are not a member of this project's workspace.")
        return (
            Issue.objects.filter(project=project)
            .select_related("assignee", "reporter")
            .prefetch_related("labels")
        )

    def perform_create(self, serializer):
        project = get_object_or_404(Project, pk=self.request.data.get("project"))
        if get_membership(self.request.user, project.workspace) is None:
            raise PermissionDenied("You are not a member of this project's workspace.")
        serializer.save(project=project, reporter=self.request.user)


class IssueDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Issue.objects.select_related("assignee", "reporter", "project").prefetch_related("labels")
    serializer_class = IssueSerializer

    def get_permissions(self):
        if self.request.method == "DELETE":
            return [IsAuthenticated(), CanDeleteIssue()]
        return [IsAuthenticated(), IsIssueWorkspaceMember()]
