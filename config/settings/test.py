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

# `public_media` must be here as well as in base. A model field declaring
# `storage=public_media` resolves the alias at import time, and an unknown alias
# raises InvalidStorageError — which means the suite would stop COLLECTING rather
# than fail a test, and every error would point somewhere unhelpful.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "public_media": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
