from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.comments.models import Comment
from apps.issues.models import Issue
from apps.projects.models import Project

from .models import Activity


def _actor_for(issue):
    """Whoever caused the change: the request user when the view supplied one
    (``issue._actor``), the reporter otherwise (shell, seeding, fixtures)."""
    return getattr(issue, "_actor", None) or issue.reporter


def _comment_target_workspace(comment):
    target = comment.content_object
    return target.project.workspace if hasattr(target, "project") else target.workspace


@receiver(post_save, sender=Project)
def log_project_created(sender, instance, created, **kwargs):
    if not created:
        return
    Activity.objects.create(
        workspace=instance.workspace,
        actor=instance.owner,
        verb="created_project",
        target=instance,
    )


# Fields whose changes show in an issue's history (status has its own "moved" entry).
TRACKED_FIELDS = ("title", "priority", "type", "assignee_id", "due_date", "estimate", "cycle_id", "milestone_id")


@receiver(pre_save, sender=Issue)
def stash_previous_issue_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_status = None
        instance._previous_fields = None
        return
    previous = Issue.objects.filter(pk=instance.pk).values("status", *TRACKED_FIELDS).first()
    instance._previous_status = previous["status"] if previous else None
    instance._previous_fields = previous


def _readable(field, value):
    """A value as people read it: usernames and names instead of ids, ISO dates as text."""
    if value is None or value == "":
        return None
    if field == "assignee_id":
        from django.contrib.auth import get_user_model

        return get_user_model().objects.filter(pk=value).values_list("username", flat=True).first()
    if field == "cycle_id":
        from apps.cycles.models import Cycle

        return Cycle.objects.filter(pk=value).values_list("name", flat=True).first()
    if field == "milestone_id":
        from apps.milestones.models import Milestone

        return Milestone.objects.filter(pk=value).values_list("name", flat=True).first()
    return str(value)


def _log_field_changes(instance, workspace):
    previous = getattr(instance, "_previous_fields", None)
    if not previous:
        return
    changes = []
    for field in TRACKED_FIELDS:
        before, after = previous.get(field), getattr(instance, field)
        if before != after:
            changes.append({"field": field.removesuffix("_id"), "from": _readable(field, before), "to": _readable(field, after)})
    if changes:
        Activity.objects.create(
            workspace=workspace, actor=_actor_for(instance), verb="changed_issue", target=instance, metadata={"changes": changes}
        )


@receiver(post_save, sender=Issue)
def log_issue_created_or_moved(sender, instance, created, **kwargs):
    workspace = instance.project.workspace
    if created:
        Activity.objects.create(
            workspace=workspace,
            actor=_actor_for(instance),
            verb="created_issue",
            target=instance,
        )
        return

    _log_field_changes(instance, workspace)

    # Callers that log their own richer activity for the transition (e.g. the
    # GitHub PR-merge handler's ``pr_merged``) opt out to avoid a duplicate entry.
    if getattr(instance, "_skip_move_activity", False):
        return

    previous_status = getattr(instance, "_previous_status", None)
    if previous_status is not None and previous_status != instance.status:
        Activity.objects.create(
            workspace=workspace,
            actor=_actor_for(instance),
            verb="moved_issue",
            target=instance,
            metadata={"from": previous_status, "to": instance.status},
        )


@receiver(post_save, sender=Comment)
def log_comment_created(sender, instance, created, **kwargs):
    if not created:
        return
    Activity.objects.create(
        workspace=_comment_target_workspace(instance),
        actor=instance.author,
        verb="commented",
        target=instance,
    )
