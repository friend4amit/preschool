"""The register through HTTP.

The selector tests already prove the scoping. These prove the views apply it — the
same rule can be right in `selectors.py` and bypassed by a view that fetches its own
object, and this file is what stops that.

The htmx pair is here too: one request with `HX-Request` asserting a bare row comes
back, one without asserting the whole page. Both come from the same view and the same
form, which is what makes "it works with JavaScript off" true rather than aspirational.
"""

from datetime import date, timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.attendance.models import AttendanceRecord, PickupRecord
from apps.attendance.services import mark
from apps.core.models import Classroom, Role, User
from apps.core.services import grant_membership
from apps.people.services import authorize_pickup

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client: Client, teacher) -> Client:
    client.force_login(teacher)
    return client


@pytest.fixture
def family(client: Client, guardian, parent) -> Client:
    client.force_login(parent)
    return client


# --- who may open the register ---------------------------------------------------------


def test_a_parent_cannot_open_the_register(family, room):
    response = family.get(reverse("attendance_day", args=[room.pk]))
    assert response.status_code == 302
    assert reverse("login") in response.url


def test_a_signed_out_visitor_cannot_open_the_register(client, room):
    assert client.get(reverse("attendance_day", args=[room.pk])).status_code == 302


def test_a_teacher_at_another_branch_gets_404_not_403(client, other_branch, room):
    """404, never 403: a 403 confirms the room exists, which tells somebody walking
    ids that they guessed a real one."""
    outsider = User.objects.create_user(phone="9100000098")
    grant_membership(user=outsider, branch=other_branch, role=Role.TEACHER)
    client.force_login(outsider)

    response = client.get(reverse("attendance_day", args=[room.pk]))
    assert response.status_code == 404
    assert response.status_code != 403


def test_marking_a_child_from_another_branch_is_refused(client, other_branch, room, child):
    outsider = User.objects.create_user(phone="9100000097")
    grant_membership(user=outsider, branch=other_branch, role=Role.TEACHER)
    client.force_login(outsider)

    response = client.post(
        reverse("attendance_mark", args=[room.pk, child.pk]), {"status": "present"}
    )
    assert response.status_code == 404
    assert not AttendanceRecord.objects.exists()


# --- the grid --------------------------------------------------------------------------


def test_the_grid_lists_every_child_in_the_room(staff, room, children):
    content = staff.get(reverse("attendance_day", args=[room.pk])).content.decode()
    for kid in children:
        assert kid.display_name in content
    # The count and its label sit in separate spans, so assert on the button copy,
    # which is one string and is also the thing a teacher actually taps.
    assert "Mark the remaining 3 present" in content
    assert "Not marked" in content


def test_one_tap_marks_a_child(staff, room, child, teacher):
    response = staff.post(
        reverse("attendance_mark", args=[room.pk, child.pk]), {"status": "present"}
    )
    assert response.status_code == 302
    record = AttendanceRecord.objects.get(student=child)
    assert record.status == "present"
    assert record.marked_by == teacher


def test_htmx_gets_one_row_back_and_everyone_else_gets_the_page(staff, room, child):
    """The progressive-enhancement contract in one pair of assertions."""
    url = reverse("attendance_mark", args=[room.pk, child.pk])

    swapped = staff.post(url, {"status": "present"}, headers={"HX-Request": "true"})
    assert swapped.status_code == 200
    assert b"<html" not in swapped.content
    assert f'id="row-{child.pk}"'.encode() in swapped.content

    plain = staff.post(url, {"status": "absent"})
    assert plain.status_code == 302


def test_mark_all_present_leaves_the_exceptions_alone(staff, room, children, teacher):
    mark(student=children[0], status="absent", marked_by=teacher)

    staff.post(reverse("attendance_all_present", args=[room.pk]))

    assert AttendanceRecord.objects.get(student=children[0]).status == "absent"
    assert AttendanceRecord.objects.filter(status="present").count() == 2


def test_a_bad_date_in_the_url_shows_today_rather_than_a_stack_trace(staff, room):
    response = staff.get(reverse("attendance_day", args=[room.pk]), {"date": "not-a-date"})
    assert response.status_code == 200
    assert timezone.localdate().strftime("%d %B %Y").lstrip("0") in response.content.decode()


def test_a_past_day_is_marked_as_not_today(staff, room):
    yesterday = timezone.localdate() - timedelta(days=1)
    content = staff.get(
        reverse("attendance_day", args=[room.pk]), {"date": yesterday.isoformat()}
    ).content.decode()
    assert "not today" in content


def test_the_medical_flag_follows_the_child_onto_the_register(staff, room, child):
    """The person holding a snack is the person marking this row."""
    child.allergies = "Peanuts"
    child.save(update_fields=["allergies"])
    assert b"Medical" in staff.get(reverse("attendance_day", args=[room.pk])).content


# --- the door --------------------------------------------------------------------------


def test_the_pickup_screen_offers_only_this_childs_authorised_adults(
    staff, child, children, guardian, uncle, teacher
):
    other = authorize_pickup(
        student=children[1],
        authorized_by=guardian,
        name="Not For Aarav",
        relationship="Neighbour",
        phone="9876500055",
    )
    record = mark(student=child, marked_by=teacher)

    content = staff.get(reverse("attendance_pickup", args=[record.pk])).content.decode()
    assert uncle.name in content
    assert other.name not in content


def test_releasing_to_an_authorised_person_records_it(staff, child, uncle, teacher):
    record = mark(student=child, marked_by=teacher)
    response = staff.post(
        reverse("attendance_pickup", args=[record.pk]), {"collected_by": f"pickup:{uncle.pk}"}
    )
    assert response.status_code == 302
    assert PickupRecord.objects.get().collected_by == "Rakesh Uncle"


def test_an_override_without_a_reason_is_refused_by_the_form(staff, child, teacher):
    record = mark(student=child, marked_by=teacher)
    response = staff.post(
        reverse("attendance_pickup", args=[record.pk]),
        {"collected_by": "override", "override_name": "Somebody", "override_reason": ""},
    )
    assert response.status_code == 200
    assert b"who authorised this" in response.content
    assert not PickupRecord.objects.exists()


def test_a_posted_id_for_another_childs_authorisation_is_refused(
    staff, child, children, guardian, teacher
):
    """The select box was built from scoped choices, but a POST is not a select box."""
    theirs = authorize_pickup(
        student=children[1],
        authorized_by=guardian,
        name="Someone Else",
        relationship="Neighbour",
        phone="9876500056",
    )
    record = mark(student=child, marked_by=teacher)

    response = staff.post(
        reverse("attendance_pickup", args=[record.pk]), {"collected_by": f"pickup:{theirs.pk}"}
    )
    assert response.status_code == 200
    assert not PickupRecord.objects.exists()


def test_a_child_with_nobody_on_file_says_so_loudly(staff, child, teacher):
    """A child with no guardian and no authorisation is not a form to fill in — it is
    a phone call to make, and the screen has to say that."""
    record = mark(student=child, marked_by=teacher)
    content = staff.get(reverse("attendance_pickup", args=[record.pk])).content.decode()
    assert "Nobody is on file for this child" in content


# --- reports and the parent view -------------------------------------------------------


def test_the_report_shows_a_percentage(staff, room, child, teacher):
    mark(student=child, day=date(2026, 12, 1), status="present", marked_by=teacher)
    mark(student=child, day=date(2026, 12, 2), status="absent", marked_by=teacher)

    content = staff.get(
        reverse("attendance_report", args=[room.pk]), {"year": 2026, "month": 12}
    ).content.decode()
    assert "50.0%" in content


def test_a_parent_sees_their_own_childs_month(family, child, teacher):
    mark(student=child, day=date(2026, 12, 1), status="present", marked_by=teacher)

    response = family.get(
        reverse("my_child_attendance", args=[child.pk]), {"year": 2026, "month": 12}
    )
    assert response.status_code == 200
    assert b"100.0%" in response.content


def test_a_parent_asking_for_another_familys_attendance_gets_404(family, children):
    """The keep-forever rule, applied to the register."""
    response = family.get(reverse("my_child_attendance", args=[children[1].pk]))
    assert response.status_code == 404
    assert response.status_code != 403


def test_a_month_with_no_records_does_not_show_a_zero(family, child):
    """Zero would put a red number against a child who did nothing wrong."""
    content = family.get(
        reverse("my_child_attendance", args=[child.pk]), {"year": 2026, "month": 12}
    ).content.decode()
    assert "0.0%" not in content
    assert "Nothing recorded" in content


def test_a_room_with_nobody_in_it_says_so(staff, other_room):
    content = staff.get(reverse("attendance_day", args=[other_room.pk])).content.decode()
    assert "Nobody is enrolled" in content


def test_the_register_reaches_a_room_without_being_told_which(staff, room):
    """A teacher opening this has one room and one question."""
    response = staff.get(reverse("attendance_today"))
    assert response.status_code == 302
    assert str(room.pk) in response.url or str(Classroom.objects.first().pk) in response.url
