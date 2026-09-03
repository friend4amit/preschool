"""Business logic for the public site."""

from django.db import transaction

from apps.core.models import Branch
from apps.people import services as people_services
from apps.people.models import Student
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


@transaction.atomic
def convert_enquiry(
    *,
    enquiry: Enquiry,
    child_name: str,
    date_of_birth,
    guardian_name: str = "",
    guardian_phone: str = "",
    **admission_fields,
) -> Student:
    """Turn a prospective family into an enrolled one, and close the enquiry.

    The dependency runs website -> people, never the other way. `apps.website` owns
    the Enquiry and therefore owns the moment it stops being one; `apps.people` owns
    admission and knows nothing about where the family came from. If the arrow ran
    the other way the product would depend on the marketing site.

    Both halves are in one transaction. An enquiry marked admitted with no student
    behind it, or a student whose enquiry still sits in the "new" queue for somebody
    to chase, are both worse than failing outright.
    """
    student = people_services.admit_family(
        branch=enquiry.branch,
        child_name=child_name,
        date_of_birth=date_of_birth,
        guardian_name=guardian_name or enquiry.guardian_name,
        guardian_phone=guardian_phone or enquiry.phone,
        **admission_fields,
    )
    set_enquiry_status(enquiry=enquiry, status=EnquiryStatus.ADMITTED)
    return student
