"""Marking the register and releasing a child, as business logic.

Every test constructs no HttpRequest. The pickup ones matter most: a wrong register
entry is embarrassing, and a wrong pickup record is the other thing entirely.
"""

from datetime import date, time, timedelta

import pytest
from django.db.utils import IntegrityError
from django.utils import timezone

from apps.attendance.models import AttendanceRecord, AttendanceStatus, PickupRecord
from apps.attendance.services import (
    mark,
    mark_all_present,
    mark_holiday,
    release_to_authorized,
    release_to_guardian,
    release_with_override,
)
from apps.people.services import authorize_pickup, create_guardian, enroll_student

pytestmark = pytest.mark.django_db


# --- marking ---------------------------------------------------------------------------


def test_marking_the_same_day_twice_edits_rather_than_duplicates(child, teacher):
    """The plan's Done-when, and the reason (student, date) is unique in the database."""
    today = timezone.localdate()
    mark(student=child, day=today, status=AttendanceStatus.ABSENT, marked_by=teacher)
    mark(student=child, day=today, status=AttendanceStatus.PRESENT, marked_by=teacher)

    assert AttendanceRecord.objects.filter(student=child, date=today).count() == 1
    assert AttendanceRecord.objects.get(student=child, date=today).status == "present"


def test_the_database_refuses_a_duplicate_even_without_the_service(child):
    """Belt and braces. The service upserts; this is what protects the register if
    anything ever writes around it."""
    today = timezone.localdate()
    AttendanceRecord.objects.create(branch=child.branch, student=child, date=today)
    with pytest.raises(IntegrityError):
        AttendanceRecord.objects.create(branch=child.branch, student=child, date=today)


def test_the_room_is_captured_at_marking_time_not_looked_up_later(child, room, other_room, year):
    """A child moved in June must not change which room March says they were in."""
    march = date(2027, 3, 2)
    mark(student=child, day=march)
    enroll_student(student=child, classroom=other_room, academic_year=year)

    assert AttendanceRecord.objects.get(student=child, date=march).classroom == room


def test_mark_all_present_fills_only_the_children_with_nothing_recorded(children, room, teacher):
    """A teacher who has marked three absences and then taps "all present" means "the
    rest are here". Overwriting would erase the work they just did."""
    today = timezone.localdate()
    mark(student=children[0], day=today, status=AttendanceStatus.ABSENT, marked_by=teacher)

    written = mark_all_present(classroom=room, students=children, day=today, marked_by=teacher)

    assert written == 2
    assert AttendanceRecord.objects.get(student=children[0], date=today).status == "absent"
    assert AttendanceRecord.objects.filter(date=today, status="present").count() == 2


def test_mark_all_present_twice_is_harmless(children, room, teacher):
    today = timezone.localdate()
    mark_all_present(classroom=room, students=children, day=today, marked_by=teacher)
    again = mark_all_present(classroom=room, students=children, day=today, marked_by=teacher)

    assert again == 0
    assert AttendanceRecord.objects.filter(date=today).count() == 3


def test_a_holiday_overwrites_because_a_closure_is_not_a_teachers_opinion(children, room, teacher):
    today = timezone.localdate()
    mark(student=children[0], day=today, status=AttendanceStatus.PRESENT, marked_by=teacher)

    mark_holiday(classroom=room, students=children, day=today, reason="Diwali")

    assert AttendanceRecord.objects.filter(date=today, status="holiday").count() == 3


def test_a_late_arrival_keeps_its_time_and_reason(child, teacher):
    record = mark(
        student=child,
        status=AttendanceStatus.LATE,
        arrived_at=time(10, 15),
        reason="Doctor",
        marked_by=teacher,
    )
    # Read back from the database, not from the instance we just built: the point is
    # that the time survives the round trip, not that Python held on to it.
    record.refresh_from_db()
    assert record.status == "late"
    assert record.arrived_at == time(10, 15)
    assert record.reason == "Doctor"


def test_a_late_child_still_counts_as_attended(child):
    """A child who arrived at ten was here. Counting late as absence would make the
    monthly percentage a punishment for traffic."""
    assert mark(student=child, status=AttendanceStatus.LATE).counts_as_attended is True
    assert mark(student=child, status=AttendanceStatus.HALF_DAY).counts_as_attended is True
    assert mark(student=child, status=AttendanceStatus.ABSENT).counts_as_attended is False


# --- the door --------------------------------------------------------------------------


def test_a_child_is_released_to_someone_on_their_list(child, uncle, teacher):
    record = mark(student=child, marked_by=teacher)
    pickup = release_to_authorized(record=record, pickup=uncle, released_by=teacher)

    assert pickup.collected_by == "Rakesh Uncle"
    assert pickup.was_override is False


def test_an_expired_authorisation_cannot_become_a_release(child, guardian, teacher):
    """The screen only offers authorisations valid today — but a screen is a
    suggestion, and a page left open over midnight must not turn into a handover."""
    yesterday = timezone.localdate() - timedelta(days=1)
    expired = authorize_pickup(
        student=child,
        authorized_by=guardian,
        name="Last Friday Uncle",
        relationship="Uncle",
        phone="9876500011",
        valid_from=yesterday - timedelta(days=2),
        valid_to=yesterday,
    )
    record = mark(student=child, marked_by=teacher)

    with pytest.raises(ValueError, match="not authorised"):
        release_to_authorized(record=record, pickup=expired, released_by=teacher)
    assert not PickupRecord.objects.exists()


def test_another_childs_authorisation_cannot_collect_this_one(
    child, children, guardian, teacher, branch
):
    """The nightmare case: two children, one list mixed up at the door."""
    sibling = children[1]
    theirs = authorize_pickup(
        student=sibling,
        authorized_by=guardian,
        name="Someone Else",
        relationship="Neighbour",
        phone="9876500012",
    )
    record = mark(student=child, marked_by=teacher)

    with pytest.raises(ValueError, match="different child"):
        release_to_authorized(record=record, pickup=theirs, released_by=teacher)
    assert not PickupRecord.objects.exists()


def test_a_guardian_who_is_not_linked_cannot_collect(child, branch, teacher):
    stranger = create_guardian(branch=branch, full_name="Not Related", phone="9876500099")
    record = mark(student=child, marked_by=teacher)

    with pytest.raises(ValueError, match="not linked"):
        release_to_guardian(record=record, guardian=stranger, released_by=teacher)


def test_the_parent_who_phones_ahead_is_recorded_as_an_override(child, teacher):
    record = mark(student=child, marked_by=teacher)
    pickup = release_with_override(
        record=record,
        name="Sunita Devi",
        reason="Mother phoned, grandmother collecting today",
        released_by=teacher,
    )

    assert pickup.was_override is True
    assert pickup.collected_by == "Sunita Devi"
    assert "grandmother" in pickup.override_reason


def test_an_override_without_a_reason_is_refused(child, teacher):
    """An override with no reason is indistinguishable from a mistake when it is read
    back, and this is exactly the row somebody reads back."""
    record = mark(student=child, marked_by=teacher)
    with pytest.raises(ValueError, match="name and a reason"):
        release_with_override(record=record, name="Somebody", reason="", released_by=teacher)


def test_the_database_refuses_a_release_to_nobody(child, teacher):
    """The service checks, and so does the table. A pickup row that identifies no one
    is worse than no row: it looks like a record and answers nothing."""
    record = mark(student=child, marked_by=teacher)
    with pytest.raises(IntegrityError):
        PickupRecord.objects.create(branch=child.branch, attendance=record)


def test_correcting_the_door_replaces_the_record_rather_than_adding_one(
    child, uncle, guardian, teacher
):
    record = mark(student=child, marked_by=teacher)
    release_with_override(record=record, name="Wrong Person", reason="mistake", released_by=teacher)
    release_to_authorized(record=record, pickup=uncle, released_by=teacher)

    assert PickupRecord.objects.count() == 1
    pickup = PickupRecord.objects.get()
    assert pickup.collected_by == "Rakesh Uncle"
    assert pickup.override_name == ""
