"""
Base settings shared by all environments. Environment-specific files
(dev.py, prod.py) import * from here and override what they need.
"""
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "apps.accounts",
    "apps.workspaces",
    "apps.projects",
    "apps.issues",
    "apps.comments",
    "apps.activities",
    "apps.analytics",
    "apps.teams",
    "apps.cycles",
    "apps.milestones",
    "apps.notifications",
    "apps.integrations",
    "apps.telegram_bot",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://neo@localhost:5432/devtrack"),
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Deliver password-reset links on a background thread so the request returns
# immediately (and timing does not reveal whether an account exists). Production turns
# this on; tests and local dev stay synchronous.
PASSWORD_RESET_ASYNC = env.bool("PASSWORD_RESET_ASYNC", default=False)

# Where the frontend lives — used to build links (e.g. password reset) that
# point at the SPA rather than the API.
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:5173")

GITHUB_CLIENT_ID = env("GITHUB_CLIENT_ID", default="")
GITHUB_CLIENT_SECRET = env("GITHUB_CLIENT_SECRET", default="")
GITHUB_WEBHOOK_SECRET = env("GITHUB_WEBHOOK_SECRET", default="")
# OAuth scopes requested when a user connects GitHub (space-separated). "repo" is
# needed to list/hook private repositories; a public-only deployment can narrow it
# to "public_repo admin:repo_hook" (the least privilege that still creates webhooks).
GITHUB_OAUTH_SCOPE = env("GITHUB_OAUTH_SCOPE", default="repo")
# The Telegram bot itself (token, webhook) lives entirely in the standalone
# devtrack-telegram-bot service now — this app only needs to know its own
# bot's @username (to build the /start deep link) and how to reach that
# service's API.
TELEGRAM_BOT_USERNAME = env("TELEGRAM_BOT_USERNAME", default="")
TELEGRAM_BOT_SERVICE_URL = env("TELEGRAM_BOT_SERVICE_URL", default="http://localhost:9000")
BOT_SERVICE_API_KEY = env("BOT_SERVICE_API_KEY", default="")
# Shared with devtrack-telegram-bot: this signs /start deep-link tokens,
# that service verifies them — same value must be set on both sides.
TELEGRAM_LINK_SECRET = env("TELEGRAM_LINK_SECRET", default="")
# Symmetric key (Fernet) used to encrypt GitHubAccount.access_token at rest.
# Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Several comma-separated keys are accepted (first encrypts, all decrypt) so a key
# can be rotated — see `manage.py rotate_encryption_key`.
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default="")
# Must exactly match the callback URL registered on the GitHub OAuth App.
GITHUB_CALLBACK_URL = env(
    "GITHUB_CALLBACK_URL", default="http://localhost:8000/api/v1/integrations/github/callback/"
)
# Where GitHub POSTs webhook deliveries — a different endpoint from the OAuth
# callback above, supplied per-repo when the webhook is created via the API.
GITHUB_WEBHOOK_CALLBACK_URL = env(
    "GITHUB_WEBHOOK_CALLBACK_URL", default="http://localhost:8000/api/v1/integrations/github/webhook/"
)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/min",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS", default=["http://localhost:5173"]
)
