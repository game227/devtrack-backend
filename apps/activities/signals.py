from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.comments.models import Comment
from apps.issues.models import Issue
from apps.projects.models import Project

from .models import Activity


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


@receiver(pre_save, sender=Issue)
def stash_previous_issue_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_status = None
        return
    previous = Issue.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    instance._previous_status = previous


@receiver(post_save, sender=Issue)
def log_issue_created_or_moved(sender, instance, created, **kwargs):
    workspace = instance.project.workspace
    if created:
        Activity.objects.create(
            workspace=workspace,
            actor=instance.reporter,
            verb="created_issue",
            target=instance,
        )
        return

    previous_status = getattr(instance, "_previous_status", None)
    if previous_status is not None and previous_status != instance.status:
        Activity.objects.create(
            workspace=workspace,
            actor=instance.reporter,
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
