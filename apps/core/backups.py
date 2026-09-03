"""The nightly backup, as business logic.

Lives beside `services.py` rather than in it because it is about the database as an
artefact, not about the domain — it touches no model and has no `branch`. It keeps
the same layer position: it composes `integrations/`, owns its own decisions, and
knows nothing about HTTP.

The plan puts this in Phase 1 ("personal data arrives in Phase 1, so backups do
too") and it was not built then. It is here now, in Phase 2, which is the phase whose
Done-when requires a restore to have been rehearsed. The plan was right about the
sequence; the code was behind it.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.utils import timezone

from integrations import postgres, storage_r2


def backup_key(*, at: datetime | None = None) -> str:
    """One key per run, sorted by time when listed lexically.

    UTC in the filename even though the whole application is Asia/Kolkata: a backup
    is an operations artefact, and the one place a local timezone genuinely hurts is
    a filename that has to sort correctly across a DST-free but offset boundary.
    """
    stamp = (at or timezone.now()).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{settings.BACKUP_PREFIX}aaroham-{stamp}.dump"


def run_backup(*, database_url: str | None = None) -> str:
    """Dump, upload, prune. Returns the key it wrote.

    The dump is written to a temporary directory that is removed on the way out —
    the server holds no copy. A local copy would be a second place for the whole
    school's personal data to sit unencrypted, and it would fill the disk.
    """
    url = database_url or settings.DATABASES["default"].get("URL") or _url_from_settings()
    key = backup_key()

    with TemporaryDirectory() as workspace:
        path = postgres.dump(database_url=url, destination=Path(workspace) / Path(key).name)
        storage_r2.upload(path=path, key=key)

    prune_old_backups()
    return key


def prune_old_backups(*, now: datetime | None = None) -> list[str]:
    """Delete dumps past the retention window. Returns what it removed.

    Pruning runs in the same task that writes, rather than on its own schedule: a
    prune that runs when the write has been failing for a month would delete the last
    good backup, which is the worst possible ordering.
    """
    cutoff = (now or timezone.now()) - timedelta(days=settings.BACKUP_RETENTION_DAYS)
    stale = [
        obj.key
        for obj in storage_r2.objects(prefix=settings.BACKUP_PREFIX)
        if obj.last_modified < cutoff
    ]
    for key in stale:
        storage_r2.delete(key=key)
    return stale


def latest_backup() -> storage_r2.StoredObject | None:
    return next(iter(storage_r2.objects(prefix=settings.BACKUP_PREFIX)), None)


def _url_from_settings() -> str:
    """django-environ hands settings a parsed dict, not the URL it came from."""
    db = settings.DATABASES["default"]
    return (
        f"postgres://{db['USER']}:{db['PASSWORD']}@{db['HOST']}:{db['PORT'] or 5432}/{db['NAME']}"
    )
