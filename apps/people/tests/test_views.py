"""The staff console and the parent portal, through HTTP.

The selector tests already prove the scoping rules. These prove the views actually
apply them — the same rule can be right in `selectors.py` and bypassed by a view that
fetches its own object, and this file is what stops that.

The first two tests are the ones to keep forever. Cross-family leakage is the
reputational failure mode of the whole product, and a 403 would leak existence just
as surely as the data would.
"""

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.models import Consent, ConsentPurpose, Role, User
from apps.core.services import grant_membership
from apps.people.models import Guardian, Student
from apps.people.services import create_guardian, create_student, link_guardian

pytestmark = pytest.mark.django_db


@pytest.fixture
def parent(client: Client, family, parent_user) -> Client:
    client.force_login(parent_user)
    return client


@pytest.fixture
def teacher(client: Client, teacher_user) -> Client:
    client.force_login(teacher_user)
    return client


# --- the permission tests to keep forever ---------------------------------------------


def test_a_parent_asking_for_another_familys_child_gets_404_not_403(parent, other_family):
    """The keep-forever test from docs/plan.md.

    404, never 403: a 403 confirms the record exists, which tells somebody walking
    the ids that they guessed a real child.
    """
    other_child, _ = other_family
    response = parent.get(reverse("child_detail", args=[other_child.pk]))

    assert response.status_code == 404
    assert response.status_code != 403


def test_staff_at_another_branch_get_404_for_a_student(client: Client, family, other_branch):
    """The same rule one layer out. A branch admin is trusted staff and still has no
    business reading another branch's records."""
    outsider = User.objects.create_user(phone="9000000099", full_name="Other Branch Admin")
    grant_membership(user=outsider, branch=other_branch, role=Role.BRANCH_ADMIN)
    client.force_login(outsider)

    student, _ = family
    assert client.get(reverse("student_detail", args=[student.pk])).status_code == 404


def test_a_parent_cannot_open_the_staff_console(parent, family):
    student, _ = family
    for url in (
        reverse("student_list"),
        reverse("student_detail", args=[student.pk]),
        reverse("staff_list"),
        reverse("enquiry_list"),
    ):
        response = parent.get(url)
        # Redirected to login rather than shown a 403 — same reasoning as the 404s.
        assert response.status_code == 302, url
        assert reverse("login") in response.url, url


def test_signed_out_visitors_reach_nothing(client: Client, family):
    student, _ = family
    for url in (reverse("student_list"), reverse("my_children")):
        assert client.get(url).status_code == 302, url


def test_a_parent_sees_their_own_child(parent, family):
    student, _ = family
    response = parent.get(reverse("child_detail", args=[student.pk]))
    assert response.status_code == 200
    assert student.display_name.encode() in response.content


def test_the_portal_lists_only_this_parents_children(parent, family, other_family):
    mine, _ = family
    theirs, _ = other_family
    response = parent.get(reverse("my_children"))

    assert mine.display_name.encode() in response.content
    assert theirs.display_name.encode() not in response.content


# --- the student list, with and without JavaScript ------------------------------------


def test_the_student_list_renders_a_full_page_for_a_normal_request(teacher, family):
    student, _ = family
    response = teacher.get(reverse("student_list"))

    assert response.status_code == 200
    assert student.display_name.encode() in response.content
    # The layout came with it — this is a whole page, not a fragment.
    assert b"<html" in response.content


def test_the_same_search_returns_a_bare_partial_to_htmx(teacher, family):
    """The progressive-enhancement contract in one pair of assertions: htmx gets the
    rows, everyone else gets the page, and both come from the same view and the same
    form. With JavaScript off the form still submits as a plain GET."""
    response = teacher.get(reverse("student_list"), headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert b"<html" not in response.content
    assert b'id="student-rows"' in response.content


def test_searching_by_name_narrows_the_list(teacher, family, other_family):
    mine, _ = family
    theirs, _ = other_family
    response = teacher.get(reverse("student_list"), {"q": mine.first_name})

    assert mine.display_name.encode() in response.content
    assert theirs.display_name.encode() not in response.content


def test_search_scopes_before_it_filters(client: Client, family, other_branch):
    """A staff member at another branch searching a name they know still finds
    nothing — the scoping is not a filter that a query string can widen."""
    outsider = User.objects.create_user(phone="9000000098")
    grant_membership(user=outsider, branch=other_branch, role=Role.TEACHER)
    client.force_login(outsider)

    student, _ = family
    response = client.get(reverse("student_list"), {"q": student.first_name})

    # Assert on the row's link, not the name: the search box echoes the query back
    # into its own value attribute, so the name is in the markup either way.
    assert reverse("student_detail", args=[student.pk]).encode() not in response.content
    assert b"No students match that" in response.content


def test_an_allergy_is_visible_on_the_list_not_buried_in_the_record(teacher, branch):
    """The person who needs this is holding a snack, not browsing records."""
    create_student(
        branch=branch, first_name="Anya", date_of_birth="2023-05-01", allergies="Peanuts"
    )
    response = teacher.get(reverse("student_list"))
    assert b"Medical" in response.content


# --- editing --------------------------------------------------------------------------


def test_a_teacher_can_edit_a_student(teacher, family):
    student, _ = family
    response = teacher.post(
        reverse("student_edit", args=[student.pk]),
        {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "preferred_name": "Adi",
            "date_of_birth": "2023-04-12",
            "admission_number": "",
            "status": "enrolled",
            "allergies": "Peanuts",
            "medical_conditions": "",
            "medications": "",
            "blood_group": "",
            "doctor_name": "",
            "doctor_phone": "",
            "notes": "",
        },
    )
    assert response.status_code == 302

    student.refresh_from_db()
    assert student.display_name == "Adi Sharma"
    assert student.has_medical_flags is True


def test_a_posted_branch_id_is_ignored_on_edit(teacher, family, other_branch):
    """The select box never offered it; a POST is not a select box."""
    student, _ = family
    original = student.branch_id
    teacher.post(
        reverse("student_edit", args=[student.pk]),
        {
            "first_name": "Aarav",
            "last_name": "",
            "preferred_name": "",
            "date_of_birth": "2023-04-12",
            "admission_number": "",
            "status": "enrolled",
            "allergies": "",
            "medical_conditions": "",
            "medications": "",
            "blood_group": "",
            "doctor_name": "",
            "doctor_phone": "",
            "notes": "",
            "branch": other_branch.pk,
        },
    )
    student.refresh_from_db()
    assert student.branch_id == original


# --- guardians ------------------------------------------------------------------------


def test_adding_a_second_guardian_to_a_child(teacher, family):
    student, _ = family
    response = teacher.post(
        reverse("guardian_new", args=[student.pk]),
        {
            "full_name": "Rahul Sharma",
            "phone": "9876511111",
            "email": "",
            "address": "",
            "occupation": "",
            "relationship": "father",
            "is_primary": "on",
        },
    )
    assert response.status_code == 302
    assert student.guardian_links.count() == 2
    # Two primaries is allowed on purpose — split families routinely have two.
    assert student.guardian_links.filter(is_primary=True).count() == 2


def test_a_sibling_links_to_the_existing_guardian_rather_than_a_second_row(teacher, family, branch):
    """Retyping a mother is how one family becomes two portal accounts."""
    _, mother = family
    sibling = create_student(branch=branch, first_name="Anya", date_of_birth="2024-01-01")

    response = teacher.post(
        reverse("guardian_link", args=[sibling.pk]),
        {"guardian": str(mother.pk), "relationship": "mother", "is_primary": "on"},
    )
    assert response.status_code == 302
    assert Guardian.objects.filter(phone=mother.phone).count() == 1
    assert sibling.guardian_links.get().guardian == mother


def test_linking_a_guardian_from_another_branch_is_refused(teacher, family, other_branch):
    student, _ = family
    outsider = create_guardian(branch=other_branch, full_name="Someone Else", phone="9876522222")
    response = teacher.post(
        reverse("guardian_link", args=[student.pk]),
        {"guardian": str(outsider.pk), "relationship": "mother"},
    )
    # The choice was never offered, so the form itself rejects it and sends the
    # admin back to the page rather than 500-ing on an id it cannot resolve.
    assert response.status_code == 302
    assert not student.guardian_links.filter(guardian=outsider).exists()


def test_creating_a_portal_account_shows_a_link_once(teacher, family):
    _, guardian = family
    guardian.user = None
    guardian.save(update_fields=["user"])

    response = teacher.post(reverse("guardian_account", args=[guardian.pk]))

    assert response.status_code == 200
    assert b"/accounts/set-password/" in response.content
    guardian.refresh_from_db()
    assert guardian.user_id is not None
    assert guardian.user.has_usable_password() is False


# --- enrolment ------------------------------------------------------------------------


def test_moving_a_child_between_rooms_through_the_screen(
    teacher, enrolled, family, other_classroom, year
):
    student, _ = family
    response = teacher.post(
        reverse("enrollment_change", args=[student.pk]),
        {"classroom": str(other_classroom.pk), "academic_year": str(year.pk)},
    )
    assert response.status_code == 302

    enrolled.refresh_from_db()
    assert enrolled.left_on is not None
    assert student.enrollments.filter(left_on__isnull=True).get().classroom == other_classroom


# --- staff ----------------------------------------------------------------------------


def test_creating_a_colleague_makes_one_account_and_one_link(teacher, branch):
    response = teacher.post(
        reverse("staff_new"),
        {
            "phone": "9800000123",
            "full_name": "Kavita Iyer",
            "email": "",
            "role": Role.TEACHER,
            "designation": "",
        },
    )
    assert response.status_code == 200
    assert b"/accounts/set-password/" in response.content

    account = User.objects.get(phone="9800000123")
    assert account.memberships.filter(branch=branch, role=Role.TEACHER).exists()
    assert account.staff_profile is not None


def test_a_parent_cannot_read_the_staff_list(parent):
    assert parent.get(reverse("staff_list")).status_code == 302


# --- admission, end to end ------------------------------------------------------------


def admission_payload(**overrides) -> dict:
    payload = {
        "child_name": "Aarav Sharma",
        "date_of_birth": "2023-04-12",
        "preferred_name": "",
        "allergies": "",
        "guardian_name": "Priya Sharma",
        "guardian_phone": "9876543210",
        "guardian_email": "",
        "relationship": "mother",
        "classroom": "",
        "academic_year": "",
        "open_portal_account": "on",
    }
    return payload | overrides


def test_an_enquiry_becomes_an_enrolled_student_through_the_screen(
    teacher, branch, classroom, year
):
    """The Done-when from docs/plan.md: an enquiry from the public site becomes an
    enrolled student without retyping anything."""
    from apps.website.models import EnquiryStatus
    from apps.website.services import create_enquiry

    enquiry = create_enquiry(
        branch=branch,
        guardian_name="Priya Sharma",
        phone="9876543210",
        child_name="Aarav Sharma",
        message="Looking for a Nursery place from June.",
    )

    prefilled = teacher.get(reverse("enquiry_convert", args=[enquiry.pk]))
    assert b"Priya Sharma" in prefilled.content
    assert b"9876543210" in prefilled.content

    response = teacher.post(
        reverse("enquiry_convert", args=[enquiry.pk]),
        admission_payload(classroom=str(classroom.pk), academic_year=str(year.pk)),
    )
    assert response.status_code == 302

    student = Student.objects.get(first_name="Aarav")
    assert student.enrollments.get().classroom == classroom
    assert student.guardian_links.get().guardian.full_name == "Priya Sharma"

    enquiry.refresh_from_db()
    assert enquiry.status == EnquiryStatus.ADMITTED


def test_admission_creates_the_login_at_the_same_desk(teacher, branch):
    teacher.post(reverse("student_new"), admission_payload())

    guardian = Guardian.objects.get(phone="9876543210")
    assert guardian.user_id is not None
    assert guardian.user.has_usable_password() is False


def test_consent_is_recorded_off_unless_it_was_ticked(teacher, branch):
    """Off by default, per purpose. The two photo questions are separate on purpose."""
    teacher.post(
        reverse("student_new"),
        admission_payload(**{ConsentPurpose.PHOTOS_IN_APP.value: "on"}),
    )

    guardian = Guardian.objects.get(phone="9876543210")
    granted = set(
        Consent.objects.filter(guardian=guardian.user, granted=True).values_list(
            "purpose", flat=True
        )
    )
    assert granted == {ConsentPurpose.PHOTOS_IN_APP}

    shared = Consent.objects.get(
        guardian=guardian.user, purpose=ConsentPurpose.PHOTOS_SHARED_WITH_CLASS
    )
    assert shared.granted is False


def test_declining_an_account_still_admits_the_child(teacher, branch):
    """Consent needs an account to hang off, so declining one skips consent — but the
    child still gets a record."""
    payload = admission_payload()
    payload.pop("open_portal_account")
    teacher.post(reverse("student_new"), payload)

    guardian = Guardian.objects.get(phone="9876543210")
    assert guardian.user_id is None
    assert Consent.objects.count() == 0
    assert Student.objects.filter(first_name="Aarav").exists()


def test_a_room_without_a_year_is_rejected_rather_than_silently_dropped(teacher, branch, classroom):
    """The open-enrolment constraint is per student per year, so a room with no year
    cannot become an Enrollment. Say so instead of half-admitting the child."""
    response = teacher.post(reverse("student_new"), admission_payload(classroom=str(classroom.pk)))
    assert response.status_code == 200
    assert b"Pick a year as well" in response.content
    assert not Student.objects.filter(first_name="Aarav").exists()


def test_admitting_a_sibling_reuses_the_mother_rather_than_splitting_the_family(
    teacher, branch, family
):
    _, mother = family
    teacher.post(
        reverse("student_new"),
        admission_payload(child_name="Anya Sharma", guardian_phone=mother.phone),
    )

    assert Guardian.objects.filter(phone=mother.phone).count() == 1
    mother.refresh_from_db()
    assert mother.students.count() == 2


def test_converting_another_branchs_enquiry_gives_404(client: Client, other_branch, branch):
    from apps.website.services import create_enquiry

    enquiry = create_enquiry(branch=other_branch, guardian_name="Someone", phone="9876599999")
    insider = User.objects.create_user(phone="9000000097")
    grant_membership(user=insider, branch=branch, role=Role.BRANCH_ADMIN)
    client.force_login(insider)

    assert client.get(reverse("enquiry_convert", args=[enquiry.pk])).status_code == 404


# --- a second guardian on the admitted family, per the plan's Done-when ---------------


def test_the_admitted_family_can_hold_two_guardians(teacher, branch, classroom, year):
    """ "...becomes an enrolled student with two guardians, without retyping anything."
    The second one is added on the child's page, and both may be primary."""
    teacher.post(
        reverse("student_new"),
        admission_payload(classroom=str(classroom.pk), academic_year=str(year.pk)),
    )
    student = Student.objects.get(first_name="Aarav")

    teacher.post(
        reverse("guardian_new", args=[student.pk]),
        {
            "full_name": "Rahul Sharma",
            "phone": "9876543211",
            "email": "",
            "address": "",
            "occupation": "",
            "relationship": "father",
            "is_primary": "on",
        },
    )

    assert student.guardian_links.count() == 2
    assert student.guardian_links.filter(is_primary=True).count() == 2


# --- emergency contacts ---------------------------------------------------------------


def test_adding_an_emergency_contact(teacher, family):
    student, _ = family
    response = teacher.post(
        reverse("emergency_contact_add", args=[student.pk]),
        {
            "name": "Sunita Devi",
            "relationship": "Grandmother",
            "phone": "9876533333",
            "priority": 1,
        },
    )
    assert response.status_code == 302
    assert student.emergency_contacts.get().name == "Sunita Devi"


def test_the_detail_page_says_when_an_emergency_contact_is_missing(teacher, family):
    """An enrolment is not complete without one, and the record has to admit it."""
    student, _ = family
    response = teacher.get(reverse("student_detail", args=[student.pk]))
    assert b"None on file" in response.content


def test_an_expired_pickup_authorisation_does_not_appear_as_current(teacher, family):
    from datetime import timedelta

    from django.utils import timezone

    from apps.people.services import authorize_pickup

    student, guardian = family
    yesterday = timezone.localdate() - timedelta(days=1)
    authorize_pickup(
        student=student,
        authorized_by=guardian,
        name="Last Friday Uncle",
        relationship="Uncle",
        phone="9876544444",
        valid_from=yesterday - timedelta(days=1),
        valid_to=yesterday,
    )

    response = teacher.get(reverse("student_detail", args=[student.pk]))
    assert b"Last Friday Uncle" not in response.content


# --- guardian editing -----------------------------------------------------------------


def test_a_guardians_children_are_listed_on_their_record(teacher, family, branch):
    student, mother = family
    sibling = create_student(branch=branch, first_name="Anya", date_of_birth="2024-01-01")
    link_guardian(student=sibling, guardian=mother, relationship="mother")

    response = teacher.get(reverse("guardian_edit", args=[mother.pk]))
    assert student.display_name.encode() in response.content
    assert sibling.display_name.encode() in response.content


def test_a_parent_cannot_edit_a_guardian_record(parent, family):
    _, guardian = family
    assert parent.get(reverse("guardian_edit", args=[guardian.pk])).status_code == 302


def test_converting_the_same_enquiry_twice_does_not_admit_two_children(teacher, branch):
    """A double-click, a back-then-resubmit, or the queue open in two tabs. The
    guardian would be reused — create_guardian matches on phone — but the child
    would not, and a duplicate student is silent until two of the same name turn up
    on a register."""
    from apps.website.models import EnquiryStatus
    from apps.website.services import create_enquiry

    enquiry = create_enquiry(branch=branch, guardian_name="Priya Sharma", phone="9876543210")
    url = reverse("enquiry_convert", args=[enquiry.pk])

    teacher.post(url, admission_payload())
    second = teacher.post(url, admission_payload())

    assert Student.objects.filter(first_name="Aarav").count() == 1
    assert second.status_code == 302
    assert second.url == reverse("enquiry_list")

    enquiry.refresh_from_db()
    assert enquiry.status == EnquiryStatus.ADMITTED


def test_an_admitted_enquiry_no_longer_offers_the_admit_link(teacher, branch):
    from apps.website.services import create_enquiry

    enquiry = create_enquiry(branch=branch, guardian_name="Priya Sharma", phone="9876543210")
    teacher.post(reverse("enquiry_convert", args=[enquiry.pk]), admission_payload())

    listing = teacher.get(reverse("enquiry_list"))
    assert b"Nothing waiting" in listing.content
