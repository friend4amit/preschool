"""Cloudflare R2, for the things Django's storage backend does not carry.

Media uploads go through `django-storages`, configured in `config/settings/prod.py`.
This wrapper exists for database backups, which are not model files: nothing points
at them, they are written by a background task, and they get pruned on a schedule.

Free at this volume with no egress charge, which is the reason the whole backup
story costs nothing. Vendor-only, per the layer contract — it imports no domain code
and knows nothing about what is in the files it moves.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import boto3
from botocore.config import Config
from django.conf import settings


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    last_modified: datetime


class NotConfigured(RuntimeError):
    """R2 credentials are absent. Raised rather than silently doing nothing — a
    backup that quietly no-ops is worse than one that fails loudly."""


def is_configured() -> bool:
    return bool(getattr(settings, "R2_ACCESS_KEY_ID", "") and getattr(settings, "R2_BUCKET", ""))


def _client():
    if not is_configured():
        raise NotConfigured("R2_ACCESS_KEY_ID and R2_BUCKET are not set.")
    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        # R2 is S3-compatible but has no regions; boto3 insists on one being named.
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def upload(*, path: Path, key: str) -> str:
    _client().upload_file(str(path), settings.R2_BUCKET, key)
    return key


def download(*, key: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _client().download_file(settings.R2_BUCKET, key, str(destination))
    return destination


def objects(*, prefix: str = "") -> list[StoredObject]:
    """Newest first — the order anyone restoring actually wants."""
    paginator = _client().get_paginator("list_objects_v2")
    found = [
        StoredObject(key=item["Key"], size=item["Size"], last_modified=item["LastModified"])
        for page in paginator.paginate(Bucket=settings.R2_BUCKET, Prefix=prefix)
        for item in page.get("Contents", [])
    ]
    return sorted(found, key=lambda o: o.last_modified, reverse=True)


def delete(*, key: str) -> None:
    _client().delete_object(Bucket=settings.R2_BUCKET, Key=key)


def presign_put(*, key: str, content_type: str = "", expires_in: int = 900) -> str:
    """A URL the browser may PUT one object to, and nothing else.

    Direct-to-R2: the photograph never passes through Django. A 12 MP phone photo
    through the VPS would occupy a gunicorn worker for the length of a 4G upload, and
    there are three workers.

    Scoped to one key and one method, and short-lived — fifteen minutes is longer than
    an upload on a bad connection and shorter than a URL is useful to anyone who
    finds it later.
    """
    params = {"Bucket": settings.R2_BUCKET, "Key": key}
    if content_type:
        params["ContentType"] = content_type
    return _client().generate_presigned_url("put_object", Params=params, ExpiresIn=expires_in)


def presign_get(*, key: str, expires_in: int = 300) -> str:
    """A short-lived URL to read one object.

    The bucket is private, so this is the only way a photograph reaches a browser.
    Five minutes: long enough to render a feed, short enough that a forwarded link is
    dead by the time it is opened. Do not lengthen this to make caching work — the
    authorisation lives in the code that decides whether to call this at all, and a
    long-lived URL moves it somewhere nobody can revoke.
    """
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.R2_BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )


def exists(*, key: str) -> bool:
    """Whether an object actually landed. The nightly reconciliation's question.

    404 means the browser never completed its PUT; every other error is a real fault
    and is allowed to propagate rather than being reported as "missing", which would
    make the reconciliation delete rows on an outage.
    """
    from botocore.exceptions import ClientError

    try:
        _client().head_object(Bucket=settings.R2_BUCKET, Key=key)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise
    return True


def public_media():
    """The storage marketing images live in — world-readable, cached, indexable.

    Deliberately NOT `default`, which in production is the private bucket holding
    children's photos and is served by short-lived presigned URLs after a consent
    check. Those are opposite requirements; see config/settings/prod.py.

    Referenced as a callable from model fields rather than resolved at import time.
    Django's FileField holds the callable on `_storage_callable` and `deconstruct()`
    re-emits it, so what lands in a migration is this function's import path and not
    a frozen storage instance with a bucket name baked into it.
    """
    from django.core.files.storage import storages

    return storages["public_media"]
