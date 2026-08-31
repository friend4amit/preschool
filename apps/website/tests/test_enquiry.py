"""The enquiry path — the join between the marketing site and admissions.

If any of these break, the school stops hearing from prospective parents and nothing
in the app says so. That makes them the highest-value tests in the phase.
"""

import pytest
from django.urls import reverse

from apps.core.models import Organization
from apps.core.services import create_branch
from apps.website.forms import EnquiryForm
from apps.website.models import Enquiry, EnquiryStatus, Program
from apps.website.services import create_enquiry, set_enquiry_status

pytestmark = pytest.mark.django_db


@pytest.fixture
def branch():
    org = Organization.objects.create(name="Aaroham", slug="aaroham")
    return create_branch(organization=org, name="Main", slug="main")


@pytest.fixture
def program(branch):
    return Program.objects.create(
        branch=branch, name="Nursery", slug="nursery", age_from_months=30, age_to_months=42
    )


# --- form: what a valid enquiry is -------------------------------------------------


@pytest.mark.parametrize(
    "typed,stored",
    [
        ("9876543210", "9876543210"),
        ("98765 43210", "9876543210"),
        ("+91 98765 43210", "9876543210"),
        ("098765-43210", "9876543210"),
        ("+919876543210", "9876543210"),
    ],
)
def test_phone_accepts_how_people_actually_type_it(typed, stored):
    """Rejecting '+91 98765 43210' over formatting loses a real family."""
    form = EnquiryForm(data={"guardian_name": "Priya", "phone": typed})
    assert form.is_valid(), form.errors
    assert form.cleaned_data["phone"] == stored


@pytest.mark.parametrize("bad", ["12345", "abcdefghij", "", "9876543210123456"])
def test_phone_rejects_what_cannot_be_dialled(bad):
    form = EnquiryForm(data={"guardian_name": "Priya", "phone": bad})
    assert not form.is_valid()


def test_only_name_and_phone_are_required():
    """Every extra required field costs enquiries; the school can ask the rest by phone."""
    form = EnquiryForm(data={"guardian_name": "Priya", "phone": "9876543210"})
    assert form.is_valid(), form.errors


def test_future_date_of_birth_is_rejected():
    from datetime import timedelta

    from django.utils import timezone

    tomorrow = timezone.localdate() + timedelta(days=1)
    form = EnquiryForm(
        data={"guardian_name": "Priya", "phone": "9876543210", "child_dob": tomorrow.isoformat()}
    )
    assert not form.is_valid()
    assert "child_dob" in form.errors


def test_honeypot_rejects_a_filled_hidden_field():
    form = EnquiryForm(
        data={"guardian_name": "Bot", "phone": "9876543210", "website": "http://spam.example"}
    )
    assert not form.is_valid()
    assert "website" in form.errors


# --- service: no HttpRequest anywhere ----------------------------------------------


def test_create_enquiry_records_a_new_prospect(branch, program):
    enquiry = create_enquiry(
        branch=branch,
        guardian_name="  Priya Sharma  ",
        phone=" 9876543210 ",
        program=program,
        message="  Looking for June.  ",
    )
    assert enquiry.guardian_name == "Priya Sharma"  # whitespace stripped
    assert enquiry.message == "Looking for June."
    assert enquiry.status == EnquiryStatus.NEW
    assert enquiry.branch == branch


def test_enquiry_status_moves_through_the_funnel(branch):
    enquiry = create_enquiry(branch=branch, guardian_name="Priya", phone="9876543210")
    set_enquiry_status(enquiry=enquiry, status=EnquiryStatus.CONTACTED, notes="Called Tuesday")
    enquiry.refresh_from_db()
    assert enquiry.status == EnquiryStatus.CONTACTED
    assert enquiry.notes == "Called Tuesday"


# --- view: the whole path ----------------------------------------------------------


def test_posting_the_form_creates_an_enquiry_and_redirects(client, branch, program):
    response = client.post(
        reverse("contact"),
        {
            "guardian_name": "Priya Sharma",
            "phone": "+91 98765 43210",
            "child_name": "Aarav",
            "program": program.pk,
            "message": "Looking for a Nursery place from June.",
        },
    )
    assert response.status_code == 302  # POST/redirect/GET, so a refresh can't double-submit

    enquiry = Enquiry.objects.get()
    assert enquiry.guardian_name == "Priya Sharma"
    assert enquiry.phone == "9876543210"
    assert enquiry.program == program
    assert enquiry.branch == branch


def test_a_bot_filling_the_honeypot_saves_nothing(client, branch):
    response = client.post(
        reverse("contact"),
        {"guardian_name": "Bot", "phone": "9876543210", "website": "http://spam.example"},
    )
    assert response.status_code == 200  # re-rendered with the error, not redirected
    assert Enquiry.objects.count() == 0


def test_an_invalid_submission_does_not_lose_what_was_typed(client, branch):
    """A parent who mistypes a phone number should not have to write the message again."""
    response = client.post(
        reverse("contact"),
        {"guardian_name": "Priya", "phone": "123", "message": "A long and thoughtful message."},
    )
    assert response.status_code == 200
    assert b"A long and thoughtful message." in response.content
    assert Enquiry.objects.count() == 0
