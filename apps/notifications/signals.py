import re

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.comments.models import Comment
from apps.issues.models import Issue
from apps.projects.models import ProjectMember
from apps.workspaces.models import Membership

from apps.telegram_bot.notify import push_notification

from .models import Notification

User = get_user_model()
MENTION_RE = re.compile(r"@(\w+)")


def _notify(recipient, actor, verb, target):
    if recipient is None or recipient_id_equals_actor(recipient, actor):
        return
    notification = Notification.objects.create(recipient=recipient, verb=verb, target=target)
    push_notification(notification, actor)


def recipient_id_equals_actor(recipient, actor):
    return actor is not None and recipient.id == actor.id


@receiver(pre_save, sender=Issue)
def stash_previous_assignee(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_assignee_id = None
        return
    instance._previous_assignee_id = (
        Issue.objects.filter(pk=instance.pk).values_list("assignee_id", flat=True).first()
    )


@receiver(post_save, sender=Issue)
def notify_on_assignment(sender, instance, created, **kwargs):
    previous_assignee_id = getattr(instance, "_previous_assignee_id", None)
    if instance.assignee_id and instance.assignee_id != previous_assignee_id:
        actor = getattr(instance, "_actor", None) or instance.reporter
        _notify(instance.assignee, actor, "issue_assigned", instance)


@receiver(post_save, sender=Comment)
def notify_on_comment(sender, instance, created, **kwargs):
    if not created:
        return

    target = instance.content_object
    watchers = set()
    if hasattr(target, "assignee") and target.assignee_id:
        watchers.add(target.assignee)
    if hasattr(target, "reporter"):
        watchers.add(target.reporter)
    if hasattr(target, "owner"):
        watchers.add(target.owner)

    for user in watchers:
        _notify(user, instance.author, "commented", instance)

    mentioned_usernames = set(MENTION_RE.findall(instance.body))
    if mentioned_usernames:
        for user in User.objects.filter(username__in=mentioned_usernames):
            _notify(user, instance.author, "mentioned", instance)


@receiver(post_save, sender=Membership)
def notify_on_workspace_invite(sender, instance, created, **kwargs):
    if created and instance.role != Membership.Role.OWNER:
        _notify(instance.user, None, "workspace_invited", instance.workspace)


@receiver(post_save, sender=ProjectMember)
def notify_on_project_member_added(sender, instance, created, **kwargs):
    if created and instance.role != "owner":
        _notify(instance.user, None, "project_member_added", instance.project)
