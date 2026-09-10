from rest_framework.permissions import BasePermission

from apps.workspaces.models import Membership
from apps.workspaces.permissions import get_membership


class IsIssueWorkspaceMember(BasePermission):
    """Object-level check: request.user belongs to the issue's project's workspace."""

    def has_object_permission(self, request, view, obj):
        return get_membership(request.user, obj.project.workspace) is not None


class CanDeleteIssue(BasePermission):
    """Object-level check: request.user is the reporter, or a workspace admin/owner."""

    def has_object_permission(self, request, view, obj):
        if obj.reporter_id == request.user.id:
            return True
        membership = get_membership(request.user, obj.project.workspace)
        return membership is not None and membership.role in (
            Membership.Role.OWNER,
            Membership.Role.ADMIN,
        )
