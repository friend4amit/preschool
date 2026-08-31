"""Business logic for the public site."""

from django.db import transaction

from apps.core.models import Branch
from apps.website.models import Enquiry, EnquiryStatus, Program


@transaction.atomic
def create_enquiry(
    *,
    branch: Branch,
    guardian_name: str,
    phone: str,
    email: str = "",
    child_name: str = "",
    child_dob=None,
    program: Program | None = None,
    message: str = "",
    source: str = "website",
) -> Enquiry:
    """Record a prospective family.

    Deliberately forgiving about what it requires: a name and a phone number are
    enough. An admissions form that demands a date of birth before it will accept a
    curious parent loses the parent.
    """
    return Enquiry.objects.create(
        branch=branch,
        guardian_name=guardian_name.strip(),
        phone=phone.strip(),
        email=email.strip(),
        child_name=child_name.strip(),
        child_dob=child_dob,
        program=program,
        message=message.strip(),
        source=source,
        status=EnquiryStatus.NEW,
    )


@transaction.atomic
def set_enquiry_status(*, enquiry: Enquiry, status: str, notes: str = "") -> Enquiry:
    enquiry.status = status
    if notes:
        enquiry.notes = notes
    enquiry.save(update_fields=["status", "notes", "updated_at"])
    return enquiry
