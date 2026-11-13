import re

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from apps.comments.models import Comment
from apps.issues.models import Issue
from apps.projects.models import ProjectMember
from apps.telegram_bot.notify import push_notification
from apps.workspaces.models import Invitation, Membership, Workspace

from .models import Notification

User = get_user_model()
MENTION_RE = re.compile(r"@(\w+)")


def _workspace_of(target):
    """The workspace a notification target lives in (None when it cannot be determined)."""
    if isinstance(target, Comment):
        target = target.content_object
    if target is None:
        return None
    if isinstance(target, Workspace):
        return target
    if hasattr(target, "project"):  # an issue
        return target.project.workspace
    return getattr(target, "workspace", None)  # a project


def _is_member(recipient, target):
    workspace = _workspace_of(target)
    return workspace is not None and Membership.objects.filter(workspace=workspace, user=recipient).exists()


def _notify(recipient, actor, verb, target, require_membership=True):
    if recipient is None or recipient_id_equals_actor(recipient, actor):
        return
    # Only people who belong to the workspace are told about what happens in it — and shown its titles
    # and comment excerpts (in-app and via Telegram). This also covers someone who was removed from the
    # workspace but is still the assignee/reporter/owner of something in it, and an @mention of a
    # username that happens to exist elsewhere.
    if require_membership and not _is_member(recipient, target):
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


@receiver(post_save, sender=Invitation)
def notify_on_workspace_invite(sender, instance, created, **kwargs):
    # The one notification about a workspace someone does not belong to (yet): only its name is shown.
    if created:
        _notify(instance.user, instance.invited_by, "workspace_invited", instance.workspace, require_membership=False)


@receiver(post_delete, sender=Invitation)
def forget_workspace_invite(sender, instance, **kwargs):
    # Accepted, declined, withdrawn or expired: the invitee keeps no link to a workspace they did not join
    # (its name would otherwise keep showing, live, after any rename).
    Notification.objects.filter(
        recipient_id=instance.user_id,
        verb="workspace_invited",
        content_type=ContentType.objects.get_for_model(Workspace),
        object_id=instance.workspace_id,
    ).delete()


@receiver(post_save, sender=ProjectMember)
def notify_on_project_member_added(sender, instance, created, **kwargs):
    if created and instance.role != "owner":
        _notify(instance.user, None, "project_member_added", instance.project)
