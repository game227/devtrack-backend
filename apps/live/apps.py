from django.apps import AppConfig


class LiveConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.live"

    def ready(self):
        from . import signals  # noqa: F401 — connects the change markers
