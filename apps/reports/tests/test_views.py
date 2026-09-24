"""The dashboard, the register, and the files that leave the building.

An export is a screen that saves to disk, so it gets the same tests a screen gets: a
parent cannot open it, another branch's staff cannot open it, and an id the user is
not entitled to is a 404 rather than a 403. The roster CSV carries children's names
and guardians' phone numbers, which is why those tests are here and not "obvious".
"""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.attendance.models import AttendanceStatus
from apps.attendance.services import mark

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------------


def test_the_dashboard_renders(client, admin_user, child_a):
    mark(student=child_a, status=AttendanceStatus.ABSENT)
    client.force_login(admin_user)
    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    assert response.context["enrolled"] == 1
    assert b"Aarav" in response.content


def test_the_dashboard_says_fees_are_not_built_rather_than_showing_a_zero(client, admin_user):
    """A "0 outstanding" tile against a schema with no invoices is a confident wrong
    answer. The phase is built out of order, and the screen has to admit it."""
    client.force_login(admin_user)
    response = client.get(reverse("dashboard")).content.decode()

    assert "Phase 6" in response
    assert "would read as" in response


def test_a_parent_cannot_open_the_dashboard(client, child_a):
    parent = child_a.guardian_links.get().guardian.user
    client.force_login(parent)
    assert client.get(reverse("dashboard")).status_code == 302


def test_an_admin_lands_on_the_dashboard_after_signing_in(client, admin_user):
    client.force_login(admin_user)
    response = client.get(reverse("after_login"))
    assert response.status_code == 302
    assert response.url == reverse("dashboard")


def test_a_teacher_still_lands_on_their_students(client, branch):
    """Deliberately not the dashboard. A teacher's morning is a room and a register,
    and a school-wide attendance percentage is not something they can act on."""
    from apps.core.models import Role, User
    from apps.core.services import grant_membership

    teacher = User.objects.create_user(phone="9100000031", full_name="Meera Nair")
    grant_membership(user=teacher, branch=branch, role=Role.TEACHER)

    client.force_login(teacher)
    assert client.get(reverse("after_login")).url == reverse("student_list")


# --------------------------------------------------------------------------------
# Roster CSV
# --------------------------------------------------------------------------------


def test_the_roster_csv_downloads(client, admin_user, child_a):
    client.force_login(admin_user)
    response = client.get(reverse("roster_csv"))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]

    body = response.content.decode("utf-8-sig")
    assert "Aarav" in body
    assert "9876500001" in body


def test_the_roster_csv_starts_with_a_bom(client, admin_user, child_a):
    """Without it Excel on Windows reads a UTF-8 CSV as the system codepage, and every
    name with a Devanagari character comes out as mojibake. The school opens these in
    Excel, so the file is written for Excel."""
    client.force_login(admin_user)
    assert client.get(reverse("roster_csv")).content.startswith(b"\xef\xbb\xbf")


def test_the_roster_csv_never_carries_another_branch(client, admin_user, child_a, other_child):
    client.force_login(admin_user)
    body = client.get(reverse("roster_csv")).content.decode("utf-8-sig")

    assert "Aarav" in body
    assert "Zoya" not in body
    assert "9876500003" not in body


def test_a_classroom_from_another_branch_is_a_404(client, admin_user, other_room):
    """The shape that leaks: an export view taking a classroom id. 404, not 403 —
    a 403 confirms the room exists."""
    client.force_login(admin_user)
    response = client.get(f"{reverse('roster_csv')}?classroom={other_room.pk}")
    assert response.status_code == 404


def test_a_junk_classroom_id_is_a_404_not_a_500(client, admin_user):
    client.force_login(admin_user)
    assert client.get(f"{reverse('roster_csv')}?classroom=abc").status_code == 404


def test_a_parent_cannot_download_the_roster(client, child_a):
    parent = child_a.guardian_links.get().guardian.user
    client.force_login(parent)
    assert client.get(reverse("roster_csv")).status_code == 302


def test_an_anonymous_visitor_cannot_download_the_roster(client, child_a):
    assert client.get(reverse("roster_csv")).status_code == 302


# --------------------------------------------------------------------------------
# Attendance exports
# --------------------------------------------------------------------------------


def test_the_attendance_csv_downloads(client, admin_user, room, child_a):
    mark(student=child_a, status=AttendanceStatus.PRESENT)
    client.force_login(admin_user)
    response = client.get(reverse("attendance_csv", args=[room.pk]))

    assert response.status_code == 200
    body = response.content.decode("utf-8-sig")
    assert "Aarav" in body
    assert "100.0" in body


def test_another_branchs_register_is_a_404(client, admin_user, other_room):
    client.force_login(admin_user)
    assert client.get(reverse("attendance_csv", args=[other_room.pk])).status_code == 404
    assert client.get(reverse("attendance_register", args=[other_room.pk])).status_code == 404


def test_the_printable_register_renders_a_column_per_day(client, admin_user, room, child_a):
    day = timezone.localdate()
    mark(student=child_a, day=day, status=AttendanceStatus.PRESENT)

    client.force_login(admin_user)
    response = client.get(f"{reverse('attendance_register', args=[room.pk])}?month={day:%Y-%m}")

    assert response.status_code == 200
    assert len(response.context["days"]) >= 28
    assert response.context["rows"][0]["marks"][day.day - 1] == "P"


def test_the_register_ignores_a_junk_month_rather_than_failing(client, admin_user, room):
    """Same forgiving read as `activities.views._day_from`. A bookmarked URL with a
    stale query string should show this month, not a 500."""
    client.force_login(admin_user)
    response = client.get(f"{reverse('attendance_register', args=[room.pk])}?month=nonsense")

    assert response.status_code == 200
    assert response.context["month"] == timezone.localdate().replace(day=1)


def test_the_register_does_not_extend_the_staff_layout(client, admin_user, room, child_a):
    """It is printed and filed. The console's nav, badges and sign-out button are
    furniture that would print with it."""
    client.force_login(admin_user)
    body = client.get(reverse("attendance_register", args=[room.pk])).content.decode()

    assert "Sign out" not in body
    assert "Class teacher" in body


def test_the_export_index_names_the_fee_ledger_as_not_built(client, admin_user):
    client.force_login(admin_user)
    body = client.get(reverse("report_index")).content.decode()

    assert "Fee ledger" in body
    assert "Phase 6" in body
