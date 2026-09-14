from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.comments.models import Comment
from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import get_membership

from .models import Activity
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
            return self._project_timeline_queryset(project)

        if workspace_id:
            workspace = get_object_or_404(Workspace, pk=workspace_id)
            if get_membership(self.request.user, workspace) is None:
                raise PermissionDenied("You are not a member of this workspace.")
            return Activity.objects.filter(workspace=workspace).select_related("actor", "content_type")

        raise ValidationError({"workspace": "Either 'workspace' or 'project' query parameter is required."})

    @staticmethod
    def _project_timeline_queryset(project):
        # Activity only has a workspace FK, not a project one — a project's
        # timeline is every Activity whose target is the project itself, one
        # of its issues, or a comment on either of those.
        project_ct = ContentType.objects.get_for_model(Project)
        issue_ct = ContentType.objects.get_for_model(Issue)
        comment_ct = ContentType.objects.get_for_model(Comment)
        issue_ids = list(Issue.objects.filter(project=project).values_list("id", flat=True))
        comment_ids = list(
            Comment.objects.filter(
                Q(content_type=issue_ct, object_id__in=issue_ids)
                | Q(content_type=project_ct, object_id=project.id)
            ).values_list("id", flat=True)
        )
        return Activity.objects.filter(
            Q(content_type=project_ct, object_id=project.id)
            | Q(content_type=issue_ct, object_id__in=issue_ids)
            | Q(content_type=comment_ct, object_id__in=comment_ids)
        ).select_related("actor", "content_type")
