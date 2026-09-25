"""Pushing DevTrack notifications to the user's linked Telegram chat.

The backend only says *what happened* (a structured payload: kind, actor, title, link path); the
bot service renders it in the chat's own language and honours the user's /mute. Delivery is
best-effort and, by default, happens on a background thread: a slow or dead bot service must never
slow down — let alone fail — the request that caused the notification.
"""

import logging
import threading

from django.conf import settings

from apps.issues.models import Issue
from apps.projects.models import Project

from . import services

logger = logging.getLogger(__name__)

EXCERPT_CHARS = 200


def build_payload(notification, actor=None):
    """The structured description of a Notification, or None if its target no longer exists."""
    target = notification.target
    if target is None:
        return None

    excerpt = ""
    if notification.verb in ("commented", "mentioned"):  # target is the Comment
        excerpt = target.body[:EXCERPT_CHARS]
        target = target.content_object
        if target is None:
            return None

    if isinstance(target, Issue):
        title, path = target.title, f"/issues/{target.id}"
    elif isinstance(target, Project):
        title, path = target.name, f"/projects/{target.id}"
    else:  # a workspace
        title, path = getattr(target, "name", str(target)), "/dashboard"

    return {
        "user_id": notification.recipient_id,
        "kind": notification.verb,
        "actor": actor.username if actor is not None else "",
        "title": title,
        "excerpt": excerpt,
        "path": path,
    }


def _deliver(payload):
    try:
        services.notify(payload)
    except services.BotServiceError:
        logger.debug("Telegram notification for user %s was not delivered.", payload["user_id"], exc_info=True)
    except Exception:  # noqa: BLE001 — a notification must never take anything else down with it
        logger.warning("Unexpected error delivering a Telegram notification.", exc_info=True)


def push_notification(notification, actor=None):
    if not settings.TELEGRAM_NOTIFICATIONS_ENABLED:
        return
    payload = build_payload(notification, actor)
    if payload is None:
        return
    if settings.TELEGRAM_NOTIFICATIONS_ASYNC:
        threading.Thread(target=_deliver, args=(payload,), daemon=True).start()
    else:
        _deliver(payload)
