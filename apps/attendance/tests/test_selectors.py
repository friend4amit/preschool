"""Who may read whose register, and whether the sums are right.

The scoping tests here are the same shape as the ones in `apps/people`: a register is
just as much a leak as a student record, and a teacher at branch two reading branch
one's morning is the same failure wearing a different hat.
"""

from datetime import date

import pytest

from apps.attendance.models import AttendanceStatus
from apps.attendance.selectors import (
    classroom_for_user,
    classroom_month_report,
    day_sheet,
    month_for_child_of,
    records_for_user,
    student_month_summary,
    unmarked_count,
)
from apps.attendance.services import mark, mark_all_present
from apps.core.models import Classroom, Role, User
from apps.core.services import grant_membership

pytestmark = pytest.mark.django_db


# --- scoping ---------------------------------------------------------------------------


def test_a_parent_cannot_read_another_familys_attendance(children, guardian, parent, teacher):
    """The keep-forever rule from plan.md, applied to the register."""
    for kid in children:
        mark(student=kid, marked_by=teacher)

    visible = records_for_user(parent)
    assert visible.count() == 1
    assert visible.get().student == children[0]


def test_staff_at_another_branch_see_no_records(children, other_branch, teacher):
    for kid in children:
        mark(student=kid, marked_by=teacher)

    outsider = User.objects.create_user(phone="9100000099")
    grant_membership(user=outsider, branch=other_branch, role=Role.TEACHER)

    assert records_for_user(outsider).count() == 0


def test_a_room_at_another_branch_cannot_be_opened_by_guessing_its_id(other_branch, teacher):
    theirs = Classroom.objects.create(branch=other_branch, name="Their Room")
    assert classroom_for_user(teacher, theirs.pk) is None


def test_an_anonymous_visitor_sees_nothing(children, teacher):
    from django.contrib.auth.models import AnonymousUser

    mark(student=children[0], marked_by=teacher)
    assert records_for_user(AnonymousUser()).count() == 0


# --- the day sheet ---------------------------------------------------------------------


def test_the_sheet_lists_unmarked_children_too(children, room, teacher):
    """A list of only the marked children would hide exactly the ones a teacher is
    looking for."""
    mark(student=children[0], classroom=room, marked_by=teacher)

    sheet = day_sheet(room, date.today(), user=teacher)
    assert len(sheet) == 3
    assert sheet[0]["record"] is not None
    assert [row["record"] for row in sheet].count(None) == 2


def test_unmarked_count_is_what_a_teacher_checks_before_putting_the_phone_away(
    children, room, teacher
):
    today = date.today()
    assert unmarked_count(room, today, user=teacher) == 3

    mark_all_present(classroom=room, students=children, day=today, marked_by=teacher)
    assert unmarked_count(room, today, user=teacher) == 0


def test_the_sheet_does_not_show_a_child_from_another_room(children, room, other_room, teacher):
    sheet = day_sheet(other_room, date.today(), user=teacher)
    assert sheet == []


# --- the sums --------------------------------------------------------------------------


def test_a_holiday_is_excluded_from_both_halves_of_the_percentage(child, teacher):
    """A school closure is not a child's absence. Counting it as one makes every
    percentage wrong in December."""
    mark(student=child, day=date(2026, 12, 1), status=AttendanceStatus.PRESENT)
    mark(student=child, day=date(2026, 12, 2), status=AttendanceStatus.HOLIDAY)
    mark(student=child, day=date(2026, 12, 3), status=AttendanceStatus.ABSENT)

    summary = student_month_summary(child, 2026, 12)
    assert summary["counted"] == 2
    assert summary["present"] == 1
    assert summary["rate"] == 50.0


def test_late_and_half_days_count_as_attended_in_the_percentage(child):
    mark(student=child, day=date(2026, 12, 1), status=AttendanceStatus.LATE)
    mark(student=child, day=date(2026, 12, 2), status=AttendanceStatus.HALF_DAY)

    assert student_month_summary(child, 2026, 12)["rate"] == 100.0


def test_a_month_with_no_records_has_no_rate_rather_than_zero(child):
    """Zero would put a red number against a child who did nothing wrong."""
    assert student_month_summary(child, 2026, 12)["rate"] is None


def test_the_classroom_report_puts_the_worst_attendance_first(children, room, teacher):
    """The reason anyone opens this report is to find the child who has stopped
    coming. Alphabetical order buries them."""
    mark(student=children[0], day=date(2026, 12, 1), status=AttendanceStatus.PRESENT)
    mark(student=children[1], day=date(2026, 12, 1), status=AttendanceStatus.ABSENT)

    rows = classroom_month_report(room, 2026, 12, user=teacher)
    with_rate = [r for r in rows if r["rate"] is not None]
    assert with_rate[0]["student"] == children[1]
    assert with_rate[0]["rate"] == 0.0


# --- the parent view -------------------------------------------------------------------


def test_a_parent_reads_their_own_childs_month(child, guardian, parent, teacher):
    mark(student=child, day=date(2026, 12, 1), marked_by=teacher)

    found, records = month_for_child_of(parent, child.pk, 2026, 12)
    assert found == child
    assert records.count() == 1


def test_a_parent_asking_for_another_childs_month_gets_nothing(children, guardian, parent):
    """None, which the view turns into a 404 — never a 403, which would confirm the
    child exists."""
    other_child = children[1]
    found, records = month_for_child_of(parent, other_child.pk, 2026, 12)

    assert found is None
    assert records.count() == 0
