from django.apps import AppConfig


class ActivitiesConfig(AppConfig):
    name = 'apps.activities'

    def ready(self):
        from . import signals  # noqa: F401
