from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .signing import sign_user_id


class TelegramConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        token = sign_user_id(request.user.id, settings.TELEGRAM_LINK_SECRET)
        return Response({"deep_link": services.build_deep_link(token)})


class TelegramStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            data = services.get_status(request.user.id)
        except services.BotServiceError:
            return Response({"connected": False})
        return Response(data)


class TelegramDisconnectView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        try:
            services.delete_link(request.user.id)
        except services.BotServiceError:
            pass  # best-effort — nothing locally to clean up either way
        return Response(status=status.HTTP_204_NO_CONTENT)
