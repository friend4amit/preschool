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

from datetime import timedelta

from django.db.models import Exists, Max, OuterRef, Q, QuerySet
from django.utils import timezone

from apps.activities.models import (
    ActivityEntry,
    IncidentReport,
    MediaAsset,
    MediaTag,
    UploadState,
)
from apps.core.models import Consent, ConsentPurpose, User
from apps.core.selectors import branches_for_user
from apps.people.models import Student, StudentGuardian
from apps.people.selectors import children_of, roster, students_for_user
from integrations import storage_r2

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
    return child, ActivityEntry.objects.filter(
        Q(student=child) | _room_entries_for(child), is_published=True
    ).order_by("-occurred_at", "-id")


def _room_entries_for(child: Student) -> Q:
    """Room entries from the rooms this child was in AT THE TIME, not the room they
    are in now.

    The obvious version filters `enrollments__left_on__isnull=True` and is wrong: a
    child who moves from Nursery A to Nursery B in June then loses every Nursery A
    entry from March out of their own history, permanently. Enrollment rows are never
    deleted precisely so that history stays answerable — see apps/people/models.py.

    apps.attendance.services.mark already settled this in the other direction, by
    capturing the room at marking time so that "a child moved to another room in June
    does not retroactively change which room they were in during March". Same rule,
    read back: match each enrollment against the window it was open for.

    A child has one enrollment per academic year, so the OR is a handful of clauses
    rather than a join that has to be reasoned about.
    """
    windows = Q()
    found = False
    for classroom_id, joined_on, left_on in child.enrollments.values_list(
        "classroom_id", "joined_on", "left_on"
    ):
        found = True
        clause = Q(classroom_id=classroom_id, occurred_at__date__gte=joined_on)
        if left_on is not None:
            clause &= Q(occurred_at__date__lte=left_on)
        windows |= clause
    # An empty Q() matches EVERYTHING when OR'd into a filter, which would hand a
    # never-enrolled child every room entry in the school.
    return windows if found else Q(pk__in=[])


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


# --------------------------------------------------------------------------------
# Staff day view
# --------------------------------------------------------------------------------


def entries_for_room_on(classroom, day, *, user: User) -> QuerySet[ActivityEntry]:
    """One room's entries for one day — the child-level ones and the room-level ones
    together, which is how the teacher wrote them and how they will be published."""
    return (
        entries_for_user(user)
        .filter(
            Q(student__in=roster(classroom.pk, user=user)) | Q(classroom=classroom),
            occurred_at__date=day,
        )
        .select_related("student", "classroom", "author")
        .order_by("-occurred_at", "-id")
    )


def media_for_room_on(classroom, day, *, user: User) -> QuerySet[MediaAsset]:
    """One room's photographs for one day, tagged or not.

    Untagged ones are included on purpose: a photo nobody has tagged yet is exactly
    what the teacher needs to see on this screen, and filtering it out would hide the
    work still to do.
    """
    children = roster(classroom.pk, user=user)
    return (
        MediaAsset.objects.filter(
            Q(tags__student__in=children) | Q(tags__isnull=True),
            branch=classroom.branch,
            taken_at__date=day,
        )
        .distinct()
        .prefetch_related("tags__student")
        .order_by("-taken_at", "-id")
    )


def media_for_staff(user: User, media_id: int) -> MediaAsset | None:
    """One photograph, or None for the caller to turn into a 404.

    An untagged photo has no student to scope through, so it is reached by branch
    instead. That is the widest this app scopes anything, and it is the price of
    letting a teacher tag a photo they have just uploaded.
    """
    return MediaAsset.objects.filter(branch__in=branches_for_user(user)).filter(pk=media_id).first()


def taggable_students(media: MediaAsset, *, user: User) -> list[dict]:
    """Who the teacher may tag, and whether each one would block publication.

    The blocked marker is computed HERE rather than at publish time, because the plan
    is explicit that a rule a teacher meets only when the publish button refuses is a
    rule that gets worked around. Seeing it beside the name while tagging leaves them
    three good options instead of one dead end.
    """
    tagged = set(media.tags.values_list("student_id", flat=True))
    return [
        {
            "student": student,
            "is_tagged": student.pk in tagged,
            "blocks_publication": not student_carries(
                student, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS
            ),
        }
        for student in students_for_user(user).filter(branch=media.branch)
    ]


# --------------------------------------------------------------------------------
# Serving the bytes
# --------------------------------------------------------------------------------


def media_url(media: MediaAsset, *, prefer_thumbnail: bool = False) -> str | None:
    """A short-lived URL for one photograph, or None when it cannot be served.

    `prefer_thumbnail` asks for the small version and silently falls back to the full
    one when the worker has not been round yet — a feed that showed gaps until a
    background job finished would be a worse feed than one that is briefly heavier.

    ALWAYS call this behind a gate. It does no permission check of its own — by the
    time a caller has a MediaAsset in hand the consent question is already answered,
    and re-answering it here would be a second answer to one question.

    When R2 is unconfigured — which is the development machine, deliberately — this
    returns None and the caller falls back to `media_file`, a Django view that applies
    the same gate and streams from local disk. plan.md's "don't proxy the bytes
    through Django" is about production egress costs on R2, not about a laptop with
    no bucket; the alternative fallback, an unauthenticated /media/ URL, would break
    the one rule this whole app is built around.
    """
    if media.upload_state != UploadState.STORED:
        return None
    if not storage_r2.is_configured():
        return None
    key = media.thumbnail_key if (prefer_thumbnail and media.thumbnail_key) else media.key
    return storage_r2.presign_get(key=key)


def feed_days(media_queryset) -> list[dict]:
    """Group a gated feed into day buckets, newest first, each photo with its URL.

    Grouped in Python over an already-scoped, already-gated queryset rather than with
    a database grouping, because the feed page is small and this keeps the gate as the
    single query it needs to be.

    Each photo carries its storage URL, resolved here rather than in the template:
    templates are display only (see the layer contract), and a template that could
    reach a storage backend would be one that could reach it without passing the gate.

    `url` is None where R2 is unconfigured. Filling that gap is the VIEW's job, not
    this module's — the fallback is a Django route, and `django.urls` below the
    controller layer is exactly what apps/core/tests/test_architecture.py forbids.
    """
    days: list[dict] = []
    for asset in media_queryset:
        day = timezone.localtime(asset.taken_at).date()
        if not days or days[-1]["day"] != day:
            days.append({"day": day, "media": []})
        # The grid renders each of these in a square roughly 180px across. Asking for
        # the thumbnail is the difference between a day of photographs costing a
        # parent a few hundred KB and costing them several megabytes.
        days[-1]["media"].append({"asset": asset, "url": media_url(asset, prefer_thumbnail=True)})
    return days


# --------------------------------------------------------------------------------
# Retention
# --------------------------------------------------------------------------------
#
# Photographs of children accumulate indefinitely by default, which is the wrong
# default under the DPDP Act — the plan calls this out and names "a year after a child
# leaves" as the common answer. The number lives in `settings.MEDIA_RETENTION_DAYS`
# and still wants the school's sign-off; what is decided here is the *shape* of the
# question, which does not depend on the number.
#
# Two rules, deliberately separate because they answer to different facts:
#
#   tagged     a photo expires once EVERY child tagged in it left long enough ago.
#              One child still on the roll keeps the whole photograph, because it is
#              their photograph too.
#   untagged   a photo nobody ever tagged expires on its own age. A year after it was
#              taken it is not waiting to be tagged, it is a picture of children that
#              no rule in this codebase can reason about — which is the worst kind to
#              keep.
#
# Nothing here deletes. These are reads; `services.prune_expired_media` decides, and
# only when a person has read the dry run first.


def departure_date(student: Student):
    """The day a child stopped attending, or None while they are still on the roll.

    None for a child with no enrolment row at all, which reads as "still here" and so
    keeps their photographs. That is the safe direction: retention deletes, and a
    record too thin to answer the question is not permission to answer it as yes.
    """
    dates = list(student.enrollments.values_list("left_on", flat=True))
    if not dates or any(date is None for date in dates):
        return None
    return max(dates)


def students_gone_since(cutoff) -> QuerySet[Student]:
    """Children whose last enrolment ended on or before `cutoff`.

    A child with any open enrolment is excluded by the `Max` being null — a row with
    `left_on IS NULL` propagates, which is exactly the answer wanted and is why this
    is one aggregate rather than two queries.
    """
    return (
        Student.objects.annotate(last_left=Max("enrollments__left_on"))
        .filter(last_left__isnull=False, last_left__lte=cutoff)
        .exclude(enrollments__left_on__isnull=True)
    )


def media_expired_by_retention(*, window_days: int, as_of=None) -> QuerySet[MediaAsset]:
    """Photographs past the retention window, by either rule above.

    Returns a queryset so the caller can count it, page it, or print it without this
    module deciding how much of it fits in memory.
    """
    as_of = as_of or timezone.localdate()
    cutoff = as_of - timedelta(days=window_days)

    gone = students_gone_since(cutoff)
    # Assets every one of whose tags points at a child in `gone`. Stated as "has a
    # tag, and has no tag pointing anywhere else", because SQL can answer that and
    # cannot answer "for all" directly.
    all_tags_expired = (
        MediaAsset.objects.filter(tags__isnull=False)
        .exclude(tags__student__in=Student.objects.exclude(pk__in=gone.values("pk")))
        .values("pk")
    )
    never_tagged = MediaAsset.objects.filter(tags__isnull=True, taken_at__date__lte=cutoff).values(
        "pk"
    )

    return MediaAsset.objects.filter(Q(pk__in=all_tags_expired) | Q(pk__in=never_tagged)).order_by(
        "taken_at", "pk"
    )
