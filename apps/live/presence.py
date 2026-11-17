"""Who has an issue open right now, kept in the cache (best-effort, no database writes).

With several web processes, CACHE_URL must point at a shared cache for everyone to see everyone.
"""

import time

from django.core.cache import cache

FRESH_SECONDS = 45


def beat(issue_id, user_id, now=None):
    """Record that user_id is looking at issue_id; return the other users seen recently."""
    now = now or time.time()
    key = f"presence:issue:{issue_id}"
    seen = {uid: at for uid, at in (cache.get(key) or {}).items() if now - at < FRESH_SECONDS}
    seen[user_id] = now
    cache.set(key, seen, FRESH_SECONDS * 2)
    return [uid for uid in seen if uid != user_id]
