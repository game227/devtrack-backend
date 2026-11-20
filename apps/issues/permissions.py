from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.workspaces.models import Membership
from apps.workspaces.permissions import get_membership

# What the person an issue is assigned to may change on someone else's issue: how the work is going,
# not what the work is. Everything else (title, description, assignee, labels, dates, ...) stays with
# whoever created the issue.
ASSIGNEE_EDITABLE_FIELDS = frozenset({"status", "priority"})


def _is_workspace_member(user, issue):
    return get_membership(user, issue.project.workspace) is not None


class IsIssueWorkspaceMember(BasePermission):
    """Object-level check: request.user belongs to the issue's project's workspace."""

    def has_object_permission(self, request, view, obj):
        return _is_workspace_member(request.user, obj)


class CanDeleteIssue(BasePermission):
    """Object-level check: a workspace member who is the reporter, or a workspace admin/owner.

    Membership is required first: someone removed from the workspace keeps no rights over what they
    created there.
    """

    def has_object_permission(self, request, view, obj):
        membership = get_membership(request.user, obj.project.workspace)
        if membership is None:
            return False
        if obj.reporter_id == request.user.id:
            return True
        return membership.role in (Membership.Role.OWNER, Membership.Role.ADMIN)


class CanEditIssue(BasePermission):
    """Object-level check for PUT/PATCH.

    * The reporter (the user who created the issue) may change anything.
    * The assignee may PATCH only ``status`` and ``priority``.
    * Nobody else may edit — a workspace admin/owner can remove a stuck issue (CanDeleteIssue) but
      cannot edit someone else's issue out from under them.

    All of it requires current workspace membership, so an ex-member loses access to what they created.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return _is_workspace_member(request.user, obj)
        if not _is_workspace_member(request.user, obj):
            return False
        if obj.reporter_id == request.user.id:
            return True
        if obj.assignee_id == request.user.id and request.method == "PATCH":
            data = request.data
            keys = set(data.keys()) if hasattr(data, "keys") else None
            return bool(keys) and keys <= ASSIGNEE_EDITABLE_FIELDS
        return False


class CanWorkOnIssue(BasePermission):
    """Checklist and links: anyone in the workspace reads them; the reporter and the assignee change them.

    Ticking off steps and noting what blocks the work is part of doing it, so unlike the issue's own
    fields the assignee has full control here.
    """

    def has_object_permission(self, request, view, obj):
        if not _is_workspace_member(request.user, obj):
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.id in (obj.reporter_id, obj.assignee_id)
