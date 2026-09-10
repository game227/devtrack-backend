from rest_framework.permissions import BasePermission

from apps.workspaces.permissions import get_membership
from apps.workspaces.models import Membership


class IsProjectWorkspaceMember(BasePermission):
    """Object-level check: request.user is a member of the project's workspace."""

    def has_object_permission(self, request, view, obj):
        workspace = obj.workspace if hasattr(obj, "workspace") else obj
        return get_membership(request.user, workspace) is not None


class CanManageProject(BasePermission):
    """Object-level check: request.user is the project's owner, or a workspace admin/owner."""

    def has_object_permission(self, request, view, obj):
        project = obj
        if project.owner_id == request.user.id:
            return True
        membership = get_membership(request.user, project.workspace)
        return membership is not None and membership.role in (
            Membership.Role.OWNER,
            Membership.Role.ADMIN,
        )
