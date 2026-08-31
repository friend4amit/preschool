"""Reads. Every non-trivial query lives here, alongside branch scoping.

Nothing outside models.py and selectors.py touches the ORM — that is what makes an
N+1 fixable in one place instead of twelve, and what makes `lint-imports` able to
prove the boundary rather than trust it.

Note there is no HTTP here: no request, no get_object_or_404, no 404s. Selectors
take a user and return querysets. The view decides what an empty result means.
"""

from django.db.models import QuerySet

from apps.core.models import Branch, Consent, ConsentPurpose, Role, User


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
