"""Reads for the notice board, on both sides of it.

The parent-facing question is "which notices reach this guardian", and it has a
different shape from the photo feed's. A photograph is gated on consent, because it
is a picture of a child. A notice is not: it is the school talking to the parents of
its own students, and there is no purpose to consent to. The gate here is enrolment —
you see a room's notices while you have a child in that room — and nothing else.

That difference is worth stating because the two feeds sit next to each other in the
portal and it would be easy to copy the consent check across out of symmetry. It would
then be a bug: a guardian who declined photo consent would stop being told the school
is shut on Monday.
"""

from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from apps.announcements.models import Announcement, AnnouncementRead
from apps.core import selectors as core_selectors
from apps.core.models import User
from apps.people import selectors as people_selectors
from apps.people.models import Student, StudentStatus

# --------------------------------------------------------------------------------
# Staff reads
# --------------------------------------------------------------------------------


def for_user(user: User) -> QuerySet[Announcement]:
    """Every notice at the branches this user works at, drafts included.

    Explicit scoping, per the non-negotiable in docs/plan.md — no scoped manager, no
    middleware. A teacher sees their branch's notices whether or not they wrote them;
    a notice board that only showed you your own would defeat the point.
    """
    return (
        Announcement.objects.filter(branch__in=core_selectors.branches_for_user(user))
        .select_related("classroom", "author")
        .distinct()
    )


def staff_detail(user: User, announcement_id: int) -> Announcement | None:
    return for_user(user).filter(pk=announcement_id).first()


def read_count(announcement: Announcement) -> int:
    """How many guardian accounts have opened this one.

    The denominator deliberately is not computed here. "Twelve of how many" needs a
    definition of the audience — guardians with portal accounts, of currently enrolled
    children, in this room — and that belongs to whoever renders it. See
    `audience_size`.
    """
    return AnnouncementRead.objects.filter(announcement=announcement).count()


def audience_size(announcement: Announcement) -> int:
    """How many guardian accounts could have read it.

    Counts *accounts*, not guardians: a family whose portal login was never created
    cannot read a notice, and including them would make every notice look unread
    forever. It is the honest denominator for the read receipt, and it moves as
    children enrol and leave, which is why it is computed rather than stored.
    """
    return _audience_users(announcement).count()


def _audience_users(announcement: Announcement) -> QuerySet[User]:
    """The guardian `User` rows a notice is addressed to."""
    return User.objects.filter(
        guardian_profile__student_links__student__in=_audience_students(announcement)
    ).distinct()


def _audience_students(announcement: Announcement) -> QuerySet[Student]:
    """Currently enrolled children the notice targets."""
    qs = Student.objects.filter(branch=announcement.branch, status=StudentStatus.ENROLLED)
    if announcement.is_school_wide:
        return qs
    return qs.filter(
        enrollments__classroom=announcement.classroom, enrollments__left_on__isnull=True
    ).distinct()


# --------------------------------------------------------------------------------
# Parent reads
# --------------------------------------------------------------------------------


def _visible_q(user: User, *, on=None) -> Q:
    """School-wide, or addressed to a room one of this user's children is in.

    Uses `people_selectors.children_of`, which is the same scoping the photo feed and
    "my children" use. Routing every parent-facing read through one definition of
    "this user's children" is what keeps them from drifting apart.
    """
    today = on or timezone.localdate()
    children = people_selectors.children_of(user)
    rooms = children.filter(enrollments__left_on__isnull=True).values("enrollments__classroom")
    return (
        Q(is_published=True)
        & Q(branch__in=children.values("branch"))
        & (Q(is_school_wide=True) | Q(classroom__in=rooms))
        & (Q(expires_on__isnull=True) | Q(expires_on__gte=today))
    )


def feed_for(user: User, *, on=None) -> QuerySet[Announcement]:
    """The parent's notice board, newest first, with a read flag per row.

    The receipt is annotated rather than joined so a notice appears exactly once no
    matter how many children the guardian has in the addressed room — a LEFT JOIN on
    `reads` would duplicate the row the moment a second family member reads it.
    """
    read = AnnouncementRead.objects.filter(announcement=OuterRef("pk"), guardian=user)
    return (
        Announcement.objects.filter(_visible_q(user, on=on))
        .annotate(is_read=Exists(read))
        .select_related("classroom")
        .distinct()
    )


def detail_for(user: User, announcement_id: int, *, on=None) -> Announcement | None:
    """One notice, if it reaches this guardian. None otherwise — the view turns that
    into a 404, never a 403, so walking ids does not confirm a notice exists."""
    return feed_for(user, on=on).filter(pk=announcement_id).first()


def unread_count(user: User, *, on=None) -> int:
    """The portal badge.

    Runs the same gated query as the feed itself, for the reason the photo badge does:
    a count derived any other way can promise a notice the feed then withholds.
    """
    return feed_for(user, on=on).filter(is_read=False).count()
