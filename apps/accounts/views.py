import logging
import threading

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

# accounts is a foundational/leaf app; telegram_bot is a feature app built on
# top of it. This one import runs against the codebase's usual leaf<-feature
# dependency direction — justified because password reset (a leaf-app view)
# needs to prefer an out-of-band delivery channel a feature app owns. Only
# the stateless services module is imported, never telegram_bot's models.
from apps.telegram_bot import services as telegram_services

from .messages import password_reset_message
from .serializers import (
    LoginSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    UserSerializer,
)

User = get_user_model()
logger = logging.getLogger(__name__)


def _deliver_password_reset(user_id, email, message):
    """Telegram first (if linked) — email is the fallback, not a second
    delivery, so a reset link is never sent twice. The bot service itself knows
    whether this user has a linked chat (a 404 there just means "not linked"),
    so there is nothing to check locally before trying."""
    try:
        telegram_services.send_message(user_id, message["telegram"])
        return
    except telegram_services.BotServiceError:
        pass  # not linked, or the bot service call failed — fall back to email

    try:
        send_mail(
            subject=message["subject"],
            message=message["email"],
            from_email=None,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception:  # noqa: BLE001 — never let delivery problems reach the caller
        logger.exception("Password reset email could not be delivered")


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response({"detail": "refresh is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            return Response(
                {"detail": "Invalid or already blacklisted token."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_object(self):
        return self.request.user


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Password changed successfully."})


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        user = User.objects.filter(email__iexact=email).first()
        if user is not None:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = PasswordResetTokenGenerator().make_token(user)
            reset_link = f"{settings.FRONTEND_URL}/reset-password/{uid}/{token}/"

            message = password_reset_message(serializer.validated_data["lang"], reset_link)
            if settings.PASSWORD_RESET_ASYNC:
                threading.Thread(
                    target=_deliver_password_reset, args=(user.id, email, message), daemon=True
                ).start()
            else:
                _deliver_password_reset(user.id, email, message)
        # Same response whether or not the account exists — don't leak it.
        return Response({"detail": "If an account with that email exists, a reset link has been sent."})


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Password has been reset successfully."})
