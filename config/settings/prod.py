import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from .base import *  # noqa: F401,F403

DEBUG = False

# No-op until SENTRY_DSN is set (no Sentry account exists yet) — set the env
# var later and error tracking turns on with no further code changes.
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), LoggingIntegration(level=None, event_level="ERROR")],
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1),
        send_default_pii=False,
        environment=env("SENTRY_ENVIRONMENT", default="production"),
    )

# Render (and most PaaS) terminate TLS at the edge and forward plain HTTP
# with this header set — without telling Django, request.is_secure() would
# always read False behind the proxy, breaking secure-cookie/CSRF behavior.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# HSTS is opt-in: browsers cache it and refuse plain HTTP for the whole period, so it
# stays off (0) until the domain/TLS setup has proven stable. Ramp it up via the
# environment, e.g. 3600 -> 86400 -> 31536000.
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)

PASSWORD_RESET_ASYNC = env.bool("PASSWORD_RESET_ASYNC", default=True)

# Static files served directly by the app via WhiteNoise — no separate
# static host needed at this scale.
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Media (user uploads, e.g. avatars) stays on the mounted disk
# (FileSystemStorage) until MEDIA_STORAGE_BUCKET is set — an S3-compatible
# bucket (R2, S3, ...) doesn't exist yet. Switching to one later is just
# setting env vars, no code change: the disk doesn't scale horizontally
# and loses files if it ever fills up.
INSTALLED_APPS = INSTALLED_APPS + ["storages"]
MEDIA_STORAGE_BUCKET = env("MEDIA_STORAGE_BUCKET", default="")
if MEDIA_STORAGE_BUCKET:
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        "OPTIONS": {
            "bucket_name": MEDIA_STORAGE_BUCKET,
            # Blank for real AWS S3; set to the provider's endpoint for an
            # S3-compatible service such as Cloudflare R2.
            "endpoint_url": env("MEDIA_STORAGE_ENDPOINT_URL", default="") or None,
            "access_key": env("MEDIA_STORAGE_ACCESS_KEY", default=""),
            "secret_key": env("MEDIA_STORAGE_SECRET_KEY", default=""),
            "region_name": env("MEDIA_STORAGE_REGION", default="auto"),
            # A CDN/custom domain in front of the bucket, if any.
            "custom_domain": env("MEDIA_STORAGE_CUSTOM_DOMAIN", default="") or None,
            "default_acl": None,
            "querystring_auth": False,
            "file_overwrite": False,
        },
    }

MIDDLEWARE = MIDDLEWARE.copy()
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

# Password-reset emails go out via Resend's SMTP relay — no new dependency,
# Django's built-in SMTP backend already does the job.
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.resend.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "resend"
EMAIL_HOST_PASSWORD = env("RESEND_API_KEY", default="")
# resend.dev's shared sender only delivers to the Resend account's own
# verified address until a custom domain is verified on Resend — fine for
# now, revisit once a real "from" domain is set up.
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="onboarding@resend.dev")
