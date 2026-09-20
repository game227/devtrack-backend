from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.projects.models import Project
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import get_membership

from .models import Activity
from .queries import project_timeline_queryset
from .serializers import ActivitySerializer


class ActivityListView(generics.ListAPIView):
    serializer_class = ActivitySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        project_id = self.request.query_params.get("project")
        workspace_id = self.request.query_params.get("workspace")

        if project_id:
            project = get_object_or_404(Project, pk=project_id)
            if get_membership(self.request.user, project.workspace) is None:
                raise PermissionDenied("You are not a member of this project's workspace.")
            return project_timeline_queryset(project).select_related("actor", "content_type")

        if workspace_id:
            workspace = get_object_or_404(Workspace, pk=workspace_id)
            if get_membership(self.request.user, workspace) is None:
                raise PermissionDenied("You are not a member of this workspace.")
            return Activity.objects.filter(workspace=workspace).select_related("actor", "content_type")

        raise ValidationError({"workspace": "Either 'workspace' or 'project' query parameter is required."})
