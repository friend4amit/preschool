"""Business logic. Plain functions that take arguments, return objects, own their
transactions, and know nothing about HTTP.

This is the layer a future django-ninja API calls, which is why adding mobile later
is mechanical rather than archaeological. It is also the layer that is pleasant to
unit-test: every test below constructs no HttpRequest.
"""

from django.db import transaction
from django.utils import timezone

from apps.core.models import Branch, BranchMembership, Consent, ConsentPurpose, Organization, User


@transaction.atomic
def create_branch(*, organization: Organization, name: str, slug: str, **fields) -> Branch:
    return Branch.objects.create(organization=organization, name=name, slug=slug, **fields)


@transaction.atomic
def grant_membership(*, user: User, branch: Branch, role: str) -> BranchMembership:
    membership, _ = BranchMembership.objects.get_or_create(user=user, branch=branch, role=role)
    return membership


@transaction.atomic
def record_consent(
    *,
    guardian: User,
    branch: Branch,
    purpose: ConsentPurpose,
    granted: bool,
    recorded_by: User | None = None,
) -> Consent:
    """Record a guardian's answer to one consent question.

    Re-answering bumps the version rather than overwriting: what was consented to,
    and when, has to survive being changed. Revoking stamps revoked_at so the record
    shows a withdrawal rather than an absence.
    """
    consent, created = Consent.objects.select_for_update().get_or_create(
        guardian=guardian,
        branch=branch,
        purpose=purpose,
        defaults={"granted": granted, "recorded_by": recorded_by},
    )
    if not created:
        consent.version += 1
        consent.granted = granted
        consent.recorded_by = recorded_by

    if granted:
        consent.granted_at = timezone.now()
        consent.revoked_at = None
    else:
        consent.revoked_at = timezone.now()

    consent.save()
    return consent
