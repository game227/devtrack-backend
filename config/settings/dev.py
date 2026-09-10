from .base import *  # noqa: F401,F403

DEBUG = True

# MVP: no real SMTP yet — password-reset emails just print to the runserver
# console/log.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
