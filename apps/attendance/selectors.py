"""Reads for the register, and the scoping that decides who may see whose day.

Everything here composes with `apps.people.selectors.students_for_user`, which is
already the one place answering "may this person see this child". Re-deriving that
rule here would be a second answer to the same question, and second answers are how
the two drift apart.

Nothing here knows what HTTP is. The view turns an empty result into a 404.
"""

from datetime import date as date_type
from datetime import timedelta

from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.attendance.models import AttendanceRecord, AttendanceStatus, StaffAttendance
from apps.core.models import Classroom, Role, User
from apps.core.selectors import branches_for_user, classrooms_for_user
from apps.people.models import Student
from apps.people.selectors import children_of, roster, students_for_user


def classroom_for_user(user: User, classroom_id: int) -> Classroom | None:
    """One room, or None. The caller turns None into a 404 — a teacher at branch one
    must not learn that branch two's room ids exist."""
    return classrooms_for_user(user).filter(pk=classroom_id).first()


def records_for_user(user: User) -> QuerySet[AttendanceRecord]:
    """Every attendance row this user may see. The security boundary of this app."""
    return AttendanceRecord.objects.filter(student__in=students_for_user(user))


def day_sheet(classroom: Classroom, day: date_type, *, user: User) -> list[dict]:
    """The register for one room on one day: every enrolled child, with their record
    if one exists.

    Returns children who have no record yet as well, because the grid's job is to
    show who has not been marked — a list of only the marked children would hide
    exactly the ones a teacher is looking for.
    """
    children = list(roster(classroom.pk, user=user).order_by("first_name", "last_name"))
    existing = {
        record.student_id: record
        for record in AttendanceRecord.objects.filter(
            classroom=classroom, date=day, student__in=children
        ).select_related("student")
    }
    return [{"student": child, "record": existing.get(child.pk)} for child in children]


def unmarked_count(classroom: Classroom, day: date_type, *, user: User) -> int:
    """How many children still have nothing recorded. The number a teacher checks
    before putting the phone away."""
    return sum(1 for row in day_sheet(classroom, day, user=user) if row["record"] is None)


def month_for_student(student: Student, year: int, month: int) -> QuerySet[AttendanceRecord]:
    """One child's month, oldest first — the order a calendar reads in."""
    return AttendanceRecord.objects.filter(
        student=student, date__year=year, date__month=month
    ).order_by("date")


def month_for_child_of(user: User, student_id: int, year: int, month: int):
    """The parent portal's view. Scoped through `children_of`, not
    `students_for_user`: this is a parent looking at their own child, and a teacher
    reaching it should see it as a parent or not at all."""
    child = children_of(user).filter(pk=student_id).first()
    if child is None:
        return None, AttendanceRecord.objects.none()
    return child, month_for_student(child, year, month)


def _attendance_rate(present: int, counted: int) -> float | None:
    """None rather than zero when nothing was counted.

    A month with no school days is not a month with 0% attendance, and rendering it
    as one would put a red number against a child who did nothing wrong.
    """
    return round(present / counted * 100, 1) if counted else None


def student_month_summary(student: Student, year: int, month: int) -> dict:
    counts = month_for_student(student, year, month).aggregate(
        counted=Count("pk", filter=~Q(status=AttendanceStatus.HOLIDAY)),
        present=Count(
            "pk",
            filter=Q(
                status__in=[
                    AttendanceStatus.PRESENT,
                    AttendanceStatus.LATE,
                    AttendanceStatus.HALF_DAY,
                ]
            ),
        ),
        absent=Count("pk", filter=Q(status=AttendanceStatus.ABSENT)),
        late=Count("pk", filter=Q(status=AttendanceStatus.LATE)),
    )
    counts["rate"] = _attendance_rate(counts["present"], counts["counted"])
    return counts


def classroom_month_report(
    classroom: Classroom, year: int, month: int, *, user: User
) -> list[dict]:
    """Every child in the room with their percentage for the month, worst first.

    Worst first because the reason anyone opens this report is to find the child who
    has stopped coming, and sorting alphabetically buries them.
    """
    rows = [
        {"student": child, **student_month_summary(child, year, month)}
        for child in roster(classroom.pk, user=user)
    ]
    rows.sort(key=lambda r: (r["rate"] is not None, r["rate"] if r["rate"] is not None else 0))
    return rows


def staff_day(branch, day: date_type) -> QuerySet[StaffAttendance]:
    return StaffAttendance.objects.filter(branch=branch, date=day).select_related("staff__user")


def staff_records_for_user(user: User) -> QuerySet[StaffAttendance]:
    if not user.is_authenticated:
        return StaffAttendance.objects.none()
    return StaffAttendance.objects.filter(branch__in=branches_for_user(user))


def recent_days(day: date_type, count: int = 7) -> list[date_type]:
    """The last few dates, newest first — for the date switcher on the grid."""
    return [day - timedelta(days=offset) for offset in range(count)]


# A teacher who forgets to mark until the next morning is ordinary; a teacher editing
# last month is a correction, and corrections are the branch admin's call. One day is
# the line, and it is a judgement rather than a rule handed down by the plan — moving
# it is a one-line change here.
BACKDATE_WINDOW_DAYS = 1


def may_mark_on(user: User, day: date_type) -> bool:
    """Whether this user may write a register for this date.

    Nobody marks the future: a register is a record of what happened, and a tap made
    in advance is a guess that will be read later as a fact.
    """
    if not user.is_authenticated:
        return False

    today = timezone.localdate()
    if day > today:
        return False
    if (today - day).days <= BACKDATE_WINDOW_DAYS:
        return True

    return user.is_superuser or user.memberships.filter(role=Role.BRANCH_ADMIN).exists()
