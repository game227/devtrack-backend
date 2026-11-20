from .base import *  # noqa: F401,F403

DEBUG = True

# MVP: no real SMTP yet — password-reset emails just print to the runserver
# console/log.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Local development (and the e2e job, which runs this settings module) registers fresh accounts and
# requests password resets over and over; production's per-hour limits would lock the developer out
# after a couple of test runs. The limits themselves are tested in the backend suite.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": {
        **REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],  # noqa: F405
        "register": "1000/hour",
        "password_reset_email": "1000/hour",
    },
}
