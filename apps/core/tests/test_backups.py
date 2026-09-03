"""The nightly backup, without touching R2 or writing a dump.

The end-to-end proof is a rehearsal, not a test — `./scripts/restore.sh` loads a real
dump into a scratch database and counts the rows that come back, which is the only
check that means anything. What is tested here is the logic around it: the key
format, the retention arithmetic, and the two ways it can fail quietly.

Failing quietly is the real risk. A backup that silently does nothing looks
identical to one that works, right up until the morning you need it.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.core import backups
from integrations import storage_r2
from integrations.postgres import DumpFailed, table_names


def stored(key: str, *, days_old: int) -> storage_r2.StoredObject:
    return storage_r2.StoredObject(
        key=key, size=1024, last_modified=timezone.now() - timedelta(days=days_old)
    )


# --- keys -----------------------------------------------------------------------------


def test_a_backup_key_sorts_by_time_when_listed():
    """Lexical order has to equal chronological order — every tool that lists a
    bucket sorts by name, and a restore picks the newest."""
    earlier = backups.backup_key(at=datetime(2026, 3, 1, 2, 30, tzinfo=UTC))
    later = backups.backup_key(at=datetime(2026, 11, 1, 2, 30, tzinfo=UTC))
    assert earlier < later


@override_settings(TIME_ZONE="Asia/Kolkata")
def test_the_key_is_stamped_in_utc_not_local_time():
    """The one place a local timezone hurts. 02:30 IST is the previous day in UTC,
    and a filename that disagrees with the bucket's own timestamps is confusing at
    exactly the wrong moment."""
    key = backups.backup_key(at=datetime(2026, 3, 2, 2, 30, tzinfo=UTC))
    assert "20260302T023000Z" in key


@override_settings(BACKUP_PREFIX="backups/postgres/")
def test_backups_land_under_the_configured_prefix():
    assert backups.backup_key().startswith("backups/postgres/")


# --- retention ------------------------------------------------------------------------


@override_settings(BACKUP_RETENTION_DAYS=30)
def test_pruning_deletes_what_is_past_the_window_and_nothing_else(monkeypatch):
    catalogue = [stored("old.dump", days_old=45), stored("recent.dump", days_old=2)]
    deleted: list[str] = []

    monkeypatch.setattr(storage_r2, "objects", lambda **_: catalogue)
    monkeypatch.setattr(storage_r2, "delete", lambda *, key: deleted.append(key))

    assert backups.prune_old_backups() == ["old.dump"]
    assert deleted == ["old.dump"]


@override_settings(BACKUP_RETENTION_DAYS=30)
def test_pruning_a_bucket_of_only_recent_backups_deletes_nothing(monkeypatch):
    monkeypatch.setattr(storage_r2, "objects", lambda **_: [stored("today.dump", days_old=0)])
    monkeypatch.setattr(
        storage_r2, "delete", lambda **_: pytest.fail("Deleted a backup inside the window.")
    )
    assert backups.prune_old_backups() == []


def test_the_newest_backup_is_the_one_offered_for_restore(monkeypatch):
    monkeypatch.setattr(
        storage_r2,
        "objects",
        lambda **_: [stored("newest.dump", days_old=0), stored("older.dump", days_old=5)],
    )
    assert backups.latest_backup().key == "newest.dump"


# --- the quiet failures ---------------------------------------------------------------


@override_settings(R2_ACCESS_KEY_ID="", R2_BUCKET="")
def test_an_unconfigured_bucket_raises_rather_than_doing_nothing():
    """A no-op backup and a working one look identical from the outside. This is the
    line that makes them look different."""
    assert storage_r2.is_configured() is False
    with pytest.raises(storage_r2.NotConfigured):
        storage_r2.upload(path=Path("anything"), key="anything")


def test_an_unreadable_dump_is_reported_rather_than_treated_as_empty(tmp_path):
    """A file that is not a dump must not read as a dump with no tables in it."""
    not_a_dump = tmp_path / "notes.txt"
    not_a_dump.write_text("this is not a backup")

    with pytest.raises(DumpFailed):
        table_names(source=not_a_dump)


def test_a_failed_dump_never_puts_the_database_url_in_the_error(monkeypatch, tmp_path):
    """The URL holds the database password, and this exception ends up in logs."""
    from integrations import postgres

    class Failed:
        returncode = 1
        stderr = "connection refused"

    monkeypatch.setattr(postgres.subprocess, "run", lambda *a, **k: Failed())

    with pytest.raises(DumpFailed) as raised:
        postgres.dump(
            database_url="postgres://aaroham:hunter2@localhost:5432/aaroham",
            destination=tmp_path / "out.dump",
        )
    assert "hunter2" not in str(raised.value)
