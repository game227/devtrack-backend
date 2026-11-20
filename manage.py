#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    # `manage.py test` always runs against the hermetic test settings, so a developer's .env
    # (e.g. PASSWORD_RESET_ASYNC=true) can never change what the tests exercise.
    default_settings = "config.settings.test" if sys.argv[1:2] == ["test"] else "config.settings.dev"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
