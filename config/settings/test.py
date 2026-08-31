"""Test settings. Self-sufficient on purpose: `pytest` must run on a clean checkout
with only a database available, so CI needs no .env file."""

import os

os.environ.setdefault("SECRET_KEY", "test-only-not-a-secret")
os.environ.setdefault("DATABASE_URL", "postgres://aaroham:aaroham@localhost:5432/aaroham")
os.environ.setdefault("ALLOWED_HOSTS", "*")

from .base import *  # noqa: E402, F403

DEBUG = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Store tasks without running them, so tests assert on what was enqueued.
TASKS = {"default": {"BACKEND": "django_tasks.backends.dummy.DummyBackend"}}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
