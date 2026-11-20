from django.apps import AppConfig


class IssuesConfig(AppConfig):
    name = 'apps.issues'

    def ready(self):
        from . import signals  # noqa: F401
