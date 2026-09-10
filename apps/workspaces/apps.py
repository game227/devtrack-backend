from django.apps import AppConfig


class WorkspacesConfig(AppConfig):
    name = 'apps.workspaces'

    def ready(self):
        from . import signals  # noqa: F401
