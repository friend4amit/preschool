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

from apps.core import services as core_services
from apps.core.models import AcademicYear, Branch, Classroom, Consent, Role, User
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
    into another app's status field — `website.services.convert_enquiry` composes
    the two inside one transaction.

    Deliberately does not create a login or ask for consent. `admit_family` wraps
    this and does both; this one stays available for the back-office case of
    recording a child whose paperwork is still in progress.
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


@transaction.atomic
def create_portal_account(*, guardian: Guardian, role: str = Role.PARENT) -> User:
    """Give a guardian a login, using the phone number already on their record.

    Separate from `create_guardian` because the two are genuinely separate events: a
    guardian exists from the moment the office writes them down, and an account
    exists from the moment somebody hands over a link. Most guardians spend a while
    in between, and a nullable `Guardian.user` is what records that honestly.
    """
    user = core_services.create_account(
        phone=guardian.phone,
        full_name=guardian.full_name,
        email=guardian.email,
        branch=guardian.branch,
        role=role,
    )
    if guardian.user_id != user.pk:
        guardian.user = user
        guardian.save(update_fields=["user"])
    return user


@transaction.atomic
def record_consents(
    *, guardian: Guardian, answers: dict[str, bool], recorded_by: User | None = None
) -> list[Consent]:
    """Write a guardian's answers to the consent questions.

    Requires an account, because `Consent.guardian` is a `User` — consent is given by
    a person who can later revoke it, and revoking needs somewhere to sign in. That is
    why admission creates the account at the same desk rather than later.

    Only the purposes actually asked about are written. An absent row is a "no", so
    silence and refusal record identically, which is the DPDP default we want.
    """
    if guardian.user_id is None:
        raise ValueError("Consent is recorded against an account. Create one first.")
    return [
        core_services.record_consent(
            guardian=guardian.user,
            branch=guardian.branch,
            purpose=purpose,
            granted=granted,
            recorded_by=recorded_by,
        )
        for purpose, granted in answers.items()
    ]


@transaction.atomic
def admit_family(
    *,
    branch: Branch,
    child_name: str,
    date_of_birth,
    guardian_name: str,
    guardian_phone: str,
    relationship: str = Relationship.MOTHER,
    classroom: Classroom | None = None,
    academic_year: AcademicYear | None = None,
    consents: dict[str, bool] | None = None,
    open_portal_account: bool = True,
    recorded_by: User | None = None,
    **student_fields,
) -> Student:
    """One admission, end to end: child, guardian, login, consent, enrolment.

    All of it in one transaction on purpose. A half-admitted family — a student row
    with no guardian, or a consent answer against an account that failed to save — is
    worse than no row at all, because the office cannot see that it is broken.

    `open_portal_account` exists for the family who decline one. They still get a
    student record; they just cannot be asked for consent, which is why the two
    switches are wired together rather than independent.
    """
    student = admit_student(
        branch=branch,
        child_name=child_name,
        date_of_birth=date_of_birth,
        guardian_name=guardian_name,
        guardian_phone=guardian_phone,
        relationship=relationship,
        classroom=classroom,
        academic_year=academic_year,
        **student_fields,
    )
    guardian = student.guardian_links.get(is_primary=True).guardian

    if open_portal_account:
        create_portal_account(guardian=guardian)
        if consents:
            record_consents(guardian=guardian, answers=consents, recorded_by=recorded_by)

    return student


@transaction.atomic
def update_student(*, student: Student, **fields) -> Student:
    """Field-by-field so the caller cannot set `branch` by posting one.

    A student does not change branch through an edit form, and the day there are two
    branches, accepting one from a POST is how a child ends up in the wrong school.
    """
    editable = {k: v for k, v in fields.items() if k not in {"branch", "id", "pk"}}
    for name, value in editable.items():
        setattr(student, name, value.strip() if isinstance(value, str) else value)
    student.save()
    return student


@transaction.atomic
def update_guardian(*, guardian: Guardian, **fields) -> Guardian:
    """`user` is excluded for the same reason `branch` is on students: an account is
    attached by `create_portal_account`, deliberately, not by editing a contact."""
    editable = {k: v for k, v in fields.items() if k not in {"branch", "user", "id", "pk"}}
    for name, value in editable.items():
        setattr(guardian, name, value.strip() if isinstance(value, str) else value)
    guardian.save()
    return guardian


@transaction.atomic
def add_guardian_to_student(
    *,
    student: Student,
    full_name: str,
    phone: str,
    relationship: str,
    is_primary: bool = False,
    **fields,
) -> StudentGuardian:
    """Create a guardian and attach them in one step, in the child's branch.

    Goes through `create_guardian`, so typing in a mother who already exists on a
    sibling's record links the existing row instead of splitting the family in two.
    """
    guardian = create_guardian(branch=student.branch, full_name=full_name, phone=phone, **fields)
    return link_guardian(
        student=student, guardian=guardian, relationship=relationship, is_primary=is_primary
    )


@transaction.atomic
def update_staff_profile(*, staff: Staff, **fields) -> Staff:
    editable = {k: v for k, v in fields.items() if k not in {"branch", "user", "id", "pk"}}
    for name, value in editable.items():
        setattr(staff, name, value.strip() if isinstance(value, str) else value)
    staff.save()
    return staff


@transaction.atomic
def onboard_staff(
    *, branch: Branch, phone: str, full_name: str, role: str, email: str = "", **fields
) -> Staff:
    """A teacher's account and profile in one call.

    The same `User` a parent gets — one account system, one login form, one
    set-password link. What differs is the BranchMembership role.
    """
    user = core_services.create_account(
        phone=phone, full_name=full_name, email=email, branch=branch, role=role
    )
    return create_staff_profile(branch=branch, user=user, **fields)
