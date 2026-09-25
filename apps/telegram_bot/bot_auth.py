import hmac

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

User = get_user_model()

USER_HEADER = "X-DevTrack-User-Id"


class BotServiceAuthentication(BaseAuthentication):
    """The Telegram bot service acting for the DevTrack user whose chat it is talking to.

    Two things must both hold: the shared BOT_SERVICE_API_KEY (proves the caller is our bot
    service) and an ``X-DevTrack-User-Id`` naming the account (the bot only knows that id for chats
    that went through the signed /start linking). It is deliberately used only by the small
    ``bot/`` API surface in bot_api.py — never as a global authentication class — so a leaked key can
    reach exactly those endpoints and no others.
    """

    def authenticate(self, request):
        expected = settings.BOT_SERVICE_API_KEY
        header = request.headers.get("Authorization", "")
        if not expected or not header.startswith("Bearer "):
            return None
        if not hmac.compare_digest(header[len("Bearer "):], expected):
            return None

        try:
            user_id = int(request.headers.get(USER_HEADER, ""))
        except ValueError:
            raise AuthenticationFailed(f"Missing or invalid {USER_HEADER} header.")
        user = User.objects.filter(pk=user_id, is_active=True).first()
        if user is None:
            raise AuthenticationFailed("Unknown user.")
        return (user, None)

    def authenticate_header(self, request):
        return "Bearer"
