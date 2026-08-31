from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["*"]
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Same DB-backed queue as prod, so the dev worker container has real work and
# dev/prod parity is not something you discover on deploy day.
TASKS = {"default": {"BACKEND": "django_tasks_db.DatabaseBackend"}}
