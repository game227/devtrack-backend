import requests
from django.conf import settings

REQUEST_TIMEOUT = 10


class BotServiceError(Exception):
    """Raised whenever a call to the devtrack-telegram-bot service fails —
    an error status, an unreachable service, a timeout, or the expected
    "no linked chat for this user" 404 case."""


def _headers():
    return {"Authorization": f"Bearer {settings.BOT_SERVICE_API_KEY}"}


def _call(method, path, **kwargs):
    # Network failures (connection refused, DNS, timeout) must surface as
    # BotServiceError too, otherwise callers that fall back on it (password
    # reset -> email, status -> "not connected") would crash with a 500
    # whenever the bot service is down.
    try:
        return requests.request(
            method,
            f"{settings.TELEGRAM_BOT_SERVICE_URL}{path}",
            headers=_headers(),
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise BotServiceError(f"Bot service unreachable ({exc.__class__.__name__}).") from exc


def _detail(response, default):
    try:
        return response.json().get("detail", default)
    except (ValueError, AttributeError):
        return default


def send_message(user_id, text):
    response = _call("POST", "/send", json={"user_id": user_id, "text": text})
    if response.status_code != 200:
        raise BotServiceError(_detail(response, "Failed to send Telegram message."))
    return response.json()


def get_status(user_id):
    response = _call("GET", f"/status/{user_id}")
    if response.status_code != 200:
        raise BotServiceError("Failed to fetch Telegram status.")
    return response.json()


def delete_link(user_id):
    response = _call("DELETE", f"/link/{user_id}")
    if response.status_code != 200:
        raise BotServiceError("Failed to disconnect Telegram.")


def build_deep_link(start_token):
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={start_token}"
