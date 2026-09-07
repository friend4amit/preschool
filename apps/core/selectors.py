"""Reads. Every non-trivial query lives here, alongside branch scoping.

Nothing outside models.py and selectors.py touches the ORM — that is what makes an
N+1 fixable in one place instead of twelve, and what makes `lint-imports` able to
prove the boundary rather than trust it.

Note there is no HTTP here: no request, no get_object_or_404, no 404s. Selectors
take a user and return querysets. The view decides what an empty result means.
"""

from django.db.models import QuerySet

from apps.core.models import (
    AcademicYear,
    Branch,
    Classroom,
    Consent,
    ConsentPurpose,
    Role,
    User,
)


def branches_for_user(user: User) -> QuerySet[Branch]:
    """Branches this user may see. The scoping helper every other selector composes with.

    Called explicitly at each call site rather than applied by a manager or middleware:
    hidden scoping breaks migrations, loaddata, shell sessions, and background tasks,
    none of which have a request.
    """
    if not user.is_authenticated:
        return Branch.objects.none()
    if user.is_superuser:
        return Branch.objects.all()
    return Branch.objects.filter(memberships__user=user, is_active=True).distinct()


def user_has_role_at(user: User, branch: Branch, *roles: str) -> bool:
    if user.is_superuser:
        return True
    return user.memberships.filter(branch=branch, role__in=roles).exists()


def consents_for_guardian(guardian: User, branch: Branch) -> QuerySet[Consent]:
    return Consent.objects.filter(guardian=guardian, branch=branch)


def has_active_consent(guardian: User, branch: Branch, purpose: ConsentPurpose) -> bool:
    """Off by default: an absent row is a "no", not an unknown."""
    return Consent.objects.filter(
        guardian=guardian, branch=branch, purpose=purpose, granted=True, revoked_at__isnull=True
    ).exists()


def staff_at(branch: Branch) -> QuerySet[User]:
    return User.objects.filter(
        memberships__branch=branch,
        memberships__role__in=[Role.BRANCH_ADMIN, Role.TEACHER, Role.ACCOUNTANT],
    ).distinct()


def current_branch_fallback() -> Branch | None:
    """The single branch, for commands and seeds that have no user.

    Distinct from `branches_for_user`: this one deliberately has no scoping because
    it has no request and no user. Never call it from a view.
    """
    return Branch.objects.filter(is_active=True).order_by("pk").first()


def primary_role_for(user: User) -> str:
    """The role that decides which console a user lands in after logging in.

    Returned as a role, not a URL: which screen a role maps to is routing, and
    routing is the view's business. Staff roles win over parent, so a teacher who
    is also a parent lands in the staff console rather than the portal.
    """
    if not user.is_authenticated:
        return ""
    if user.is_superuser:
        return Role.SUPERADMIN
    ranked = [Role.BRANCH_ADMIN, Role.TEACHER, Role.ACCOUNTANT, Role.PARENT]
    held = set(user.memberships.values_list("role", flat=True))
    return next((role for role in ranked if role in held), Role.PARENT)


def classrooms_for_user(user: User) -> QuerySet[Classroom]:
    """Rooms this user may see. Populates every classroom select box in the console,
    so an unscoped version here would let one branch enumerate another's rooms."""
    return Classroom.objects.filter(branch__in=branches_for_user(user), is_active=True)


def academic_years_for_user(user: User) -> QuerySet[AcademicYear]:
    return AcademicYear.objects.filter(branch__in=branches_for_user(user))


def current_academic_year(branch: Branch) -> AcademicYear | None:
    """The year the office has marked current, which is a decision rather than a
    calendar fact — a school is mid-admissions for next year while this one runs."""
    return AcademicYear.objects.filter(branch=branch, is_current=True).first()


STAFF_ROLES = (Role.BRANCH_ADMIN, Role.TEACHER, Role.ACCOUNTANT)


def is_staff_member(user: User) -> bool:
    """May this person open the staff console at all?

    Not `user.is_staff`: that flag governs Django admin, which is superadmin-only
    here. A teacher has no `is_staff` and every right to the console.
    """
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.memberships.filter(role__in=STAFF_ROLES).exists()


# --------------------------------------------------------------------------------
# Damaged password hashes
# --------------------------------------------------------------------------------
#
# The admin registered `User` on a plain `ModelAdmin` for four phases, so the change
# form offered `password` as an ordinary text box and saved whatever was typed into
# it straight into the hash column. Those accounts cannot log in — `check_password`
# has no hasher to identify — and their password is sitting in the database, and in
# every pg_dump taken since, as readable text.
#
# The admin is fixed (`apps/core/admin.py`, with tests that go red on the old code).
# This is how you find what it already broke: `manage.py repair_passwords`.


def password_state(user: User) -> str:
    """One of `hashed`, `unset`, or `plaintext`.

    `unset` is the normal, healthy state for an account created by an admin whose
    set-password link has not been used yet — Django writes an unusable marker, not a
    hash, and that is correct. Only `plaintext` is damage.
    """
    from django.contrib.auth.hashers import identify_hasher

    if not user.has_usable_password():
        return "unset"
    try:
        identify_hasher(user.password)
    except (ValueError, TypeError):
        return "plaintext"
    return "hashed"


def accounts_with_plaintext_passwords() -> list[User]:
    """Every account the admin bug locked out. Cheap enough to walk in Python — the
    hasher prefix is not something a database index can answer, and this runs once."""
    return [user for user in User.objects.order_by("pk") if password_state(user) == "plaintext"]
