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

# A SECOND, PUBLIC bucket — marketing images only, never a child's photo.
#
# Objects here are world-readable, cached forever and indexable by search engines.
# That is correct for a hero photograph and catastrophic for a classroom one, which
# is why this is a separate bucket rather than a prefix inside the private one: a
# prefix is one typo away from publishing a child.
_R2_PUBLIC_CONFIGURED = bool(
    env("R2_PUBLIC_BUCKET", default="") and env("R2_PUBLIC_BASE_URL", default="")
)

if _R2_CONFIGURED and _R2_PUBLIC_CONFIGURED:
    _public_media_storage = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "access_key": env("R2_ACCESS_KEY_ID"),
            "secret_key": env("R2_SECRET_ACCESS_KEY"),
            "bucket_name": env("R2_PUBLIC_BUCKET"),
            "endpoint_url": env("R2_ENDPOINT_URL"),
            # custom_domain is the load-bearing setting, not querystring_auth.
            # django-storages returns a clean https://host/key ONLY when this is
            # set; without it you get an unsigned URL against the S3 API endpoint,
            # and R2 does not serve anonymous GETs there — every image would 403.
            # Bare host, no scheme, no trailing slash.
            "custom_domain": env("R2_PUBLIC_BASE_URL"),
            "querystring_auth": False,
            "default_acl": None,
            # An admin re-uploading a same-named file gets a suffixed key rather
            # than silently replacing an object every CDN edge has cached for a
            # year under `immutable`.
            "file_overwrite": False,
            "region_name": "auto",
            "signature_version": "s3v4",
            "object_parameters": {"CacheControl": "public, max-age=31536000, immutable"},
        },
    }
else:
    # Loud, like the private bucket above: marketing images would land on the
    # container filesystem and vanish on the next rebuild.
    logging.getLogger(__name__).warning(
        "R2_PUBLIC_BUCKET / R2_PUBLIC_BASE_URL are not set — marketing images fall "
        "back to local disk and will NOT survive a container rebuild. Set them "
        "before the public site goes live."
    )
    _public_media_storage = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

STORAGES = {
    "default": _default_storage,
    "public_media": _public_media_storage,
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
