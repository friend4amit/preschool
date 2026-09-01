"""Business logic for admissions and records.

Plain functions. They take arguments, own their transactions, and construct no
HttpRequest — which is what lets the enquiry-to-admission flow be tested as a unit
and, later, be called by the mobile API without being rewritten.

`admit_student` is the one that matters: it is the join between the public website
and the product, and it exists so that nothing typed into the enquiry form is ever
typed again.
"""

from django.db import transaction
from django.utils import timezone

from apps.core.models import AcademicYear, Branch, Classroom, User
from apps.people.models import (
    AuthorizedPickup,
    Document,
    EmergencyContact,
    Enrollment,
    Guardian,
    Relationship,
    Staff,
    Student,
    StudentGuardian,
    StudentStatus,
)


@transaction.atomic
def create_student(*, branch: Branch, first_name: str, date_of_birth, **fields) -> Student:
    fields.setdefault("status", StudentStatus.ENROLLED)
    return Student.objects.create(
        branch=branch,
        first_name=first_name.strip(),
        date_of_birth=date_of_birth,
        **{k: (v.strip() if isinstance(v, str) else v) for k, v in fields.items()},
    )


@transaction.atomic
def create_guardian(*, branch: Branch, full_name: str, phone: str, **fields) -> Guardian:
    """Matches on phone within the branch rather than creating a duplicate.

    Siblings arrive months apart and the office types the same mother in twice; two
    guardian rows then split one family's children across two portal accounts.
    """
    guardian, created = Guardian.objects.get_or_create(
        branch=branch,
        phone=phone.strip(),
        defaults={"full_name": full_name.strip(), **fields},
    )
    if not created and not guardian.full_name:
        guardian.full_name = full_name.strip()
        guardian.save(update_fields=["full_name"])
    return guardian


@transaction.atomic
def link_guardian(
    *, student: Student, guardian: Guardian, relationship: str, is_primary: bool = False
) -> StudentGuardian:
    """Also how a second child is attached to an existing guardian."""
    link, _ = StudentGuardian.objects.update_or_create(
        student=student,
        guardian=guardian,
        defaults={"relationship": relationship, "is_primary": is_primary},
    )
    return link


@transaction.atomic
def add_emergency_contact(
    *, student: Student, name: str, relationship: str, phone: str, priority: int = 1
) -> EmergencyContact:
    return EmergencyContact.objects.create(
        branch=student.branch,
        student=student,
        name=name.strip(),
        relationship=relationship.strip(),
        phone=phone.strip(),
        priority=priority,
    )


@transaction.atomic
def authorize_pickup(
    *,
    student: Student,
    authorized_by: Guardian,
    name: str,
    relationship: str,
    phone: str,
    valid_from=None,
    valid_to=None,
    photo=None,
) -> AuthorizedPickup:
    """`valid_to=None` means open-ended, and is the *less* common case. The temporary
    authorisation is the normal one, which is why the window is a parameter rather
    than something bolted on afterwards."""
    return AuthorizedPickup.objects.create(
        branch=student.branch,
        student=student,
        authorized_by=authorized_by,
        name=name.strip(),
        relationship=relationship.strip(),
        phone=phone.strip(),
        valid_from=valid_from or timezone.localdate(),
        valid_to=valid_to,
        photo=photo,
    )


@transaction.atomic
def enroll_student(
    *, student: Student, classroom: Classroom, academic_year: AcademicYear, joined_on=None
) -> Enrollment:
    """Moving a child to another room closes the old enrolment rather than editing it.

    The history is the point: attendance and invoices already point at the row that
    was open at the time, and rewriting it would quietly rewrite them too.
    """
    open_row = Enrollment.objects.select_for_update().filter(
        student=student, academic_year=academic_year, left_on__isnull=True
    )
    joined = joined_on or timezone.localdate()
    for existing in open_row:
        if existing.classroom_id == classroom.pk:
            return existing
        existing.left_on = joined
        existing.save(update_fields=["left_on"])

    student.status = StudentStatus.ENROLLED
    student.save(update_fields=["status", "updated_at"])

    return Enrollment.objects.create(
        branch=student.branch,
        student=student,
        classroom=classroom,
        academic_year=academic_year,
        joined_on=joined,
    )


@transaction.atomic
def withdraw_student(*, student: Student, left_on=None) -> Student:
    day = left_on or timezone.localdate()
    Enrollment.objects.filter(student=student, left_on__isnull=True).update(left_on=day)
    student.status = StudentStatus.LEFT
    student.save(update_fields=["status", "updated_at"])
    return student


@transaction.atomic
def admit_student(
    *,
    branch: Branch,
    child_name: str,
    date_of_birth,
    guardian_name: str,
    guardian_phone: str,
    relationship: str = Relationship.MOTHER,
    classroom: Classroom | None = None,
    academic_year: AcademicYear | None = None,
    **student_fields,
) -> Student:
    """Enquiry to enrolled student in one call — the join between the two halves of
    the product.

    Takes the enquiry's *values*, not the enquiry. Marking it converted belongs to
    `apps.website`, which owns that model, and this layer does not reach sideways
    into another app's status field. The conversion view calls both.
    """
    first, _, last = child_name.strip().partition(" ")
    student = create_student(
        branch=branch,
        first_name=first,
        last_name=last,
        date_of_birth=date_of_birth,
        **student_fields,
    )
    guardian = create_guardian(branch=branch, full_name=guardian_name, phone=guardian_phone)
    link_guardian(student=student, guardian=guardian, relationship=relationship, is_primary=True)

    if classroom and academic_year:
        enroll_student(student=student, classroom=classroom, academic_year=academic_year)

    return student


@transaction.atomic
def create_staff_profile(*, branch: Branch, user: User, **fields) -> Staff:
    """One account system: this is a profile on an existing User, never a second
    identity. The User is created the same way a parent's is."""
    staff, _ = Staff.objects.get_or_create(user=user, defaults={"branch": branch, **fields})
    return staff


@transaction.atomic
def attach_document(
    *, student: Student, doc_type: str, file, uploaded_by: User | None = None, expires_on=None
) -> Document:
    return Document.objects.create(
        branch=student.branch,
        student=student,
        doc_type=doc_type,
        file=file,
        uploaded_by=uploaded_by,
        expires_on=expires_on,
    )
