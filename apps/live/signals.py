"""Which saves and deletes count as a change to which part of a workspace."""

from django.db.models.signals import m2m_changed, post_delete, post_save

from apps.comments.models import Comment
from apps.cycles.models import Cycle
from apps.integrations.models import GitHubCommit, GitHubPullRequest
from apps.issues.models import Issue
from apps.milestones.models import Milestone
from apps.projects.models import Label, Note, Project, ProjectMember
from apps.teams.models import Team, TeamMembership
from apps.workspaces.models import Invitation, Membership, Workspace

from .models import touch


def _workspace_of_comment(comment):
    target = comment.content_object
    if target is None:
        return None
    return target.project.workspace_id if hasattr(target, "project") else getattr(target, "workspace_id", None)


# model -> (area, how to find the workspace id from an instance)
WATCHED = {
    Issue: ("issues", lambda i: i.project.workspace_id),
    Comment: ("issues", _workspace_of_comment),
    GitHubCommit: ("issues", lambda c: c.repo_link.project.workspace_id),
    GitHubPullRequest: ("issues", lambda p: p.repo_link.project.workspace_id),
    Project: ("projects", lambda p: p.workspace_id),
    ProjectMember: ("projects", lambda m: m.project.workspace_id),
    Note: ("projects", lambda n: n.project.workspace_id),
    Label: ("projects", lambda lb: lb.workspace_id),
    Cycle: ("projects", lambda c: c.project.workspace_id),
    Milestone: ("projects", lambda m: m.project.workspace_id),
    Team: ("projects", lambda t: t.workspace_id),
    TeamMembership: ("projects", lambda m: m.team.workspace_id),
    Membership: ("members", lambda m: m.workspace_id),
    Invitation: ("members", lambda i: i.workspace_id),
    Workspace: ("members", lambda w: w.pk),
}


def _mark(sender, instance, **kwargs):
    if kwargs.get("signal") is post_delete and isinstance(kwargs.get("origin"), Workspace):
        # The whole workspace is being deleted: its clock goes with it, and marking it from inside the
        # cascade would recreate a clock row for a workspace that is about to disappear.
        return
    area, workspace_of = WATCHED[sender]
    try:
        workspace_id = workspace_of(instance)
    except Exception:  # noqa: BLE001 — a parent already deleted in a cascade: nothing left to refresh
        return
    touch(workspace_id, area)


for model in WATCHED:
    post_save.connect(_mark, sender=model, dispatch_uid=f"live-save-{model.__name__}")
    post_delete.connect(_mark, sender=model, dispatch_uid=f"live-delete-{model.__name__}")


def _labels_changed(sender, instance, action, **kwargs):
    if action in ("post_add", "post_remove", "post_clear"):
        touch(instance.project.workspace_id, "issues")


m2m_changed.connect(_labels_changed, sender=Issue.labels.through, dispatch_uid="live-issue-labels")
