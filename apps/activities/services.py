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
    return media


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
