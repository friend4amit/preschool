"""Reads for students, guardians and staff — and the scoping that decides who sees whom.

`students_for_user` is the one to get right. A parent's queryset narrows to the
children they are actually linked to as a guardian; a member of staff sees the
branches they hold a membership at; a superuser sees everything. Every other selector
here composes with it rather than re-deriving the rule, so there is exactly one place
where "may this person see this child" is answered.

The view layer turns an empty result into a 404, never a 403 — see
`docs/plan.md`. Nothing here knows what HTTP is.
"""

from django.db.models import Prefetch, QuerySet
from django.utils import timezone

from apps.core.models import Branch, Role, User
from apps.core.selectors import branches_for_user
from apps.people.models import (
    AuthorizedPickup,
    Document,
    EmergencyContact,
    Enrollment,
    Guardian,
    Staff,
    Student,
    StudentGuardian,
)

STAFF_ROLES = [Role.BRANCH_ADMIN, Role.TEACHER, Role.ACCOUNTANT]


def students_for_user(user: User) -> QuerySet[Student]:
    """Every student this user may see, and no others.

    The parent branch is the security boundary of the whole product: a guardian is
    linked to their children through StudentGuardian, and that link — not the branch —
    is what grants access. A parent who is also, say, a teacher gets the staff view,
    because the membership is the broader grant.
    """
    if not user.is_authenticated:
        return Student.objects.none()
    if user.is_superuser:
        return Student.objects.all()

    if user.memberships.filter(role__in=STAFF_ROLES).exists():
        return Student.objects.filter(branch__in=branches_for_user(user))

    # Everyone else is a parent, and reaches children only through their own
    # guardian profile. No guardian profile means no children, not "all of them".
    return Student.objects.filter(guardian_links__guardian__user=user).distinct()


def student_detail_for_user(user: User, student_id: int) -> Student | None:
    """One student, or None. The caller decides that None means 404.

    Prefetches what the detail page always renders, so the page is a fixed number of
    queries rather than one per guardian.
    """
    return (
        students_for_user(user)
        .select_related("branch")
        .prefetch_related(
            Prefetch(
                "guardian_links",
                queryset=StudentGuardian.objects.select_related("guardian").order_by("-is_primary"),
            ),
            "emergency_contacts",
            "enrollments__classroom",
            "enrollments__academic_year",
        )
        .filter(pk=student_id)
        .first()
    )


def search_students(
    user: User, *, query: str = "", classroom_id: int | None = None, status: str = ""
) -> QuerySet[Student]:
    """The student list. Scoped first, filtered second — never the other way round."""
    students = students_for_user(user).select_related("branch")

    if query:
        from django.db.models import Q

        students = students.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(preferred_name__icontains=query)
            | Q(admission_number__icontains=query)
        )
    if classroom_id:
        students = students.filter(
            enrollments__classroom_id=classroom_id, enrollments__left_on__isnull=True
        )
    if status:
        students = students.filter(status=status)

    return students.distinct()


def guardians_for_student(student: Student) -> QuerySet[StudentGuardian]:
    """Ordered so the primary contact is the one the office reads first."""
    return (
        StudentGuardian.objects.filter(student=student)
        .select_related("guardian", "guardian__user")
        .order_by("-is_primary", "guardian__full_name")
    )


def guardians_for_user(user: User) -> QuerySet[Guardian]:
    if not user.is_authenticated:
        return Guardian.objects.none()
    if user.is_superuser:
        return Guardian.objects.all()
    if user.memberships.filter(role__in=STAFF_ROLES).exists():
        return Guardian.objects.filter(branch__in=branches_for_user(user))
    # A parent may see their own record and nobody else's.
    return Guardian.objects.filter(user=user)


def children_of(user: User) -> QuerySet[Student]:
    """The parent portal's "my children". Distinct from students_for_user, which a
    member of staff also passes — this one is only ever the guardian link."""
    if not user.is_authenticated:
        return Student.objects.none()
    return Student.objects.filter(guardian_links__guardian__user=user).distinct()


def open_enrollment(student: Student) -> Enrollment | None:
    return (
        Enrollment.objects.filter(student=student, left_on__isnull=True)
        .select_related("classroom", "academic_year")
        .first()
    )


def roster(classroom_id: int, *, user: User) -> QuerySet[Student]:
    """Who is in a room right now. Scoped through students_for_user so a teacher at
    branch one cannot read branch two's roster by guessing an id."""
    return (
        students_for_user(user)
        .filter(enrollments__classroom_id=classroom_id, enrollments__left_on__isnull=True)
        .distinct()
    )


def valid_pickups_for(student: Student, *, on=None) -> QuerySet[AuthorizedPickup]:
    """Only authorisations in force today. An expired one that still reads as valid
    is exactly what this model exists to prevent, so the filter lives here rather
    than in a template."""
    day = on or timezone.localdate()
    from django.db.models import Q

    return AuthorizedPickup.objects.filter(student=student, valid_from__lte=day).filter(
        Q(valid_to__isnull=True) | Q(valid_to__gte=day)
    )


def emergency_contacts_for(student: Student) -> QuerySet[EmergencyContact]:
    return EmergencyContact.objects.filter(student=student).order_by("priority", "name")


def documents_for_student(student: Student) -> QuerySet[Document]:
    return Document.objects.filter(student=student).select_related("uploaded_by")


def students_missing_an_emergency_contact(branch: Branch) -> QuerySet[Student]:
    """The office's own checklist. An enrolment is not complete without one, and this
    is how anyone finds the ones that slipped through."""
    return Student.objects.filter(branch=branch, emergency_contacts__isnull=True)


def staff_for_user(user: User) -> QuerySet[Staff]:
    if not user.is_authenticated:
        return Staff.objects.none()
    if user.is_superuser:
        return Staff.objects.all()
    if user.memberships.filter(role__in=STAFF_ROLES).exists():
        return Staff.objects.filter(branch__in=branches_for_user(user)).select_related("user")
    # A parent has no business reading the staff list.
    return Staff.objects.none()
