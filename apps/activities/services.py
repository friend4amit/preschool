"""Writing the day: entries, incidents, photographs, and the publish gate.

Plain functions that take arguments and own their transactions. They construct no
HttpRequest, which is what lets the whole day's flow be tested without a browser.

The publish path is the one to read carefully. `publish_media` refuses a photograph
whose tagged children do not all carry `photos_shared_with_class`, and it refuses by
raising rather than by silently skipping — a bulk publish that quietly drops three
photos teaches a teacher that the feature is unreliable, which is worse than a
message naming the child whose consent is missing.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.activities.models import (
    ActivityEntry,
    ActivityKind,
    IncidentReport,
    MediaAsset,
    MediaTag,
    UploadState,
)
from apps.activities.selectors import blocked_tags, is_publishable
from apps.core.models import Branch, Classroom, User
from apps.people.models import Student

# --------------------------------------------------------------------------------
# Activity entries
# --------------------------------------------------------------------------------


@transaction.atomic
def record_entry(
    *,
    kind: str,
    branch: Branch,
    student: Student | None = None,
    classroom: Classroom | None = None,
    body: str = "",
    occurred_at=None,
    author: User | None = None,
) -> ActivityEntry:
    """One entry, against a child or a room. Drafts by default.

    Draft rather than published because teachers stage the day and publish it once —
    a parent who gets a trickle of six notifications between 9am and 4pm has been
    given a worse experience than one who gets the day.
    """
    if (student is None) == (classroom is None):
        raise ValidationError("An entry targets exactly one of a student or a classroom.")
    return ActivityEntry.objects.create(
        branch=branch,
        student=student,
        classroom=classroom,
        kind=kind,
        body=body,
        occurred_at=occurred_at or timezone.now(),
        author=author,
    )


@transaction.atomic
def record_for_classroom(
    *,
    classroom: Classroom,
    kind: str = ActivityKind.NAP,
    body: str = "",
    occurred_at=None,
    author: User | None = None,
) -> ActivityEntry:
    """The bulk path: "everyone napped", as ONE row rather than thirty.

    This is the path that decides whether the feature survives a real day. Thirty
    rows would also be thirty things to edit when the teacher realises one child was
    absent, and the parent's feed unions room rows with their own child's anyway.
    """
    return record_entry(
        kind=kind,
        branch=classroom.branch,
        classroom=classroom,
        body=body,
        occurred_at=occurred_at,
        author=author,
    )


@transaction.atomic
def publish_entries(*, entries, at=None) -> int:
    """Publish a staged day. Returns how many rows changed.

    Idempotent: already-published rows are filtered out rather than re-stamped, so a
    double tap does not reset every `published_at` and reorder a parent's feed.
    """
    at = at or timezone.now()
    ids = [entry.pk for entry in entries]
    return ActivityEntry.objects.filter(pk__in=ids, is_published=False).update(
        is_published=True, published_at=at
    )


# --------------------------------------------------------------------------------
# Incidents
# --------------------------------------------------------------------------------


@transaction.atomic
def report_incident(
    *,
    student: Student,
    severity: str,
    what_happened: str,
    action_taken: str,
    staff_responsible: User,
    occurred_at=None,
    reported_by: User | None = None,
) -> IncidentReport:
    """Record that a child was hurt. Visible to the family immediately.

    There is no draft state here on purpose. An incident a teacher is still deciding
    whether to mention is the exact case the record exists to prevent.
    """
    return IncidentReport.objects.create(
        branch=student.branch,
        student=student,
        severity=severity,
        what_happened=what_happened,
        action_taken=action_taken,
        staff_responsible=staff_responsible,
        reported_by=reported_by,
        occurred_at=occurred_at or timezone.now(),
    )


@transaction.atomic
def acknowledge_incident(*, incident: IncidentReport, guardian: User, at=None) -> IncidentReport:
    """A named guardian confirms they were told, at a known time.

    The first acknowledgement stands. Re-acknowledging does not move the timestamp,
    because "when did the family find out" has one answer and it is the earliest one.
    """
    if incident.acknowledged_at is None:
        incident.acknowledged_by = guardian
        incident.acknowledged_at = at or timezone.now()
        incident.save(update_fields=["acknowledged_by", "acknowledged_at", "updated_at"])
    return incident


# --------------------------------------------------------------------------------
# Photographs
# --------------------------------------------------------------------------------


@transaction.atomic
def register_upload(
    *,
    branch: Branch,
    key: str,
    uploaded_by: User | None = None,
    content_type: str = "",
    taken_at=None,
) -> MediaAsset:
    """Create the PENDING row before the browser starts its direct-to-R2 PUT.

    The row comes first so that an object which lands but is never confirmed still has
    something pointing at it — the alternative is an orphan in the bucket that nothing
    knows about and nobody is looking for.
    """
    return MediaAsset.objects.create(
        branch=branch,
        key=key,
        uploaded_by=uploaded_by,
        content_type=content_type,
        taken_at=taken_at or timezone.now(),
        upload_state=UploadState.PENDING,
    )


@transaction.atomic
def confirm_upload(*, media: MediaAsset, byte_size=None, width=None, height=None) -> MediaAsset:
    """The browser reported the PUT succeeded. Promote PENDING to STORED."""
    media.upload_state = UploadState.STORED
    if byte_size is not None:
        media.byte_size = byte_size
    if width is not None:
        media.width = width
    if height is not None:
        media.height = height
    media.save(update_fields=["upload_state", "byte_size", "width", "height", "updated_at"])

    # Enqueued here rather than swept nightly: the worker is running and this is the
    # moment the bytes are known to exist. Deliberately after the save, and never
    # inside the transaction — a task enqueued in a transaction that then rolls back
    # is a worker looking for a row that does not exist.
    transaction.on_commit(lambda: _enqueue_thumbnail(media.pk))
    return media


def _enqueue_thumbnail(media_id: int) -> None:
    """Fire and forget. A thumbnail that never gets built costs the feed a larger
    image, not a broken one, so a queue that is down must not fail the upload."""
    from apps.activities import tasks

    try:
        tasks.build_thumbnail_task.enqueue(media_id=media_id)
    except Exception:  # noqa: BLE001 — see the docstring; this must not propagate.
        import logging

        logging.getLogger(__name__).warning("Could not enqueue thumbnail for %s", media_id)


@transaction.atomic
def tag(*, media: MediaAsset, student: Student, tagged_by: User | None = None) -> MediaTag:
    """A teacher says this child is in this photograph. Two taps, never automatic.

    `get_or_create` because tapping a child twice is a slip, not an instruction to
    create a second tag — and the unique constraint would refuse it anyway.
    """
    link, _ = MediaTag.objects.get_or_create(
        media=media, student=student, defaults={"tagged_by": tagged_by}
    )
    return link


@transaction.atomic
def untag(*, media: MediaAsset, student: Student) -> None:
    MediaTag.objects.filter(media=media, student=student).delete()


@transaction.atomic
def publish_media(*, media: MediaAsset, at=None) -> MediaAsset:
    """Publish one photograph, or refuse and say which child is blocking it.

    The refusal names the children rather than saying "consent missing", because the
    teacher's next action is to drop a tag or crop the photo and they need to know
    whose. Raising rather than returning False so a bulk publish cannot swallow it.
    """
    if not media.tags.exists():
        raise ValidationError("Tag the children in this photo before publishing it.")
    blocked = blocked_tags(media)
    if blocked:
        names = ", ".join(student.display_name for student in blocked)
        raise ValidationError(
            f"Not published: no sharing consent on record for {names}. "
            "Remove the tag, crop the photo, or keep it for that family only."
        )
    if not media.is_published:
        media.is_published = True
        media.published_at = at or timezone.now()
        media.save(update_fields=["is_published", "published_at", "updated_at"])
    return media


@transaction.atomic
def unpublish_media(*, media: MediaAsset) -> MediaAsset:
    """Pull a photograph back out of every feed. Used when a consent is revoked after
    the fact, and by a teacher who published the wrong thing."""
    media.is_published = False
    media.published_at = None
    media.save(update_fields=["is_published", "published_at", "updated_at"])
    return media


def publishable_among(media_queryset) -> tuple[list[MediaAsset], list[MediaAsset]]:
    """Split a day's photographs into (publishable, blocked) without writing anything.

    What the teacher's publish screen shows before they commit — the blocked half with
    the reason attached, so the rule is visible at tagging time rather than discovered
    at the end.
    """
    ready, blocked = [], []
    for asset in media_queryset:
        (ready if is_publishable(asset) else blocked).append(asset)
    return ready, blocked


# --------------------------------------------------------------------------------
# Storage keys and reconciliation
# --------------------------------------------------------------------------------


def build_key(*, branch: Branch, filename: str, when=None) -> str:
    """Where a photograph lives in the bucket.

    Branch-prefixed and date-partitioned, with a uuid rather than the uploaded name.
    Three reasons, all boring and all learned the hard way: two teachers photograph
    the same moment and both files are called IMG_4821.JPG; a phone filename is
    attacker-influenced input being interpolated into an object key; and a flat
    bucket of a hundred thousand objects is one nobody can list.
    """
    import uuid
    from pathlib import PurePosixPath

    when = when or timezone.now()
    suffix = PurePosixPath(filename).suffix.lower()[:10]
    return f"photos/{branch.pk}/{when:%Y/%m/%d}/{uuid.uuid4().hex}{suffix}"


@transaction.atomic
def mark_upload_failed(*, media: MediaAsset) -> MediaAsset:
    media.upload_state = UploadState.FAILED
    media.save(update_fields=["upload_state", "updated_at"])
    return media


def reconcile_uploads(*, older_than_minutes: int = 60) -> dict:
    """Confirm every PENDING row against the bucket. Runs nightly.

    A presigned direct upload means the browser can complete the R2 PUT and then fail
    to tell Django, or tell Django about an object that never arrived. Left alone,
    both accumulate: storage you are paying for and cannot see, and rows that will
    never render.

    Only rows older than `older_than_minutes` are touched, so an upload still in
    flight is not marked failed out from under a teacher on a slow connection.

    Deliberately does NOT delete bucket objects that have no row. That is the other
    half of the reconciliation and it deletes photographs of children on the strength
    of a database query — it wants its own command, its own dry run, and a person
    reading the list first.
    """
    from datetime import timedelta

    from integrations import storage_r2

    cutoff = timezone.now() - timedelta(minutes=older_than_minutes)
    promoted = failed = 0
    stale = MediaAsset.objects.filter(upload_state=UploadState.PENDING, created_at__lt=cutoff)
    for media in stale:
        if storage_r2.exists(key=media.key):
            confirm_upload(media=media)
            promoted += 1
        else:
            mark_upload_failed(media=media)
            failed += 1
    return {"promoted": promoted, "failed": failed}


# --------------------------------------------------------------------------------
# Erasure and retention
# --------------------------------------------------------------------------------
#
# The half of the storage story `reconcile_uploads` deliberately declines. Everything
# below can delete a photograph of a child, so all of it shares one shape:
#
#   * nothing deletes unless `commit=True`. The default is a report.
#   * every function returns the keys it touched, so the dry run IS the audit trail.
#   * the bucket object and the row go together. A delete that leaves the image in
#     the bucket is not a delete, and a bucket object with no row is invisible.
#
# There is no parent-facing button here and there should not be. Erasure is an
# operator action taken on a request the school has received and recorded — see
# `manage.py prune_media`.


def _forget_object(key: str, *, commit: bool) -> bool:
    """Remove one stored object, from R2 where it is configured and local disk where
    it is not. Returns whether there was something there to remove.

    Both backends, because the dev machine has no bucket and an erasure path that
    only works in production is one nobody ever watches run.
    """
    from django.core.files.storage import default_storage

    from integrations import storage_r2

    if storage_r2.is_configured():
        if not storage_r2.exists(key=key):
            return False
        if commit:
            storage_r2.delete(key=key)
        return True

    if not default_storage.exists(key):
        return False
    if commit:
        default_storage.delete(key)
    return True


def forget_media(*, media: MediaAsset, commit: bool = False) -> dict:
    """Delete one photograph: its thumbnail, its object, and its row.

    The row goes last. If the object delete raises, the row survives and the asset can
    be tried again; the other order leaves an object nothing points at, which is the
    exact condition this module exists to prevent.
    """
    keys = [media.key] + ([media.thumbnail_key] if media.thumbnail_key else [])
    removed = [key for key in keys if _forget_object(key, commit=commit)]
    if commit:
        with transaction.atomic():
            media.delete()
    return {"media_id": media.pk, "keys": keys, "objects_removed": removed}


def erase_student_media(*, student: Student, commit: bool = False) -> dict:
    """Everything about one child that this app holds, on a family's erasure request.

    The multi-child rule cuts both ways here. Untagging the child from a photograph
    that also shows two others does NOT delete that photograph — it is their
    photograph as much as it was this one's, and their families' consent is what
    governs it. So: drop this child's tags, then delete only the assets those tags
    left with nobody in them.

    `ActivityEntry` rows targeting the child go too; room-level entries stay, because
    "everyone napped" is not a record about this child.

    `IncidentReport` is deliberately NOT erased. It is a safety record naming a member
    of staff and an acknowledgement, the school may be required to hold it, and
    deleting it on request would let the record of an injury be removed by asking.
    Raise that with the school rather than quietly doing either thing here.
    """
    tagged = list(MediaAsset.objects.filter(tags__student=student).distinct())
    orphaned = [asset for asset in tagged if asset.tags.exclude(student=student).count() == 0]
    kept = [asset for asset in tagged if asset not in orphaned]

    entries = ActivityEntry.objects.filter(student=student)
    entry_count = entries.count()

    deleted = []
    if commit:
        with transaction.atomic():
            MediaTag.objects.filter(student=student).delete()
            entries.delete()
    for asset in orphaned:
        deleted.append(forget_media(media=asset, commit=commit))

    return {
        "student_id": student.pk,
        "tags_removed": len(tagged),
        "media_deleted": [item["media_id"] for item in deleted],
        "media_kept": [asset.pk for asset in kept],
        "entries_deleted": entry_count,
        "objects_removed": [key for item in deleted for key in item["objects_removed"]],
        "committed": commit,
    }


def prune_expired_media(*, window_days: int | None = None, commit: bool = False) -> dict:
    """The retention sweep. Delete photographs past the window; see the reasoning in
    `selectors.media_expired_by_retention`.

    Not scheduled from here. Like the backup, the thing that runs this on a timer is
    cron on the VPS — and unlike the backup, it should be read before it is trusted,
    so `--dry-run` is the default of the command that calls it.
    """
    from django.conf import settings

    from apps.activities.selectors import media_expired_by_retention

    window_days = window_days or settings.MEDIA_RETENTION_DAYS
    expired = list(media_expired_by_retention(window_days=window_days))
    results = [forget_media(media=asset, commit=commit) for asset in expired]
    return {
        "window_days": window_days,
        "media_deleted": [item["media_id"] for item in results],
        "objects_removed": [key for item in results for key in item["objects_removed"]],
        "committed": commit,
    }


def orphan_objects(*, prefix: str = "photos/", older_than_hours: int = 24) -> list[str]:
    """Bucket objects with no `MediaAsset` row — the other half of the reconciliation.

    Read-only on purpose, and separate from `reconcile_uploads` for the reason that
    function gives: this deletes photographs of children on the strength of a query,
    so it produces a list and a person reads it.

    The age floor matters. A key is written to the bucket by the browser moments
    before Django hears about it, so anything recent is far more likely to be an
    upload in flight than an orphan.
    """
    from datetime import timedelta

    from integrations import storage_r2

    cutoff = timezone.now() - timedelta(hours=older_than_hours)
    stored = storage_r2.objects(prefix=prefix)
    known = set(
        MediaAsset.objects.filter(key__startswith=prefix).values_list("key", flat=True)
    ) | set(MediaAsset.objects.exclude(thumbnail_key="").values_list("thumbnail_key", flat=True))
    return [obj.key for obj in stored if obj.key not in known and obj.last_modified < cutoff]


def delete_objects(*, keys, commit: bool = False) -> dict:
    """Remove named bucket objects. The `orphan_objects` list, after a person has read
    it — never a queryset piped straight in."""
    removed = [key for key in keys if _forget_object(key, commit=commit)]
    return {"considered": list(keys), "objects_removed": removed, "committed": commit}


# --------------------------------------------------------------------------------
# Thumbnails
# --------------------------------------------------------------------------------


# Two columns on a phone at 3x. Large enough that the grid is not visibly soft,
# small enough that a day of forty photographs is a few hundred KB rather than ten
# megabytes — which is the whole point on the connections these families have.
THUMBNAIL_EDGE = 600
THUMBNAIL_QUALITY = 78


def thumbnail_key_for(key: str) -> str:
    """Alongside the original, suffixed. Same prefix, so one `list_objects_v2` sees
    both and the retention sweep deletes them together without a second lookup."""
    from pathlib import PurePosixPath

    path = PurePosixPath(key)
    return str(path.with_name(f"{path.stem}_thumb.jpg"))


def build_thumbnail(*, media: MediaAsset) -> MediaAsset:
    """Fetch the stored photograph, downscale it, put it back, record the key.

    Runs in the worker, enqueued when the browser confirms its upload — not on a
    nightly sweep. The worker is already running and `django-tasks` can enqueue from a
    request; a second unscheduled nightly job would just repeat the gap that
    `reconcile_uploads` already has.

    The browser has ALREADY downscaled to 1600px before uploading, so this is a second
    reduction of an image that is at most a few hundred KB — it exists so the feed
    grid does not ship a 1600px file to fill a 180px square, not to make the upload
    survivable. Both together are why a 12 MP photo does not cost a parent 4 MB of
    their data plan to scroll past.

    Idempotent: a row that already has a thumbnail is left alone, so a retried task is
    free rather than a second round trip to storage.
    """
    import io

    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage
    from PIL import Image

    from integrations import storage_r2

    if media.upload_state != UploadState.STORED or media.thumbnail_key:
        return media

    key = thumbnail_key_for(media.key)
    using_r2 = storage_r2.is_configured()

    if using_r2:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            source = storage_r2.download(key=media.key, destination=Path(tmp) / "source")
            payload = _downscale(Image.open(source))
            written = Path(tmp) / "thumb.jpg"
            written.write_bytes(payload)
            storage_r2.upload(path=written, key=key)
    else:
        if not default_storage.exists(media.key):
            return media
        with default_storage.open(media.key, "rb") as handle:
            payload = _downscale(Image.open(io.BytesIO(handle.read())))
        default_storage.save(key, ContentFile(payload))

    media.thumbnail_key = key
    media.save(update_fields=["thumbnail_key", "updated_at"])
    return media


def _downscale(image) -> bytes:
    """One image to JPEG bytes at THUMBNAIL_EDGE. Not a service — pure, and the only
    place Pillow is touched, so a format problem has one place to be fixed."""
    import io

    from PIL import Image, ImageOps

    # `exif_transpose` first: a phone stores the rotation in a tag and Pillow does not
    # apply it on open, so without this a portrait photo thumbnails on its side.
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "L"):
        # JPEG has no alpha channel, and a PNG with one saves as an error otherwise.
        image = image.convert("RGB")
    image.thumbnail((THUMBNAIL_EDGE, THUMBNAIL_EDGE), Image.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=THUMBNAIL_QUALITY, optimize=True)
    return buffer.getvalue()
