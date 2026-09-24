"""The numbers behind the dashboard.

Two things these tests are really guarding. The first is scope: every count is
`students_for_user`-shaped, and a branch that leaks into a total is the same bug as a
branch that leaks into a screen. The second is the attendance rate's definition —
holidays out of the denominator, late and half days counted as attended — because a
rate the office disagrees with is a rate nobody looks at twice.
"""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.attendance.models import AttendanceStatus
from apps.attendance.services import mark
from apps.reports import selectors

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------------
# Attendance
# --------------------------------------------------------------------------------


def test_nothing_marked_is_not_zero_percent(admin_user, child_a):
    """An empty morning is "no answer yet", not "nobody came". A dashboard that opens
    at 0% every day before the register is taken trains its reader to ignore it."""
    today = selectors.attendance_today(admin_user)
    assert today["rate"] is None
    assert today["unmarked"] == 1


def test_the_rate_counts_late_and_half_days_as_attended(admin_user, child_a, child_b):
    mark(student=child_a, status=AttendanceStatus.LATE)
    mark(student=child_b, status=AttendanceStatus.HALF_DAY)

    today = selectors.attendance_today(admin_user)
    assert today["rate"] == 100.0
    assert today["absent"] == 0


def test_a_holiday_is_not_an_absence(admin_user, child_a, child_b):
    """The whole reason `counted` exists. A school shut on Monday is not a school at
    0%, and a rate that drops every public holiday is one nobody trusts."""
    mark(student=child_a, status=AttendanceStatus.HOLIDAY)
    mark(student=child_b, status=AttendanceStatus.PRESENT)

    today = selectors.attendance_today(admin_user)
    assert today["counted"] == 1
    assert today["rate"] == 100.0


def test_another_branch_is_not_counted(admin_user, child_a, other_child):
    mark(student=other_child, status=AttendanceStatus.ABSENT)
    today = selectors.attendance_today(admin_user)

    assert today["absent"] == 0
    assert selectors.enrolled_count(admin_user) == 1


def test_absent_today_lists_the_children_to_ring(admin_user, child_a, child_b):
    mark(student=child_a, status=AttendanceStatus.ABSENT, reason="Fever")
    mark(student=child_b, status=AttendanceStatus.PRESENT)

    absent = list(selectors.absent_today(admin_user))
    assert [r.student for r in absent] == [child_a]
    assert absent[0].reason == "Fever"


def test_absent_today_does_not_cross_branches(admin_user, other_child):
    mark(student=other_child, status=AttendanceStatus.ABSENT)
    assert selectors.absent_today(admin_user).count() == 0


# --------------------------------------------------------------------------------
# The roll
# --------------------------------------------------------------------------------


def test_the_trend_counts_joins_and_leavers_separately(admin_user, child_a, room, year):
    """A running total from `joined_on` alone would only ever go up. The month a child
    leaves has to say so."""
    enrolment = child_a.enrollments.get()
    enrolment.left_on = timezone.localdate()
    enrolment.save(update_fields=["left_on"])

    trend = selectors.enrolment_trend(admin_user, months=1)
    assert trend[-1]["left"] == 1


def test_the_trend_ends_with_this_month(admin_user):
    trend = selectors.enrolment_trend(admin_user, months=6)
    assert len(trend) == 6
    assert trend[-1]["month"] == timezone.localdate().replace(day=1)
    assert trend[0]["month"] < trend[-1]["month"]


# --------------------------------------------------------------------------------
# The month register
# --------------------------------------------------------------------------------


def test_month_days_covers_the_whole_month_including_weekends(admin_user):
    days = selectors.month_days(2026, 2)
    assert days[0] == date(2026, 2, 1)
    assert days[-1] == date(2026, 2, 28)


def test_the_register_marks_the_day_a_child_was_absent(admin_user, room, child_a):
    day = timezone.localdate()
    mark(student=child_a, day=day, status=AttendanceStatus.ABSENT)

    rows = selectors.month_register(admin_user, room, day.year, day.month)
    assert rows[0]["by_day"][day] == AttendanceStatus.ABSENT
    assert rows[0]["absent"] == 1
    assert rows[0]["rate"] == 0.0


def test_the_register_counts_half_days(admin_user, room, child_a):
    """`attendance.selectors.student_month_summary` does not report half days at all,
    which is why this selector exists rather than reusing it. A printed register that
    silently folds them into "present" is a difference a parent spots at the end of
    term and the school cannot then explain."""
    day = timezone.localdate()
    mark(student=child_a, day=day, status=AttendanceStatus.HALF_DAY)

    rows = selectors.month_register(admin_user, room, day.year, day.month)
    assert rows[0]["half_day"] == 1
    assert rows[0]["present"] == 0


def test_a_child_with_no_records_has_no_rate(admin_user, room, child_a):
    today = timezone.localdate()
    rows = selectors.month_register(admin_user, room, today.year, today.month)
    assert rows[0]["rate"] is None


# --------------------------------------------------------------------------------
# Roster rows
# --------------------------------------------------------------------------------


def test_roster_rows_carry_the_primary_guardian(admin_user, child_a):
    rows = selectors.roster_rows(admin_user)
    assert len(rows) == 1
    assert rows[0]["guardian"].full_name == "Priya Sharma"
    assert rows[0]["classroom"].name == "Nursery A"


def test_roster_rows_never_cross_a_branch(admin_user, child_a, other_child):
    rows = selectors.roster_rows(admin_user)
    assert [row["student"] for row in rows] == [child_a]


def test_roster_rows_filter_to_one_room(admin_user, child_a, room, branch, year):
    from apps.core.models import Classroom
    from apps.people.services import create_student, enroll_student

    elsewhere = Classroom.objects.create(branch=branch, name="Playgroup B", capacity=10)
    other = create_student(branch=branch, first_name="Ishaan", date_of_birth=date(2023, 1, 1))
    enroll_student(student=other, classroom=elsewhere, academic_year=year)

    rows = selectors.roster_rows(admin_user, classroom=room)
    assert [row["student"] for row in rows] == [child_a]


def test_a_child_who_left_is_off_the_roster(admin_user, child_a):
    from apps.people.models import StudentStatus

    child_a.status = StudentStatus.LEFT
    child_a.save(update_fields=["status"])

    assert selectors.roster_rows(admin_user) == []
    assert selectors.enrolled_count(admin_user) == 0


# --------------------------------------------------------------------------------
# Photographs
# --------------------------------------------------------------------------------


def test_stuck_uploads_are_counted(admin_user, branch, child_a):
    """The number nothing else in the product surfaces. `reconcile_uploads` fixes these
    but has no schedule yet, so the dashboard is where a school finds out."""
    from apps.activities.models import MediaAsset, UploadState

    MediaAsset.objects.create(branch=branch, key="a.jpg", upload_state=UploadState.PENDING)
    MediaAsset.objects.create(
        branch=branch, key="b.jpg", upload_state=UploadState.STORED, is_published=True
    )

    photos = selectors.recent_photo_activity(admin_user)
    assert photos["pending"] == 1
    assert photos["published"] == 1


def test_photo_counts_do_not_cross_a_branch(admin_user, other_branch):
    from apps.activities.models import MediaAsset, UploadState

    MediaAsset.objects.create(
        branch=other_branch, key="theirs.jpg", upload_state=UploadState.PENDING
    )
    assert selectors.recent_photo_activity(admin_user)["pending"] == 0


def test_published_photos_older_than_the_window_are_not_recent(admin_user, branch):
    from apps.activities.models import MediaAsset, UploadState

    old = MediaAsset.objects.create(
        branch=branch, key="old.jpg", upload_state=UploadState.STORED, is_published=True
    )
    MediaAsset.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=selectors.RECENT_DAYS + 2)
    )
    assert selectors.recent_photo_activity(admin_user)["published"] == 0
