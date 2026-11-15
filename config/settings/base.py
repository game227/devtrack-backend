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
    # Before django.contrib.admin, so its admin template overrides take precedence.
    "apps.adminui",
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
    "apps.common",
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
    "apps.live",
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
    "apps.common.middleware.ApiResponseHeadersMiddleware",
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

# Argon2 first: memory-hard, so offline cracking of a leaked database is far more expensive than with
# PBKDF2. Existing PBKDF2 hashes keep working and are upgraded transparently on the user's next login.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

# Password-reset and email-verification links expire after a day (Django's default is three).
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24

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

# Throttle counters live in the cache. The default is per-process memory, which is right for a single
# gunicorn worker; with several workers or instances point CACHE_URL at a shared backend
# (e.g. ``dbcache://django_cache`` after ``manage.py createcachetable``, or a Redis URL).
CACHES = {"default": environ.Env.cache_url_config(env("CACHE_URL", default="").strip() or "locmemcache://")}

# The Django admin lives under this path. Moving it off the guessable default keeps scanners and
# credential-stuffing bots away from the login form; set ADMIN_URL=some-long-random-path/ in production.
# An empty value (e.g. a dashboard variable created but left blank) falls back to the default instead of
# mounting the admin at the site root.
ADMIN_URL = (env("ADMIN_URL", default="").strip().strip("/") or "admin") + "/"

# Largest multipart request accepted (avatars are the only uploads). Enforced before the body is read.
MAX_UPLOAD_BYTES = int(env("MAX_UPLOAD_BYTES", default="").strip() or 3 * 1024 * 1024)
FILE_UPLOAD_HANDLERS = [
    "apps.common.uploads.MaxRequestSizeUploadHandler",
    "django.core.files.uploadhandler.MemoryFileUploadHandler",
    "django.core.files.uploadhandler.TemporaryFileUploadHandler",
]

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
# Push in-app notifications to the user's linked Telegram chat. Off unless switched on, so tests and a
# bot-less dev setup never make network calls; production sets it to true. Delivery runs in a
# background thread by default so a slow bot service can never slow down the request that caused it.
TELEGRAM_NOTIFICATIONS_ENABLED = env.bool("TELEGRAM_NOTIFICATIONS_ENABLED", default=False)
TELEGRAM_NOTIFICATIONS_ASYNC = env.bool("TELEGRAM_NOTIFICATIONS_ASYNC", default=True)
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

# Blank means "not configured" (DRF's default); 0 is meaningful (ignore X-Forwarded-For entirely).
_NUM_PROXIES = env("NUM_PROXIES", default="").strip()

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
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.UserRateThrottle",
    ),
    # How many reverse proxies sit in front of the app. DRF uses it to read the client address from
    # X-Forwarded-For; left unset it trusts the *whole* header, which a client can forge to dodge the
    # per-IP limits. Set it to the real number of proxies (see the README, "Deploying").
    "NUM_PROXIES": int(_NUM_PROXIES) if _NUM_PROXIES else None,
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/min",
        # Generous safety net for authenticated traffic — not meant to affect
        # normal usage, just cap a single account gone rogue (script, leaked
        # token). Falls back to per-IP for anonymous requests on views that
        # don't set their own throttle_classes.
        "user": "600/min",
        "login_account": "10/min",
        "email_verify_resend": "3/min",
        # Per-target limits do not depend on the caller's IP, so they hold even when the IP is spoofed.
        "password_reset_email": "3/hour",
        "register": "10/hour",
        "member_add": "60/hour",
        "github_sync": "10/min",
        "two_factor": "10/min",
        "password_check": "10/min",
    },
}

SIMPLE_JWT = {
    # Short-lived: an access token cannot be revoked, so a stolen one is only useful for this long.
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS", default=["http://localhost:5173"]
)

# Structured console logging — Render (and most PaaS) collect stdout directly,
# so there's no file handler to manage. Django's own request logger stays at
# its default WARNING+ (it already reports 5xx with a traceback); "apps" is
# this project's own logger namespace, used via logging.getLogger(__name__)
# in apps/*. Never log request bodies or tokens here — only messages already
# written that way (see apps/accounts/views.py's use of logger.exception).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
