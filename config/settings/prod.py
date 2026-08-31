import logging

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

from .base import *  # noqa: F403
from .base import BASE_DIR, env  # noqa: F401

DEBUG = False

# Durable, DB-backed queue. `manage.py db_worker` claims tasks with atomic locks,
# so this is safe to run multi-instance. No Redis, no broker. See docs/plan.md.
TASKS = {"default": {"BACKEND": "django_tasks_db.DatabaseBackend"}}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # Caddy terminates TLS
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in env.list("ALLOWED_HOSTS", default=[])]
X_FRAME_OPTIONS = "DENY"

# Media lives in R2: photos survive a server rebuild, and egress is free.
# The bucket is PRIVATE — objects are served by short-lived presigned GETs
# generated after the consent check. See docs/plan.md on compliance.
_R2_CONFIGURED = bool(env("R2_ACCESS_KEY_ID", default=""))

if _R2_CONFIGURED:
    _default_storage = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "access_key": env("R2_ACCESS_KEY_ID"),
            "secret_key": env("R2_SECRET_ACCESS_KEY"),
            "bucket_name": env("R2_BUCKET"),
            "endpoint_url": env("R2_ENDPOINT_URL"),
            "region_name": "auto",
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": 300,
            "signature_version": "s3v4",
        },
    }
else:
    # Lets a local or staging prod stack boot without R2 credentials. Loud on
    # purpose: uploads would land on the container filesystem and vanish on the
    # next rebuild, which for a photo feed means losing parents' photos. Configure
    # R2 before phase 4 ships uploads.
    logging.getLogger(__name__).warning(
        "R2 is not configured — media falls back to local disk and will NOT "
        "survive a container rebuild. Set R2_* before shipping uploads."
    )
    _default_storage = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

STORAGES = {
    "default": _default_storage,
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

if env("SENTRY_DSN", default=""):
    sentry_sdk.init(
        dsn=env("SENTRY_DSN"),
        integrations=[DjangoIntegration()],
        # Errors only. No Session Replay, no browser SDK, no behavioural analytics
        # on parent-facing pages — recording a screen of children's photos is
        # exactly what the DPDP Act is pointed at. See docs/plan.md.
        traces_sample_rate=0.05,
        send_default_pii=False,
    )
