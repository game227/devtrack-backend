import requests
from django.conf import settings

REQUEST_TIMEOUT = 10


class BotServiceError(Exception):
    """Raised whenever a call to the devtrack-telegram-bot service fails,
    including the expected "no linked chat for this user" 404 case."""


def _headers():
    return {"Authorization": f"Bearer {settings.BOT_SERVICE_API_KEY}"}


def send_message(user_id, text):
    response = requests.post(
        f"{settings.TELEGRAM_BOT_SERVICE_URL}/send",
        json={"user_id": user_id, "text": text},
        headers=_headers(),
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise BotServiceError(response.json().get("detail", "Failed to send Telegram message."))
    return response.json()


def get_status(user_id):
    response = requests.get(
        f"{settings.TELEGRAM_BOT_SERVICE_URL}/status/{user_id}",
        headers=_headers(),
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise BotServiceError("Failed to fetch Telegram status.")
    return response.json()


def delete_link(user_id):
    response = requests.delete(
        f"{settings.TELEGRAM_BOT_SERVICE_URL}/link/{user_id}",
        headers=_headers(),
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise BotServiceError("Failed to disconnect Telegram.")


def build_deep_link(start_token):
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={start_token}"
