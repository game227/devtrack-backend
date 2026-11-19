from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.comments.models import Comment
from apps.common.lookup import parse_id
from apps.issues.models import Issue
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
        issue_id = self.request.query_params.get("issue")

        if issue_id:
            # One issue's history: what happened to it, and the comments on it.
            issue = get_object_or_404(Issue.objects.select_related("project__workspace"), pk=parse_id(issue_id, "issue"))
            if get_membership(self.request.user, issue.project.workspace) is None:
                raise PermissionDenied("You are not a member of this project's workspace.")
            issue_type = ContentType.objects.get_for_model(Issue)
            comment_ids = Comment.objects.filter(content_type=issue_type, object_id=issue.pk).values_list("pk", flat=True)
            return (
                Activity.objects.filter(
                    Q(content_type=issue_type, object_id=issue.pk)
                    | Q(content_type=ContentType.objects.get_for_model(Comment), object_id__in=list(comment_ids))
                )
                .select_related("actor", "content_type")
                .order_by("-created_at", "-id")
            )

        if project_id:
            project = get_object_or_404(Project, pk=parse_id(project_id, "project"))
            if get_membership(self.request.user, project.workspace) is None:
                raise PermissionDenied("You are not a member of this project's workspace.")
            return project_timeline_queryset(project).select_related("actor", "content_type")

        if workspace_id:
            workspace = get_object_or_404(Workspace, pk=parse_id(workspace_id, "workspace"))
            if get_membership(self.request.user, workspace) is None:
                raise PermissionDenied("You are not a member of this workspace.")
            return Activity.objects.filter(workspace=workspace).select_related("actor", "content_type")

        raise ValidationError({"workspace": "Either 'workspace' or 'project' query parameter is required."})
