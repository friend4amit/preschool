"""The numbers on the owner's morning screen, and the rows behind the exports.

This app owns no models. It reads across `people`, `attendance`, `activities` and
`website`, which is why it is its own app rather than a module in `apps/core` — core
is what every other app imports *from*, and a dashboard selector reaching up into
`people` would invert the direction the whole layer contract is built on.

Everything here takes a `user` and scopes through the selectors that already know how
to scope. There is no dashboard-specific definition of "this user's students": the
tile and the screen it links to have to agree, and they agree by sharing a query
rather than by being written carefully twice.

**Two tiles are missing and it is not an oversight.** The phase asks for an unpaid
invoice total and count, and for a fee ledger CSV. Phase 6 has not been built — there
is no Invoice, no Payment — so those are absent rather than stubbed. A tile reading
"0 outstanding" against a schema with no invoices in it is worse than no tile: it is a
confident wrong answer, and the owner has no way to tell it from a true one.
"""

from datetime import date as date_type
from datetime import timedelta

from django.db.models import Count, QuerySet
from django.utils import timezone

from apps.activities.models import MediaAsset, UploadState
from apps.attendance.models import AttendanceRecord, AttendanceStatus
from apps.core import selectors as core_selectors
from apps.core.models import Branch, Classroom, User
from apps.people import selectors as people_selectors
from apps.people.models import Student, StudentStatus
from apps.website import selectors as website_selectors
from apps.website.models import EnquiryStatus

# How far back "recent" reaches on the dashboard. A week, because the screen is opened
# on a Monday as often as any other day and a three-day window would show that Monday
# an empty school.
RECENT_DAYS = 7


def branch_for(user: User) -> Branch | None:
    """The branch this dashboard describes.

    One branch exists today and the switcher stays hidden until branch two
    (docs/plan.md). This returns the user's first membership rather than assuming
    `Branch.objects.first()`, so the day a second branch appears the dashboard is
    already asking the right question and only the switcher is missing.
    """
    return core_selectors.branches_for_user(user).first()


# --------------------------------------------------------------------------------
# Attendance
# --------------------------------------------------------------------------------


def attendance_today(user: User, *, on: date_type | None = None) -> dict:
    """Present, absent and the percentage, for one day.

    `counted` excludes holidays deliberately — a school closed on Monday is not a
    school with 0% attendance, and a rate that drops every public holiday is a rate
    nobody trusts by the third month. `attendance.selectors._attendance_rate` makes
    the same exclusion, because the two mean the same thing rather than by accident.
    """
    day = on or timezone.localdate()
    records = AttendanceRecord.objects.filter(
        student__in=people_selectors.students_for_user(user), date=day
    )
    counts = {row["status"]: row["n"] for row in records.values("status").annotate(n=Count("id"))}

    present = counts.get(AttendanceStatus.PRESENT, 0) + counts.get(AttendanceStatus.LATE, 0)
    half = counts.get(AttendanceStatus.HALF_DAY, 0)
    absent = counts.get(AttendanceStatus.ABSENT, 0)
    counted = present + half + absent

    return {
        "date": day,
        "present": present,
        "half_day": half,
        "absent": absent,
        "counted": counted,
        "rate": round(100 * (present + half) / counted, 1) if counted else None,
        "unmarked": max(enrolled_count(user) - counted, 0),
    }


def absent_today(user: User, *, on: date_type | None = None) -> QuerySet[AttendanceRecord]:
    """Who is not in today. The list, not the number — the office rings these."""
    day = on or timezone.localdate()
    return (
        AttendanceRecord.objects.filter(
            student__in=people_selectors.students_for_user(user),
            date=day,
            status=AttendanceStatus.ABSENT,
        )
        .select_related("student", "classroom")
        .order_by("classroom__name", "student__first_name")
    )


# --------------------------------------------------------------------------------
# Roll
# --------------------------------------------------------------------------------


def enrolled_count(user: User) -> int:
    return people_selectors.students_for_user(user).filter(status=StudentStatus.ENROLLED).count()


def enrolment_trend(user: User, *, months: int = 6, on: date_type | None = None) -> list[dict]:
    """Children who joined and left, month by month, most recent last.

    Joins and leavers rather than a running total, and the distinction matters: a
    total computed from `Enrollment.joined_on` alone would count a child who left last
    March as still enrolled, and the trend would only ever go up. Counting `left_on`
    separately means a month that lost three children says so.
    """
    today = on or timezone.localdate()
    students = people_selectors.students_for_user(user)

    rows = []
    cursor = today.replace(day=1)
    for _ in range(months):
        nxt = (cursor + timedelta(days=32)).replace(day=1)
        rows.append(
            {
                "month": cursor,
                "joined": students.filter(
                    enrollments__joined_on__gte=cursor, enrollments__joined_on__lt=nxt
                )
                .distinct()
                .count(),
                "left": students.filter(
                    enrollments__left_on__gte=cursor, enrollments__left_on__lt=nxt
                )
                .distinct()
                .count(),
            }
        )
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    rows.reverse()
    return rows


# --------------------------------------------------------------------------------
# Enquiries and photographs
# --------------------------------------------------------------------------------


def new_enquiries(user: User):
    """Enquiries nobody has picked up yet.

    The only tile on this dashboard about money coming in, now that the fee ones
    cannot be built. It is also the one with a deadline attached: an enquiry answered
    on day three has usually already chosen another school.
    """
    return website_selectors.enquiries_for_user(user).filter(status=EnquiryStatus.NEW)


def recent_photo_activity(user: User, *, on: date_type | None = None) -> dict:
    """What the teachers have published this week, and what is stuck.

    `pending` is on the dashboard rather than buried in a management command because
    it is the failure a school will not notice on its own: a photograph whose browser
    completed the upload and then failed to tell Django stays `pending` forever and
    never reaches a feed. CLAUDE.md records that `reconcile_uploads` has no schedule
    yet — until it does, this number is the only thing that says so out loud.
    """
    since = (on or timezone.localdate()) - timedelta(days=RECENT_DAYS)
    media = MediaAsset.objects.filter(branch__in=core_selectors.branches_for_user(user))
    return {
        "since": since,
        "published": media.filter(is_published=True, created_at__date__gte=since).count(),
        "awaiting_publish": media.filter(
            is_published=False, upload_state=UploadState.STORED
        ).count(),
        "pending": media.filter(upload_state=UploadState.PENDING).count(),
    }


# --------------------------------------------------------------------------------
# Export rows
# --------------------------------------------------------------------------------


def roster_rows(user: User, *, classroom: Classroom | None = None) -> list[dict]:
    """The student roster, as an export sees it.

    Scoped through `students_for_user` like every screen, because an export is a
    screen that saves to disk. This one carries children's names and guardians' phone
    numbers, so it gets the same cross-family test the screens get — an export view
    taking a classroom id is exactly the shape that leaks.
    """
    students = (
        people_selectors.students_for_user(user)
        .filter(status=StudentStatus.ENROLLED)
        .prefetch_related("guardian_links__guardian", "enrollments__classroom")
        .order_by("first_name", "last_name")
    )
    if classroom is not None:
        students = students.filter(
            enrollments__classroom=classroom, enrollments__left_on__isnull=True
        ).distinct()

    rows = []
    for student in students:
        enrolment = people_selectors.open_enrollment(student)
        links = list(student.guardian_links.all())
        primary = next((link for link in links if link.is_primary), links[0] if links else None)
        rows.append(
            {
                "student": student,
                "classroom": enrolment.classroom if enrolment else None,
                "joined_on": enrolment.joined_on if enrolment else None,
                "guardian": primary.guardian if primary else None,
                "relationship": primary.get_relationship_display() if primary else "",
            }
        )
    return rows


def month_days(year: int, month: int) -> list[date_type]:
    """Every calendar day in the month, including weekends.

    Weekends are kept rather than filtered. Indian preschools run Saturday sessions
    often enough that hiding the column would make the register wrong for them, and a
    Sunday with no records renders as an empty cell, which is what it is.
    """
    first = date_type(year, month, 1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return [first + timedelta(days=n) for n in range((nxt - first).days)]


def month_register(user: User, classroom: Classroom, year: int, month: int) -> list[dict]:
    """A room's month: one row per child, with the mark for every day.

    Its own selector rather than a reuse of `attendance.selectors.classroom_month_report`
    because the register needs the marks day by day, and that report returns only the
    totals. It counts half days as well, which the summary does not — a printed
    register that silently folds `half_day` into `present` is the kind of difference a
    parent notices at the end of term and the school cannot then explain.

    One query for the room's records, not one per child. A class of thirty across a
    31-day month is 930 rows, which is small; doing it per child is thirty round trips
    for the same data.
    """
    roster = people_selectors.roster(classroom.pk, user=user)
    records = AttendanceRecord.objects.filter(
        student__in=roster, date__year=year, date__month=month
    ).values_list("student_id", "date", "status")

    by_student: dict[int, dict[date_type, str]] = {}
    for student_id, day, status in records:
        by_student.setdefault(student_id, {})[day] = status

    rows = []
    for student in roster:
        marks = by_student.get(student.pk, {})
        statuses = list(marks.values())
        counted = sum(1 for s in statuses if s != AttendanceStatus.HOLIDAY)
        present = sum(1 for s in statuses if s == AttendanceStatus.PRESENT)
        late = sum(1 for s in statuses if s == AttendanceStatus.LATE)
        half = sum(1 for s in statuses if s == AttendanceStatus.HALF_DAY)
        absent = sum(1 for s in statuses if s == AttendanceStatus.ABSENT)
        rows.append(
            {
                "student": student,
                "by_day": marks,
                "present": present,
                "late": late,
                "half_day": half,
                "absent": absent,
                "counted": counted,
                # Late and half days count as attended, the same way
                # `attendance.selectors.student_month_summary` counts them. The two
                # reports must not disagree about whether a child came in.
                "rate": (round(100 * (present + late + half) / counted, 1) if counted else None),
            }
        )
    return rows


def classroom_for_user(user: User, classroom_id: int) -> Classroom | None:
    return core_selectors.classrooms_for_user(user).filter(pk=classroom_id).first()


def student_for_user(user: User, student_id: int) -> Student | None:
    return people_selectors.students_for_user(user).filter(pk=student_id).first()
