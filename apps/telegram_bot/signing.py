"""Must implement the exact same HMAC scheme as devtrack-telegram-bot's
signing.py — this side only ever signs (never verifies); the bot service
verifies tokens minted here against the same shared TELEGRAM_LINK_SECRET."""

import base64
import hashlib
import hmac
import time


def sign_user_id(user_id, secret):
    payload = f"{user_id}:{int(time.time())}"
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"
