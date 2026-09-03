"""Admissions and records as business logic.

Every test here constructs no HttpRequest — the practical proof that the layer
boundary is real, and the reason `admit_student` will be callable unchanged from the
mobile API in Phase 9.
"""

from datetime import date, timedelta

import pytest
from django.db.utils import IntegrityError
from django.utils import timezone

from apps.people.models import Enrollment, Relationship, Student, StudentStatus
from apps.people.services import (
    admit_student,
    authorize_pickup,
    create_guardian,
    create_student,
    enroll_student,
    link_guardian,
    withdraw_student,
)

pytestmark = pytest.mark.django_db


# --- guardians: siblings and split families ------------------------------------------


def test_the_same_parent_typed_twice_is_one_guardian(branch):
    """Siblings arrive months apart and the office retypes the mother. Two rows would
    split one family's children across two portal accounts."""
    first = create_guardian(branch=branch, full_name="Priya Sharma", phone="9876500001")
    again = create_guardian(branch=branch, full_name="Priya Sharma", phone="9876500001")
    assert first.pk == again.pk


def test_a_guardian_can_hold_two_children(branch):
    mother = create_guardian(branch=branch, full_name="Priya", phone="9876500001")
    older = create_student(branch=branch, first_name="Aarav", date_of_birth=date(2021, 5, 1))
    younger = create_student(branch=branch, first_name="Anya", date_of_birth=date(2023, 5, 1))

    link_guardian(student=older, guardian=mother, relationship=Relationship.MOTHER)
    link_guardian(student=younger, guardian=mother, relationship=Relationship.MOTHER)

    assert mother.students.count() == 2


def test_a_child_can_have_two_primary_contacts(branch):
    """Split families routinely do. Forcing one would make the office pick a favourite."""
    child = create_student(branch=branch, first_name="Aarav", date_of_birth=date(2023, 5, 1))
    mother = create_guardian(branch=branch, full_name="Priya", phone="9876500001")
    father = create_guardian(branch=branch, full_name="Rahul", phone="9876500002")

    link_guardian(student=child, guardian=mother, relationship="mother", is_primary=True)
    link_guardian(student=child, guardian=father, relationship="father", is_primary=True)

    assert child.guardian_links.filter(is_primary=True).count() == 2


def test_linking_the_same_pair_twice_updates_rather_than_duplicates(branch):
    child = create_student(branch=branch, first_name="Aarav", date_of_birth=date(2023, 5, 1))
    mother = create_guardian(branch=branch, full_name="Priya", phone="9876500001")

    link_guardian(student=child, guardian=mother, relationship="other")
    link_guardian(student=child, guardian=mother, relationship="mother", is_primary=True)

    link = child.guardian_links.get()
    assert link.relationship == "mother"
    assert link.is_primary is True


# --- enrolment ------------------------------------------------------------------------


def test_moving_rooms_closes_the_old_enrolment_rather_than_editing_it(
    family, classroom, other_classroom, year
):
    """Attendance and invoices point at the row that was open at the time. Editing it
    in place would quietly rewrite them too."""
    student, _ = family
    first = enroll_student(student=student, classroom=classroom, academic_year=year)
    second = enroll_student(student=student, classroom=other_classroom, academic_year=year)

    first.refresh_from_db()
    assert first.left_on is not None
    assert second.is_open
    assert Enrollment.objects.filter(student=student).count() == 2


def test_enrolling_into_the_same_room_twice_is_idempotent(family, classroom, year):
    student, _ = family
    first = enroll_student(student=student, classroom=classroom, academic_year=year)
    again = enroll_student(student=student, classroom=classroom, academic_year=year)
    assert first.pk == again.pk


def test_a_student_cannot_hold_two_open_enrolments_in_a_year(family, classroom, year):
    """Belt and braces: the service closes the old row, and the database refuses if
    anything ever bypasses the service."""
    student, _ = family
    Enrollment.objects.create(
        branch=student.branch, student=student, classroom=classroom, academic_year=year
    )
    with pytest.raises(IntegrityError):
        Enrollment.objects.create(
            branch=student.branch, student=student, classroom=classroom, academic_year=year
        )


def test_withdrawing_closes_the_enrolment_and_marks_the_student(enrolled, family):
    student, _ = family
    withdraw_student(student=student)

    student.refresh_from_db()
    enrolled.refresh_from_db()
    assert student.status == StudentStatus.LEFT
    assert enrolled.left_on is not None


# --- enquiry to admission: the join between the two halves of the product -------------


def test_an_enquiry_becomes_an_enrolled_student_without_retyping_anything(branch, classroom, year):
    from apps.website.services import create_enquiry

    enquiry = create_enquiry(
        branch=branch,
        guardian_name="Priya Sharma",
        phone="9876543210",
        message="Looking for a Nursery place from June.",
    )

    student = admit_student(
        branch=branch,
        child_name="Aarav Sharma",
        date_of_birth=date(2023, 4, 12),
        guardian_name=enquiry.guardian_name,
        guardian_phone=enquiry.phone,
        classroom=classroom,
        academic_year=year,
    )

    assert student.first_name == "Aarav"
    assert student.last_name == "Sharma"
    assert student.branch == branch

    link = student.guardian_links.get()
    assert link.guardian.full_name == "Priya Sharma"
    assert link.guardian.phone == "9876543210"
    assert link.is_primary is True

    assert student.enrollments.get().classroom == classroom


def test_admission_works_before_a_classroom_has_been_decided(branch):
    """A place is often offered before the room is settled. That must not block the
    record being created."""
    student = admit_student(
        branch=branch,
        child_name="Anya",
        date_of_birth=date(2023, 4, 12),
        guardian_name="Priya",
        guardian_phone="9876543211",
    )
    assert student.enrollments.count() == 0
    assert Student.objects.filter(pk=student.pk).exists()


def test_a_single_word_child_name_does_not_lose_the_name(branch):
    student = admit_student(
        branch=branch,
        child_name="Aarav",
        date_of_birth=date(2023, 4, 12),
        guardian_name="Priya",
        guardian_phone="9876543212",
    )
    assert student.first_name == "Aarav"
    assert student.last_name == ""


# --- child safety ---------------------------------------------------------------------


def test_a_student_with_allergies_is_flagged_for_the_roster(branch):
    """The marker a teacher holding a snack actually sees."""
    plain = create_student(branch=branch, first_name="A", date_of_birth=date(2023, 1, 1))
    flagged = create_student(
        branch=branch, first_name="B", date_of_birth=date(2023, 1, 1), allergies="Peanuts"
    )
    assert plain.has_medical_flags is False
    assert flagged.has_medical_flags is True


def test_a_pickup_window_cannot_end_before_it_starts(family):
    student, guardian = family
    today = timezone.localdate()
    with pytest.raises(IntegrityError):
        authorize_pickup(
            student=student,
            authorized_by=guardian,
            name="Uncle",
            relationship="Uncle",
            phone="9876500010",
            valid_from=today,
            valid_to=today - timedelta(days=1),
        )


def test_a_pickup_authorisation_knows_its_own_window(family):
    student, guardian = family
    today = timezone.localdate()
    friday_only = authorize_pickup(
        student=student,
        authorized_by=guardian,
        name="Uncle",
        relationship="Uncle",
        phone="9876500010",
        valid_from=today,
        valid_to=today,
    )
    assert friday_only.is_valid_on(today) is True
    assert friday_only.is_valid_on(today + timedelta(days=1)) is False
    assert friday_only.is_valid_on(today - timedelta(days=1)) is False


def test_the_child_display_name_prefers_what_the_child_answers_to(branch):
    student = create_student(
        branch=branch,
        first_name="Aaradhya",
        last_name="Sharma",
        date_of_birth=date(2023, 1, 1),
        preferred_name="Adi",
    )
    assert student.display_name == "Adi Sharma"
