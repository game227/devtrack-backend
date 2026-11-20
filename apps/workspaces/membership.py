"""Changes to who belongs to a workspace, and the bookkeeping each one needs.

Who may do what (enforced by the views):

    action                         owner    admin             member
    invite                         yes      as member only    no
    withdraw a pending invitation  yes      yes               no
    change someone's role          yes      no                no
    remove someone                 yes      members only      no
    leave                          no*      yes               yes
    transfer ownership             yes      no                no

    * the owner hands the workspace over first.
"""

from django.db import transaction
from django.utils import timezone

from apps.activities.models import Activity
from apps.issues.models import Issue
from apps.live.models import touch
from apps.projects.models import ProjectMember
from apps.teams.models import TeamMembership

from .models import Membership


def record(workspace, actor, verb, user, **extra):
    """An entry in the workspace's activity feed about a member (the target is the workspace)."""
    Activity.objects.create(
        workspace=workspace, actor=actor, verb=verb, target=workspace, metadata={"user": user.username, **extra}
    )


def end_membership(membership, actor, verb):
    """Take someone out of a workspace, with everything that only made sense while they were in it:
    their project and team memberships there, and their open assignments (nobody outside the workspace
    can act on them, so they go back to the pool). Returns how many issues were unassigned."""
    workspace, user = membership.workspace, membership.user
    with transaction.atomic():
        ProjectMember.objects.filter(project__workspace=workspace, user=user).delete()
        TeamMembership.objects.filter(team__workspace=workspace, user=user).delete()
        unassigned = (
            Issue.objects.filter(project__workspace=workspace, assignee=user)
            .exclude(status=Issue.Status.DONE)
            .update(assignee=None, updated_at=timezone.now())
        )
        if unassigned:
            touch(workspace.id, "issues")  # a bulk update sends no signals
        membership.delete()
        record(workspace, actor, verb, user, unassigned=unassigned)
    return unassigned


def transfer_ownership(workspace, current_owner, new_owner_membership):
    with transaction.atomic():
        Membership.objects.filter(workspace=workspace, user=current_owner).update(role=Membership.Role.ADMIN)
        new_owner_membership.role = Membership.Role.OWNER
        new_owner_membership.save(update_fields=["role"])
        workspace.owner = new_owner_membership.user
        workspace.save(update_fields=["owner"])
        record(workspace, current_owner, "ownership_transferred", new_owner_membership.user)
