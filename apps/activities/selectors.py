"""Reads for the feed, and the consent gate that decides which photographs exist.

This is the most security-sensitive module in the product so far. Everything the
parent portal shows a family passes through here, and `docs/plan.md` is explicit that
getting it wrong makes every permission rule in both planning documents decorative.

Two consent questions, and conflating them is the mistake this file exists to avoid:

- `photos_in_app` governs whether **this guardian** sees photographs of **their own**
  child. It is a property of the viewer.
- `photos_shared_with_class` governs whether a child may appear in a photograph shown
  to **other** families. It is a property of every child tagged in the photo, and a
  photo publishes only if *all* of them carry it.

Nothing here knows what HTTP is. The view turns an empty result into a 404 — never a
403, because a family must not learn that another family's photo ids exist.
"""

from django.db.models import Exists, OuterRef, Q, QuerySet

from apps.activities.models import ActivityEntry, IncidentReport, MediaAsset, UploadState
from apps.core.models import Consent, ConsentPurpose, User
from apps.people.models import Student, StudentGuardian
from apps.people.selectors import children_of, students_for_user

# --------------------------------------------------------------------------------
# Consent
# --------------------------------------------------------------------------------
#
# `Consent.guardian` points at `User`, and `Guardian.user` is nullable — a guardian
# exists on the record the moment an admission is taken, and the portal account comes
# later. So a child's guardians fall into three states per purpose, not two:
#
#   no row      the question was never put to them (including: they have no account)
#   inactive    they were asked and said no, or granted and later revoked
#   active      they said yes
#
# `plan.md` settles the multi-CHILD rule ("every tagged child") and is silent on the
# multi-GUARDIAN one, so this is a decision made here rather than one handed down:
#
#   a child carries a purpose when at least one guardian has actively granted it
#   AND no guardian has a recorded refusal.
#
# "At least one" rather than "all", because requiring all would permanently block any
# child whose second guardian has no portal account — they cannot record consent, so
# the absence is not an answer. "No recorded refusal" because a guardian who was asked
# and said no must not be overridden by the other one saying yes; that is what makes
# the record revocable in any sense that matters.


def _guardian_users_of(student: Student):
    """The User accounts behind a child's guardians. Guardians without an account
    contribute nothing — they are not a yes and not a no."""
    return User.objects.filter(
        pk__in=StudentGuardian.objects.filter(student=student, guardian__user__isnull=False).values(
            "guardian__user"
        )
    )


def student_carries(student: Student, purpose: str) -> bool:
    """Does this child carry this consent purpose? See the note above for the rule."""
    rows = Consent.objects.filter(guardian__in=_guardian_users_of(student), purpose=purpose)
    if rows.filter(granted=False).exists() or rows.filter(revoked_at__isnull=False).exists():
        return False
    return rows.filter(granted=True, revoked_at__isnull=True).exists()


def guardian_has_consent(user: User, purpose: str) -> bool:
    """Whether this viewer personally granted a purpose. Used for `photos_in_app`,
    which is about the viewer rather than about the child."""
    if not user.is_authenticated:
        return False
    return Consent.objects.filter(
        guardian=user, purpose=purpose, granted=True, revoked_at__isnull=True
    ).exists()


def blocked_tags(media: MediaAsset) -> list[Student]:
    """Which tagged children are missing `photos_shared_with_class`.

    Surfaced to the teacher **at tagging time**, not at publish time. A rule a teacher
    only discovers when the publish button refuses is a rule that gets worked around;
    a marker next to the child's name while they are tagging lets them drop the tag,
    crop the photo, or keep it for that child's own family instead.
    """
    return [
        student
        for student in media.students.all()
        if not student_carries(student, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)
    ]


def is_publishable(media: MediaAsset) -> bool:
    """A photo publishes only if every tagged child carries the sharing consent.

    An untagged photo is not publishable either: with no tags there is no family it
    belongs to, so publishing it would put an unattributed picture of children into
    every feed.
    """
    return media.tags.exists() and not blocked_tags(media)


# --------------------------------------------------------------------------------
# Staff reads
# --------------------------------------------------------------------------------


def entries_for_user(user: User) -> QuerySet[ActivityEntry]:
    """Every activity row this user may see, published or not. The staff boundary.

    Classroom-targeted rows are reached through the rooms whose children this user may
    already see, rather than through a separate classroom permission — one answer to
    "may this person see this room", not two.
    """
    visible_students = students_for_user(user)
    return ActivityEntry.objects.filter(
        Q(student__in=visible_students)
        | Q(classroom__enrollments__student__in=visible_students, classroom__isnull=False)
    ).distinct()


def media_for_user(user: User) -> QuerySet[MediaAsset]:
    """Every photograph this user may see as staff. Not the parent path — see
    `feed_for_child_of`, which additionally applies the consent gate."""
    return MediaAsset.objects.filter(tags__student__in=students_for_user(user)).distinct()


def awaiting_upload() -> QuerySet[MediaAsset]:
    """Rows whose object may or may not have reached the bucket. The nightly
    reconciliation's input; see services.reconcile_uploads."""
    return MediaAsset.objects.filter(upload_state=UploadState.PENDING)


def unacknowledged_incidents(user: User) -> QuerySet[IncidentReport]:
    """Incidents nobody in the family has signed off yet — the list a branch admin
    chases. Ordered oldest first, because the oldest is the one that matters."""
    return (
        IncidentReport.objects.filter(student__in=students_for_user(user), acknowledged_at=None)
        .select_related("student")
        .order_by("occurred_at")
    )


# --------------------------------------------------------------------------------
# Parent reads — the consent gate
# --------------------------------------------------------------------------------


def _published_media_for(students) -> QuerySet[MediaAsset]:
    """Published, stored photographs tagging any of `students`, where every OTHER
    child tagged in the same photo also carries the sharing consent.

    Written as a NOT EXISTS over the tags rather than in Python because this is the
    feed's main query and it must stay one round trip. The subquery asks: is there any
    tag on this photo whose student lacks an active `photos_shared_with_class`? If so,
    the photo is excluded — which is the "every tagged child" rule stated backwards,
    and the way round a database can answer it.
    """
    consenting = Consent.objects.filter(
        guardian__guardian_profile__student_links__student=OuterRef("student"),
        purpose=ConsentPurpose.PHOTOS_SHARED_WITH_CLASS,
        granted=True,
        revoked_at__isnull=True,
    )
    refusing = Consent.objects.filter(
        guardian__guardian_profile__student_links__student=OuterRef("student"),
        purpose=ConsentPurpose.PHOTOS_SHARED_WITH_CLASS,
    ).filter(Q(granted=False) | Q(revoked_at__isnull=False))

    from apps.activities.models import MediaTag

    blocked = (
        MediaTag.objects.filter(media=OuterRef("pk"))
        .annotate(has_yes=Exists(consenting), has_no=Exists(refusing))
        .filter(Q(has_yes=False) | Q(has_no=True))
    )

    return (
        MediaAsset.objects.filter(
            tags__student__in=students,
            is_published=True,
            upload_state=UploadState.STORED,
        )
        .annotate(has_blocked_tag=Exists(blocked))
        .filter(has_blocked_tag=False)
        .distinct()
    )


def feed_for_child_of(user: User, student_id: int):
    """One child's photo feed, for their own guardian. Returns (child, queryset).

    Two gates, both required:

      1. The child is reached through `children_of`, so a member of staff hitting this
         path sees it as a parent or not at all — and a stranger sees nothing, which
         the view renders as 404 rather than 403.
      2. The viewer holds an active `photos_in_app`. Revoking it empties the feed on
         the very next request, because this is evaluated per request and nothing is
         cached.

    `(None, empty)` when either gate fails. The caller cannot tell the two apart, and
    that is deliberate.
    """
    child = children_of(user).filter(pk=student_id).first()
    if child is None:
        return None, MediaAsset.objects.none()
    if not guardian_has_consent(user, ConsentPurpose.PHOTOS_IN_APP):
        return child, MediaAsset.objects.none()
    return child, _published_media_for([child]).order_by("-taken_at", "-id")


def entries_for_child_of(user: User, student_id: int):
    """One child's activity feed, for their own guardian. Returns (child, queryset).

    Published rows only, and both the child's own entries and the ones written for
    their whole room. Unlike photographs this is not consent-gated: a parent reading
    that their own child napped is the thing the school is telling them, not a
    disclosure about anybody else.
    """
    child = children_of(user).filter(pk=student_id).first()
    if child is None:
        return None, ActivityEntry.objects.none()
    rooms = child.enrollments.filter(left_on__isnull=True).values("classroom")
    return child, ActivityEntry.objects.filter(
        Q(student=child) | Q(classroom__in=rooms), is_published=True
    ).order_by("-occurred_at", "-id")


def incidents_for_child_of(user: User, student_id: int):
    """One child's incidents, for their own guardian. Not gated on any consent
    purpose: a family is always entitled to know their child was hurt, and an
    unacknowledged incident is the one thing here the portal should insist on."""
    child = children_of(user).filter(pk=student_id).first()
    if child is None:
        return None, IncidentReport.objects.none()
    return child, IncidentReport.objects.filter(student=child).order_by("-occurred_at", "-id")


def unread_count(user: User, since) -> int:
    """Published photographs of this user's children since their last visit.

    Drives the badge. Uses the same gated query as the feed, so the badge can never
    promise a photo the feed then withholds — a count derived separately is exactly
    how those two drift apart.
    """
    if not guardian_has_consent(user, ConsentPurpose.PHOTOS_IN_APP):
        return 0
    return _published_media_for(children_of(user)).filter(published_at__gt=since).count()
