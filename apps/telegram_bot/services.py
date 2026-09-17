import requests
from django.conf import settings

TELEGRAM_API_BASE = "https://api.telegram.org"
REQUEST_TIMEOUT = 10


class TelegramAPIError(Exception):
    """Raised whenever a call to the Telegram Bot API fails."""


def send_message(chat_id, text):
    if not settings.TELEGRAM_BOT_TOKEN:
        raise TelegramAPIError("TELEGRAM_BOT_TOKEN is not configured.")
    response = requests.post(
        f"{TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=REQUEST_TIMEOUT,
    )
    data = response.json()
    if not data.get("ok"):
        raise TelegramAPIError(data.get("description", "Telegram API call failed."))
    return data["result"]


def build_deep_link(start_token):
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={start_token}"
