"""Settings for ``manage.py test`` (selected automatically by manage.py).

Hermetic on purpose: nothing here may depend on a developer's local ``.env``. A value there such as
``PASSWORD_RESET_ASYNC=true`` used to turn email delivery into real background threads during tests,
which made the ``mail.outbox`` assertions race and fail at random under ``--parallel``.
"""

from .base import *  # noqa: F401,F403

DEBUG = False

# Hashing is deliberately slow; with the real hasher it dominates the run time of the suite.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Anything that starts a thread or calls out must stay off, whatever .env says.
PASSWORD_RESET_ASYNC = False
TELEGRAM_NOTIFICATIONS_ENABLED = False
TELEGRAM_NOTIFICATIONS_ASYNC = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# The per-target throttles are cache-backed and the cache outlives a single test, so give them a rate no
# unrelated test can reach. The tests that exercise a throttle patch its rate explicitly.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": {
        **REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],  # noqa: F405
        "password_reset_email": "100000/hour",
        "register": "100000/hour",
        "member_add": "100000/hour",
        "github_sync": "100000/min",
        "two_factor": "100000/min",
        "password_check": "100000/min",
        "issue_export": "100000/hour",
    },
}

# The values the tests (and CI, which has no .env) already assume.
FRONTEND_URL = "http://localhost:5173"
GITHUB_OAUTH_SCOPE = "repo"
GITHUB_CALLBACK_URL = "http://localhost:8000/api/v1/integrations/github/callback/"
GITHUB_WEBHOOK_CALLBACK_URL = "http://localhost:8000/api/v1/integrations/github/webhook/"
TELEGRAM_BOT_SERVICE_URL = "http://localhost:9000"
