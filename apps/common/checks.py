"""Deployment checks: ``python manage.py check --deploy`` refuses a configuration that would silently
run with a missing or guessable secret. CI runs it against the production settings, so a deploy that
forgets a secret fails before it ships rather than running insecurely."""

from django.conf import settings
from django.core.checks import Error, Tags, register

WEAK_SECRET_PREFIXES = ("change-me", "django-insecure", "changeme", "secret")


@register(Tags.security, deploy=True)
def check_required_secrets(app_configs, **kwargs):
    errors = []

    secret_key = settings.SECRET_KEY or ""
    if len(secret_key) < 32 or secret_key.lower().startswith(WEAK_SECRET_PREFIXES):
        errors.append(
            Error(
                "SECRET_KEY is short or a well-known placeholder.",
                hint="Use a random value of at least 32 characters; it signs JWTs and password-reset links.",
                id="devtrack.E001",
            )
        )

    if not settings.FIELD_ENCRYPTION_KEY.strip():
        errors.append(
            Error(
                "FIELD_ENCRYPTION_KEY is not set.",
                hint="GitHub access tokens are encrypted with it. Generate one with "
                "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`.",
                id="devtrack.E002",
            )
        )

    if settings.TELEGRAM_BOT_USERNAME and not (settings.TELEGRAM_LINK_SECRET and settings.BOT_SERVICE_API_KEY):
        errors.append(
            Error(
                "The Telegram bot is configured but TELEGRAM_LINK_SECRET or BOT_SERVICE_API_KEY is empty.",
                hint="An empty link secret lets anyone mint a token that links their chat to any account, "
                "and password-reset links are delivered to the linked chat.",
                id="devtrack.E003",
            )
        )

    if settings.GITHUB_CLIENT_ID and not settings.GITHUB_WEBHOOK_SECRET:
        errors.append(
            Error(
                "GitHub is configured but GITHUB_WEBHOOK_SECRET is empty.",
                hint="Webhook deliveries are rejected without it, so linked repositories would never update.",
                id="devtrack.E004",
            )
        )

    if "*" in settings.ALLOWED_HOSTS:
        errors.append(
            Error("ALLOWED_HOSTS contains '*'.", hint="List the real host names.", id="devtrack.E005")
        )

    if getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False):
        errors.append(
            Error("CORS_ALLOW_ALL_ORIGINS is on.", hint="List the frontend origin(s) explicitly.", id="devtrack.E006")
        )

    return errors
