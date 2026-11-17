import logging
import threading

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import EmailMessage
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
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

from . import totp
from .messages import email_verification_message, password_reset_message
from .serializers import (
    AccountDeleteSerializer,
    EmailVerificationConfirmSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    TwoFactorDisableSerializer,
    TwoFactorEnableSerializer,
    TwoFactorSetupSerializer,
    UserSerializer,
)
from .sessions import revoke_all_sessions
from .throttling import (
    AccountLoginRateThrottle,
    AccountTwoFactorThrottle,
    EmailVerifyResendThrottle,
    PasswordCheckRateThrottle,
    PasswordResetEmailThrottle,
    RegisterRateThrottle,
)
from .tokens import email_verification_token
from .two_factor import accept_second_factor

User = get_user_model()
logger = logging.getLogger(__name__)


def _send_email(subject, body, to):
    """Send one plain-text email; replies go to the support address rather than the sending domain."""
    reply_to = [settings.SUPPORT_EMAIL] if settings.SUPPORT_EMAIL else None
    EmailMessage(subject=subject, body=body, to=[to], reply_to=reply_to).send(fail_silently=False)


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
        _send_email(message["subject"], message["email"], email)
    except Exception:  # noqa: BLE001 — never let delivery problems reach the caller
        logger.exception("Password reset email could not be delivered")


def _deliver_email_verification(email, message):
    try:
        _send_email(message["subject"], message["email"], email)
    except Exception:  # noqa: BLE001 — never let delivery problems reach the caller
        logger.exception("Verification email could not be delivered")


def _send_verification_email(user, lang):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    verify_link = f"{settings.FRONTEND_URL}/verify-email/{uid}/{token}/"
    message = email_verification_message(lang, verify_link)
    if settings.PASSWORD_RESET_ASYNC:
        threading.Thread(target=_deliver_email_verification, args=(user.email, message), daemon=True).start()
    else:
        _deliver_email_verification(user.email, message)


def _lang_from_request(request):
    lang = request.data.get("lang")
    return lang if lang in ("en", "uz", "ru") else "en"


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle, RegisterRateThrottle]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        _send_verification_email(user, _lang_from_request(request))
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_201_CREATED,
        )


class EmailVerifyConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailVerificationConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Email verified."})


class EmailVerifyResendView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [EmailVerifyResendThrottle]

    def post(self, request):
        user = request.user
        if user.email_verified:
            return Response({"detail": "Email is already verified."}, status=status.HTTP_400_BAD_REQUEST)
        _send_verification_email(user, _lang_from_request(request))
        return Response({"detail": "Verification email sent."})


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle, AccountLoginRateThrottle]


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
    throttle_classes = [UserRateThrottle, PasswordCheckRateThrottle]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        # Every other session ends with the old password (a stolen refresh token must not outlive it);
        # this one continues on a fresh pair, returned so the client can swap its stored tokens.
        revoke_all_sessions(user)
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "detail": "Password changed successfully.",
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            }
        )


class AccountDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle, PasswordCheckRateThrottle]

    def post(self, request):
        serializer = AccountDeleteSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user

        revoke_all_sessions(user)
        # Their GitHub token must not outlive the account (it was used to read their repositories).
        from apps.integrations.views import disconnect_github

        disconnect_github(user)

        # Deactivate and scrub PII instead of a hard delete: this user may be
        # the FK target (author, reporter, assignee) across workspaces other
        # people still rely on — a hard delete would cascade through and
        # destroy that shared data.
        user.is_active = False
        user.email = f"deleted-user-{user.pk}@devtrack.invalid"
        user.first_name = ""
        user.last_name = ""
        user.bio = ""
        user.title = ""
        user.avatar = None
        user.set_unusable_password()
        user.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle, PasswordResetEmailThrottle]

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
        user = serializer.save()
        # Resetting a password usually means "someone else may have it": end every existing session.
        revoke_all_sessions(user)
        return Response({"detail": "Password has been reset successfully."})


class TwoFactorSetupView(APIView):
    """Start enabling two-factor authentication: a secret for the authenticator app (not yet active).

    Asking again before confirming returns the same pending secret, so a second tab or a retry cannot
    silently invalidate the key the user already added to their app. Rate-limited: it checks the password.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [AccountTwoFactorThrottle]

    def post(self, request):
        serializer = TwoFactorSetupSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        if user.totp_enabled:
            return Response({"detail": "Two-factor authentication is already on."}, status=status.HTTP_400_BAD_REQUEST)
        if not user.totp_secret:
            user.totp_secret = totp.new_secret()
            user.totp_last_step = None
            user.save(update_fields=["totp_secret", "totp_last_step"])
        return Response(
            {"secret": user.totp_secret, "otpauth_uri": totp.provisioning_uri(user.totp_secret, user.username)}
        )


class TwoFactorEnableView(APIView):
    """Confirm the app works (a valid code for the pending secret), switch it on, hand out recovery codes once."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [AccountTwoFactorThrottle]

    def post(self, request):
        serializer = TwoFactorEnableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if user.totp_enabled:
            return Response({"detail": "Two-factor authentication is already on."}, status=status.HTTP_400_BAD_REQUEST)
        if not user.totp_secret:
            return Response({"detail": "Start the setup first."}, status=status.HTTP_400_BAD_REQUEST)
        step = totp.matching_step(user.totp_secret, serializer.validated_data["code"])
        if step is None:
            return Response({"code": ["That code is not valid."]}, status=status.HTTP_400_BAD_REQUEST)
        codes = totp.new_recovery_codes()
        user.totp_enabled = True
        user.totp_last_step = step
        user.totp_recovery_codes = [totp.hash_recovery_code(code) for code in codes]
        user.save(update_fields=["totp_enabled", "totp_last_step", "totp_recovery_codes"])
        # Sessions opened with the password alone end here; this one continues on a fresh pair.
        revoke_all_sessions(user)
        refresh = RefreshToken.for_user(user)
        return Response({"recovery_codes": codes, "access": str(refresh.access_token), "refresh": str(refresh)})


class TwoFactorDisableView(APIView):
    """Switch it off: needs the password and a current code (or a recovery code)."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [AccountTwoFactorThrottle]

    def post(self, request):
        serializer = TwoFactorDisableSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not user.totp_enabled:
            return Response({"detail": "Two-factor authentication is not on."}, status=status.HTTP_400_BAD_REQUEST)
        if not accept_second_factor(user, serializer.validated_data["code"]):
            return Response({"code": ["That code is not valid."]}, status=status.HTTP_400_BAD_REQUEST)
        user.totp_enabled = False
        user.totp_secret = None
        user.totp_last_step = None
        user.totp_recovery_codes = []
        user.save(update_fields=["totp_enabled", "totp_secret", "totp_last_step", "totp_recovery_codes"])
        return Response(status=status.HTTP_204_NO_CONTENT)
