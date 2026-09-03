"""Marking the register, and releasing a child at the door.

Plain functions that take arguments and own their transactions. They construct no
HttpRequest, which is what lets the whole day's flow be tested without a browser and
called unchanged from the mobile API in Phase 9.

Every write here is an upsert on (student, date). The database has a unique
constraint on that pair, so "marking the same day twice doesn't create duplicates" is
true even if something ever bypasses this module — which is the only kind of true
worth having for a register.
"""

from datetime import date as date_type

from django.db import transaction
from django.utils import timezone

from apps.attendance.models import (
    AttendanceRecord,
    AttendanceStatus,
    PickupRecord,
    StaffAttendance,
)
from apps.core.models import Classroom, User
from apps.people.models import AuthorizedPickup, Guardian, Staff, Student


@transaction.atomic
def mark(
    *,
    student: Student,
    day: date_type | None = None,
    status: str = AttendanceStatus.PRESENT,
    classroom: Classroom | None = None,
    marked_by: User | None = None,
    arrived_at=None,
    left_at=None,
    reason: str = "",
) -> AttendanceRecord:
    """Record one child's day. Marking again edits rather than duplicates.

    The room is captured at marking time and not re-derived later, so a child moved
    to another room in June does not retroactively change which room they were in
    during March.
    """
    day = day or timezone.localdate()
    record, _ = AttendanceRecord.objects.update_or_create(
        student=student,
        date=day,
        defaults={
            "branch": student.branch,
            "classroom": classroom or _current_classroom(student),
            "status": status,
            "arrived_at": arrived_at,
            "left_at": left_at,
            "reason": reason.strip(),
            "marked_by": marked_by,
        },
    )
    return record


@transaction.atomic
def mark_all_present(
    *, classroom: Classroom, students, day: date_type | None = None, marked_by: User | None = None
) -> int:
    """The one-tap start of a morning. Returns how many rows it wrote.

    Deliberately only fills in children with NO record yet. A teacher who has already
    marked three absences and then taps "all present" means "the rest are here" — if
    this overwrote, it would erase the work they just did, which is the fastest way
    to make somebody stop trusting the button.
    """
    day = day or timezone.localdate()
    already = set(
        AttendanceRecord.objects.filter(date=day, student__in=students).values_list(
            "student_id", flat=True
        )
    )
    written = 0
    for student in students:
        if student.pk in already:
            continue
        mark(
            student=student,
            day=day,
            status=AttendanceStatus.PRESENT,
            classroom=classroom,
            marked_by=marked_by,
        )
        written += 1
    return written


@transaction.atomic
def mark_holiday(
    *,
    classroom: Classroom,
    students,
    day: date_type,
    marked_by: User | None = None,
    reason: str = "",
) -> int:
    """A closure applies to the room, so it overwrites — unlike `mark_all_present`.

    A school being shut is not a fact a teacher's earlier tap can contradict.
    """
    for student in students:
        mark(
            student=student,
            day=day,
            status=AttendanceStatus.HOLIDAY,
            classroom=classroom,
            marked_by=marked_by,
            reason=reason,
        )
    return len(students)


@transaction.atomic
def release_to_authorized(
    *, record: AttendanceRecord, pickup: AuthorizedPickup, released_by: User | None = None
) -> PickupRecord:
    """Hand a child over to someone on their list.

    The window is re-checked here rather than trusted from the caller. The screen
    only offers authorisations valid today, but a screen is a suggestion and this is
    a safety record — an expired authorisation must not become a release just because
    a page was left open over midnight.
    """
    if not pickup.is_valid_on(record.date):
        raise ValueError(
            f"{pickup.name} is not authorised to collect "
            f"{record.student.display_name} on {record.date}."
        )
    if pickup.student_id != record.student_id:
        raise ValueError("That authorisation belongs to a different child.")

    return _write_pickup(record, released_by, authorized_pickup=pickup)


@transaction.atomic
def release_to_guardian(
    *, record: AttendanceRecord, guardian: Guardian, released_by: User | None = None
) -> PickupRecord:
    if not record.student.guardian_links.filter(guardian=guardian).exists():
        raise ValueError("That guardian is not linked to this child.")
    return _write_pickup(record, released_by, guardian=guardian)


@transaction.atomic
def release_with_override(
    *, record: AttendanceRecord, name: str, reason: str, released_by: User | None = None
) -> PickupRecord:
    """The parent who phones ahead.

    Both a name and a reason are required, and the database enforces it too. An
    override with no reason is indistinguishable from a mistake when it is read back,
    and this is precisely the row somebody will read back.
    """
    if not name.strip() or not reason.strip():
        raise ValueError("An override needs both a name and a reason.")
    return _write_pickup(
        record, released_by, override_name=name.strip(), override_reason=reason.strip()
    )


@transaction.atomic
def mark_staff(
    *,
    staff: Staff,
    day: date_type | None = None,
    status: str = AttendanceStatus.PRESENT,
    marked_by: User | None = None,
    reason: str = "",
) -> StaffAttendance:
    day = day or timezone.localdate()
    record, _ = StaffAttendance.objects.update_or_create(
        staff=staff,
        date=day,
        defaults={
            "branch": staff.branch,
            "status": status,
            "reason": reason.strip(),
            "marked_by": marked_by,
        },
    )
    return record


# --- internals ------------------------------------------------------------------------


def _current_classroom(student: Student) -> Classroom | None:
    enrollment = (
        student.enrollments.filter(left_on__isnull=True).select_related("classroom").first()
    )
    return enrollment.classroom if enrollment else None


def _write_pickup(record: AttendanceRecord, released_by: User | None, **who) -> PickupRecord:
    """One row per attendance day, replaced if the door is corrected.

    `update_or_create` rather than `create`: a child released to the wrong person and
    corrected two minutes later should end with one record saying what happened, not
    two disagreeing.
    """
    pickup, _ = PickupRecord.objects.update_or_create(
        attendance=record,
        defaults={
            "branch": record.branch,
            "authorized_pickup": None,
            "guardian": None,
            "override_name": "",
            "override_reason": "",
            "released_by": released_by,
            "released_at": timezone.now(),
            **who,
        },
    )
    return pickup
