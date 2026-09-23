from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from apps.projects.models import Project
from apps.workspaces.models import Membership
from apps.workspaces.permissions import get_membership

from .models import Comment
from .serializers import CommentSerializer


def comment_target_workspace(target):
    """A commentable object is either an Issue (has .project) or a Project (has .workspace)."""
    return target.project.workspace if hasattr(target, "project") else target.workspace


class BaseCommentsView(generics.ListCreateAPIView):
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated]
    target_model = None

    def get_target(self):
        target = get_object_or_404(self.target_model, pk=self.kwargs["pk"])
        if get_membership(self.request.user, comment_target_workspace(target)) is None:
            raise PermissionDenied("You are not a member of this workspace.")
        return target

    def get_queryset(self):
        target = self.get_target()
        content_type = ContentType.objects.get_for_model(self.target_model)
        return Comment.objects.filter(content_type=content_type, object_id=target.pk).select_related(
            "author"
        )

    def perform_create(self, serializer):
        target = self.get_target()
        content_type = ContentType.objects.get_for_model(self.target_model)
        serializer.save(author=self.request.user, content_type=content_type, object_id=target.pk)


class IssueCommentsView(BaseCommentsView):
    @property
    def target_model(self):
        from apps.issues.models import Issue

        return Issue


class ProjectCommentsView(BaseCommentsView):
    target_model = Project


class CommentDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Comment.objects.select_related("author", "content_type")
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated]

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        # Reading a comment still requires workspace membership — without this, any
        # authenticated user could GET /comments/<id>/ for a comment in a workspace they
        # have no connection to at all, since the queryset above isn't scoped by workspace.
        membership = get_membership(request.user, comment_target_workspace(obj.content_object))
        if membership is None:
            raise PermissionDenied("You are not a member of this workspace.")
        if request.method in ("PUT", "PATCH", "DELETE"):
            if obj.author_id == request.user.id:
                return
            if membership.role not in (Membership.Role.OWNER, Membership.Role.ADMIN):
                raise PermissionDenied("Only the comment's author or a workspace admin/owner can do that.")
