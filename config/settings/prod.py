from .base import *  # noqa: F401,F403

DEBUG = False

# Railway (and most PaaS) terminate TLS at the edge and forward plain HTTP
# with this header set — without telling Django, request.is_secure() would
# always read False behind the proxy, breaking secure-cookie/CSRF behavior.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# Deliberately not setting SECURE_HSTS_SECONDS yet — Django's own check
# warns it "can cause serious, irreversible problems" if set carelessly
# (browsers cache it and refuse plain HTTP even if you need to roll back).
# Worth revisiting once the domain setup has proven stable.

# Static files served directly by the app via WhiteNoise — no separate
# static host needed at this scale. Media (user uploads) stays on local
# disk (FileSystemStorage, Django's default) backed by a mounted volume.
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
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
