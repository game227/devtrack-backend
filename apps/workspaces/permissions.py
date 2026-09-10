from rest_framework.permissions import BasePermission

from .models import Membership


def get_membership(user, workspace):
    return Membership.objects.filter(workspace=workspace, user=user).first()


class IsWorkspaceMember(BasePermission):
    """Object-level check: request.user has any Membership in the target workspace."""

    def has_object_permission(self, request, view, obj):
        workspace = obj if hasattr(obj, "memberships") else obj.workspace
        return get_membership(request.user, workspace) is not None


class IsWorkspaceAdminOrOwner(BasePermission):
    """Object-level check: request.user's role in the target workspace is owner/admin."""

    def has_object_permission(self, request, view, obj):
        workspace = obj if hasattr(obj, "memberships") else obj.workspace
        membership = get_membership(request.user, workspace)
        return membership is not None and membership.role in (
            Membership.Role.OWNER,
            Membership.Role.ADMIN,
        )


class IsWorkspaceOwner(BasePermission):
    """Object-level check: request.user's role in the target workspace is owner."""

    def has_object_permission(self, request, view, obj):
        workspace = obj if hasattr(obj, "memberships") else obj.workspace
        membership = get_membership(request.user, workspace)
        return membership is not None and membership.role == Membership.Role.OWNER
