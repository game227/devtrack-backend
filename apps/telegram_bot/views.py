from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import TelegramAccount

User = get_user_model()


class TelegramConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        token = signing.dumps({"user_id": request.user.id}, salt="telegram-link")
        return Response({"deep_link": services.build_deep_link(token)})


class TelegramStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        account = getattr(request.user, "telegram_account", None)
        if account is None:
            return Response({"connected": False})
        return Response(
            {
                "connected": True,
                "telegram_username": account.telegram_username,
                "linked_at": account.linked_at,
            }
        )


class TelegramDisconnectView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        TelegramAccount.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TelegramWebhookView(APIView):
    # Server-to-server delivery from Telegram — authenticated via the secret
    # token Telegram echoes back on every update (set at setWebhook time),
    # not a JWT, so this overrides the global defaults.
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not settings.TELEGRAM_WEBHOOK_SECRET or secret != settings.TELEGRAM_WEBHOOK_SECRET:
            return Response(status=status.HTTP_403_FORBIDDEN)

        message = request.data.get("message") or {}
        text = message.get("text", "")
        chat = message.get("chat") or {}
        from_user = message.get("from") or {}
        chat_id = chat.get("id")

        if chat_id is None or not text.startswith("/start"):
            # Any other command/text — always 2xx, Telegram doesn't retry on
            # non-2xx the way GitHub does, but there's nothing to do either way.
            return Response({"detail": "ignored"}, status=status.HTTP_200_OK)

        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            return Response({"detail": "missing token"}, status=status.HTTP_200_OK)

        try:
            data = signing.loads(parts[1], salt="telegram-link", max_age=600)
            user = User.objects.get(pk=data["user_id"])
        except (signing.BadSignature, User.DoesNotExist):
            try:
                services.send_message(
                    chat_id, "This link has expired. Go back to DevTrack Settings and try again."
                )
            except services.TelegramAPIError:
                pass
            return Response({"detail": "invalid token"}, status=status.HTTP_200_OK)

        # A chat can only ever belong to one DevTrack account — re-linking
        # moves it rather than tripping the chat_id unique constraint.
        TelegramAccount.objects.filter(chat_id=chat_id).exclude(user=user).delete()
        TelegramAccount.objects.update_or_create(
            user=user,
            defaults={"chat_id": chat_id, "telegram_username": from_user.get("username", "")},
        )
        try:
            services.send_message(chat_id, "✅ Your Telegram is now linked to DevTrack.")
        except services.TelegramAPIError:
            pass  # linking already succeeded locally; the confirmation is best-effort
        return Response({"detail": "ok"}, status=status.HTTP_200_OK)
