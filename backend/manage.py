#!/usr/bin/env python
"""Django command-line entry point (migrate, runserver, createsuperuser...)."""

import os
import sys


def main():
    # Development settings by default; Docker and production override this
    # through the DJANGO_SETTINGS_MODULE environment variable.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
