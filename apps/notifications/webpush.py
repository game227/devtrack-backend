"""Web Push: notifications on the user's phone or desktop, even with DevTrack closed.

Off until VAPID keys are configured (``manage.py generate_vapid_keys``). The server only ever posts to
the browser vendors' push services (PUSH_HOSTS): the endpoint comes from the client, and without this
list it would be a way to make the server send requests anywhere. Delivery is best-effort; a
subscription the push service says is gone (404/410) is deleted.
"""

import json
import logging
import threading
from urllib.parse import urlsplit

from django.conf import settings

from apps.telegram_bot.notify import build_payload

from .models import PushSubscription

logger = logging.getLogger(__name__)

PUSH_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com")
PUSH_HOST_SUFFIXES = (".push.apple.com", ".notify.windows.com", ".push.services.mozilla.com")
MAX_SUBSCRIPTIONS_PER_USER = 10

TEXTS = {
    "en": {
        "issue_assigned": "{actor} assigned you an issue",
        "commented": "{actor} commented",
        "mentioned": "{actor} mentioned you",
        "workspace_invited": "{actor} invited you to a workspace",
        "project_member_added": "{actor} added you to a project",
        "other": "Something new in DevTrack",
    },
    "uz": {
        "issue_assigned": "{actor} sizga vazifa tayinladi",
        "commented": "{actor} izoh qoldirdi",
        "mentioned": "{actor} sizni eslatdi",
        "workspace_invited": "{actor} sizni ish maydoniga taklif qildi",
        "project_member_added": "{actor} sizni loyihaga qo'shdi",
        "other": "DevTrack'da yangilik",
    },
    "ru": {
        "issue_assigned": "{actor} назначил(а) вам задачу",
        "commented": "{actor} оставил(а) комментарий",
        "mentioned": "{actor} упомянул(а) вас",
        "workspace_invited": "{actor} пригласил(а) вас в рабочее пространство",
        "project_member_added": "{actor} добавил(а) вас в проект",
        "other": "Новое в DevTrack",
    },
}


def enabled():
    return bool(settings.WEB_PUSH_VAPID_PUBLIC_KEY and settings.WEB_PUSH_VAPID_PRIVATE_KEY)


def allowed_endpoint(endpoint):
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and parts.port in (None, 443) and (host in PUSH_HOSTS or host.endswith(PUSH_HOST_SUFFIXES))


def message(payload, lang):
    texts = TEXTS.get(lang) or TEXTS["en"]
    heading = texts.get(payload["kind"], texts["other"]).format(actor=payload["actor"] or "DevTrack")
    body = payload["title"] if not payload["excerpt"] else f"{payload['title']}: {payload['excerpt']}"
    return {"title": heading, "body": body[:240], "url": payload["path"], "tag": f"{payload['kind']}:{payload['path']}"}


def _send(subscription_id, data):
    from pywebpush import WebPushException, webpush

    subscription = PushSubscription.objects.filter(pk=subscription_id).first()
    if subscription is None:
        return
    try:
        webpush(
            subscription_info={"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
            data=json.dumps(data),
            vapid_private_key=settings.WEB_PUSH_VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.WEB_PUSH_SUBJECT},
            ttl=3600,
            timeout=5,
        )
    except WebPushException as error:
        status = getattr(error.response, "status_code", None)
        if status in (404, 410):
            subscription.delete()
        else:
            logger.info("Web push to subscription %s failed (%s).", subscription_id, status)
    except Exception:  # noqa: BLE001 — a notification must never take anything else down with it
        logger.warning("Unexpected error sending a web push.", exc_info=True)


def push_to_browsers(notification, actor=None):
    if not enabled():
        return
    subscriptions = list(PushSubscription.objects.filter(user_id=notification.recipient_id).values_list("pk", "lang"))
    if not subscriptions:
        return
    payload = build_payload(notification, actor)
    if payload is None:
        return
    for subscription_id, lang in subscriptions:
        data = message(payload, lang)
        if settings.WEB_PUSH_ASYNC:
            threading.Thread(target=_send, args=(subscription_id, data), daemon=True).start()
        else:
            _send(subscription_id, data)
