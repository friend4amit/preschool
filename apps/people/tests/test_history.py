"""What was changed, and who changed it.

History is on `Student` and `Consent` and nowhere else. Those are the two records a
parent might one day dispute — "you changed my child's allergy note" and "I never
agreed to that" — and a table of every edit to every model is a cost with no reader.
`Payment` joins them in Phase 6, for the same reason: somebody will dispute one.
"""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.models import Consent, ConsentPurpose, Role
from apps.core.services import create_account, record_consent
from apps.people.models import Student
from apps.people.services import create_student, update_student

pytestmark = pytest.mark.django_db


def test_editing_a_student_leaves_a_trail(branch):
    student = create_student(
        branch=branch, first_name="Aarav", date_of_birth=date(2023, 4, 12), allergies=""
    )
    update_student(student=student, allergies="Peanuts")

    trail = list(student.history.all().order_by("history_date"))
    assert [entry.allergies for entry in trail] == ["", "Peanuts"]
    assert [entry.history_type for entry in trail] == ["+", "~"]


def test_a_deleted_student_is_still_in_the_history(branch):
    """A record that vanishes without trace is the one you cannot answer questions
    about six months later."""
    student = create_student(branch=branch, first_name="Anya", date_of_birth=date(2023, 4, 12))
    pk = student.pk
    student.delete()

    assert not Student.objects.filter(pk=pk).exists()
    assert Student.history.filter(id=pk, history_type="-").exists()


def test_every_consent_answer_is_kept_not_just_the_current_one(branch):
    """Versioning the row says what the answer is now. The history says what was
    agreed to, and when — which is what a consent record has to be able to show."""
    guardian = create_account(phone="9800000055", branch=branch, role=Role.PARENT)

    record_consent(
        guardian=guardian, branch=branch, purpose=ConsentPurpose.PHOTOS_IN_APP, granted=True
    )
    consent = Consent.objects.get(guardian=guardian, purpose=ConsentPurpose.PHOTOS_IN_APP)
    record_consent(
        guardian=guardian, branch=branch, purpose=ConsentPurpose.PHOTOS_IN_APP, granted=False
    )

    answers = [entry.granted for entry in consent.history.all().order_by("history_date")]
    assert answers == [True, False]


def test_a_web_edit_records_who_made_it(client: Client, teacher_user, family):
    """Attribution comes from the request. A change made by a management command or a
    background task has no request and leaves history_user null, which is honest —
    it is genuinely not a person."""
    student, _ = family
    client.force_login(teacher_user)
    client.post(
        reverse("student_edit", args=[student.pk]),
        {
            "first_name": "Aarav",
            "last_name": "",
            "preferred_name": "",
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

    latest = student.history.order_by("-history_date").first()
    assert latest.allergies == "Peanuts"
    assert latest.history_user == teacher_user


def test_a_change_made_without_a_request_is_attributed_to_nobody(branch):
    student = create_student(branch=branch, first_name="Aarav", date_of_birth=date(2023, 4, 12))
    update_student(student=student, notes="Imported from the old spreadsheet.")

    assert student.history.order_by("-history_date").first().history_user is None
