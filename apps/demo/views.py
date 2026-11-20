import datetime as dt

from django.conf import settings
from django.http import Http404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .cleanup import delete_expired
from .models import DemoAccount
from .seed import create_demo


class DemoStartThrottle(AnonRateThrottle):
    scope = "demo_start"


class DemoStartView(APIView):
    """POST: a fresh demo account with its own small workspace, signed in. Off unless DEMO_ENABLED."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [DemoStartThrottle]

    def post(self, request):
        if not settings.DEMO_ENABLED:
            raise Http404
        delete_expired()
        # Each demo has one visitor and two teammates; count visitors.
        if DemoAccount.objects.filter(user__username__regex=r"^demo-[0-9a-f]{8}$").count() >= settings.DEMO_MAX_ACTIVE:
            return Response({"detail": "The demo is busy right now. Try again later."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        user, workspace = create_demo(dt.timedelta(hours=settings.DEMO_TTL_HOURS))
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "workspace": workspace.pk,
                "expires_at": (timezone.now() + dt.timedelta(hours=settings.DEMO_TTL_HOURS)).isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )
