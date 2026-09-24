"""Writing a notice, publishing it, and recording that somebody read it.

Plain functions owning their own transactions, constructing no HttpRequest. The one
rule worth stating out loud is the same one Phase 4 applies to photographs: nothing
reaches a parent until a person publishes it. Drafts are the default state and
`publish` is a separate, deliberate call.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.announcements.models import Announcement, AnnouncementRead
from apps.core.models import Branch, Classroom, User


@transaction.atomic
def create_announcement(
    *,
    branch: Branch,
    title: str,
    body: str,
    classroom: Classroom | None = None,
    is_school_wide: bool = False,
    is_pinned: bool = False,
    expires_on=None,
    author: User | None = None,
) -> Announcement:
    """A draft. It reaches nobody until `publish` is called on it.

    The XOR is checked here as well as in the database. The constraint is what makes
    it true; this is what makes the failure a `ValidationError` a form can render
    rather than an `IntegrityError` five hundred milliseconds into a POST.
    """
    if is_school_wide == (classroom is not None):
        raise ValidationError("A notice goes to the whole school or to one room, not both.")
    if classroom is not None and classroom.branch_id != branch.pk:
        raise ValidationError("That classroom belongs to another branch.")

    return Announcement.objects.create(
        branch=branch,
        title=title.strip(),
        body=body.strip(),
        classroom=classroom,
        is_school_wide=is_school_wide,
        is_pinned=is_pinned,
        expires_on=expires_on,
        author=author,
    )


@transaction.atomic
def publish(announcement: Announcement) -> Announcement:
    """Make it visible to the parents it addresses.

    Idempotent, and it keeps the FIRST publication time. Re-publishing an edited
    notice must not reorder it to the top of every parent's feed as though it were
    news — and "when did the school tell us" has one answer, not the most recent one.
    """
    if announcement.is_published:
        return announcement
    announcement.is_published = True
    announcement.published_at = timezone.now()
    announcement.save(update_fields=["is_published", "published_at", "updated_at"])
    return announcement


@transaction.atomic
def unpublish(announcement: Announcement) -> Announcement:
    """Pull it back. The read receipts stay.

    Deleting the receipts would be tidier and wrong: "who saw the notice before we
    withdrew it" is exactly the question that gets asked after a notice is withdrawn.
    """
    announcement.is_published = False
    announcement.save(update_fields=["is_published", "updated_at"])
    return announcement


@transaction.atomic
def mark_read(*, announcement: Announcement, guardian: User) -> AnnouncementRead:
    """Record that this guardian opened it. First read wins.

    `get_or_create` rather than `update_or_create`: the receipt answers "when were
    they first told", and refreshing the timestamp on every re-open would erase the
    only fact it exists to hold.
    """
    receipt, _ = AnnouncementRead.objects.get_or_create(
        announcement=announcement,
        guardian=guardian,
        defaults={"read_at": timezone.now()},
    )
    return receipt
