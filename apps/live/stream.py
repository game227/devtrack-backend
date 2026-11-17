"""The server-sent events stream: what changed, pushed within a couple of seconds.

GET /api/v1/changes/stream/?ticket=... answers ``text/event-stream``. Every POLL_SECONDS it checks the
same thing the polling endpoint does and sends ``event: changes`` with the areas that changed; a
comment line keeps the connection alive. Membership is rechecked on every round, and a stream ends after
MAX_SECONDS (the browser reconnects with a new ticket), so no connection outlives a removal for long.

It needs an ASGI server to scale (one open stream ties up a sync worker); see docs/DEPLOY_PLAN.md.
"""

import asyncio
import json
import secrets

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponseForbidden, StreamingHttpResponse
from django.utils import timezone

TICKET_SECONDS = 60
POLL_SECONDS = 2
KEEPALIVE_SECONDS = 20
MAX_SECONDS = 300
SALT = "devtrack.live.stream"


def issue_ticket(user_id, workspace_id):
    return signing.dumps({"u": user_id, "w": workspace_id, "n": secrets.token_hex(8)}, salt=SALT)


def redeem_ticket(ticket):
    """(user_id, workspace_id) for a valid, unused ticket; None otherwise."""
    try:
        data = signing.loads(ticket, salt=SALT, max_age=TICKET_SECONDS)
    except signing.BadSignature:
        return None
    if not cache.add(f"live-ticket:{data['n']}", 1, TICKET_SECONDS):
        return None  # already used
    return data["u"], data["w"]


def _round(user_id, workspace_id, since):
    """One check: None if the user may no longer watch this workspace, else the changed areas.

    Runs in a worker thread; its database connection is closed afterwards so an open stream does not
    hold one for minutes.
    """
    from apps.workspaces.models import Membership, Workspace

    from .views import changes_since

    try:
        if not Membership.objects.filter(user_id=user_id, workspace_id=workspace_id, user__is_active=True).exists():
            return None
        user = get_user_model().objects.get(pk=user_id)
        return changes_since(user, Workspace.objects.get(pk=workspace_id), since)
    finally:
        connection.close()


async def _events(user_id, workspace_id, rounds=None):
    since = timezone.now()
    yield "retry: 5000\n\n"
    elapsed = 0
    quiet = 0
    count = 0
    while elapsed < MAX_SECONDS and (rounds is None or count < rounds):
        await asyncio.sleep(POLL_SECONDS)
        elapsed += POLL_SECONDS
        count += 1
        now = timezone.now()
        changed = await sync_to_async(_round, thread_sensitive=False)(user_id, workspace_id, since)
        if changed is None:
            yield "event: closed\ndata: {}\n\n"
            return
        since = now
        if changed:
            quiet = 0
            yield f"event: changes\ndata: {json.dumps({'changed': changed})}\n\n"
        else:
            quiet += POLL_SECONDS
            if quiet >= KEEPALIVE_SECONDS:
                quiet = 0
                yield ": keep-alive\n\n"


async def stream_view(request):
    redeemed = await sync_to_async(redeem_ticket)(request.GET.get("ticket", ""))
    if redeemed is None:
        return HttpResponseForbidden("Invalid or used ticket.")
    response = StreamingHttpResponse(_events(*redeemed), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
