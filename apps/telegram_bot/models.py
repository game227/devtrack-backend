from django.db import models  # noqa: F401

# Account-linking state now lives in the standalone devtrack-telegram-bot
# service's own SQLite store, not here — this app is a thin API client
# (see services.py) plus the views devtrack's frontend calls.
