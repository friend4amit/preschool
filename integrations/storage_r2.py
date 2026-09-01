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
