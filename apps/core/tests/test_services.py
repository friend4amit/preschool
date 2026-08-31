"""Service-layer tests.

Note what none of these construct: an HttpRequest, a Client, a URL. That is the
practical proof that the layer boundary from docs/plan.md is real — if a service
ever needs a request to be testable, the logic has leaked upward.
"""

import pytest
from django.utils import timezone

from apps.core.models import BranchMembership, Consent, ConsentPurpose, Organization, Role
from apps.core.services import create_branch, grant_membership, record_consent

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return Organization.objects.create(name="Aaroham", slug="aaroham")


@pytest.fixture
def branch(org):
    return create_branch(organization=org, name="Main", slug="main")


@pytest.fixture
def guardian(django_user_model):
    return django_user_model.objects.create_user(phone="9111111111", full_name="A Parent")


def test_create_branch_belongs_to_org(org):
    branch = create_branch(organization=org, name="Second", slug="second")
    assert branch.organization == org
    assert branch.is_active


def test_grant_membership_is_idempotent(guardian, branch):
    first = grant_membership(user=guardian, branch=branch, role=Role.PARENT)
    second = grant_membership(user=guardian, branch=branch, role=Role.PARENT)
    assert first.pk == second.pk
    assert BranchMembership.objects.count() == 1


def test_consent_defaults_to_not_granted(guardian, branch):
    consent = Consent.objects.create(
        guardian=guardian, branch=branch, purpose=ConsentPurpose.PHOTOS_IN_APP
    )
    assert consent.granted is False
    assert consent.is_active is False


def test_record_consent_grants_and_stamps_time(guardian, branch):
    consent = record_consent(
        guardian=guardian,
        branch=branch,
        purpose=ConsentPurpose.PHOTOS_SHARED_WITH_CLASS,
        granted=True,
    )
    assert consent.is_active
    assert consent.granted_at is not None
    assert consent.revoked_at is None
    assert consent.version == 1


def test_re_answering_bumps_version_rather_than_overwriting(guardian, branch):
    record_consent(guardian=guardian, branch=branch, purpose=ConsentPurpose.COMMS, granted=True)
    again = record_consent(
        guardian=guardian, branch=branch, purpose=ConsentPurpose.COMMS, granted=True
    )
    assert again.version == 2
    assert Consent.objects.count() == 1


def test_revoking_records_a_withdrawal_not_an_absence(guardian, branch):
    """A revoked consent must look different from one never given. Under the DPDP Act
    the difference is the whole point: one is a withdrawal, the other is silence."""
    before = timezone.now()
    record_consent(
        guardian=guardian, branch=branch, purpose=ConsentPurpose.PHOTOS_IN_MARKETING, granted=True
    )
    revoked = record_consent(
        guardian=guardian, branch=branch, purpose=ConsentPurpose.PHOTOS_IN_MARKETING, granted=False
    )
    assert revoked.granted is False
    assert revoked.is_active is False
    assert revoked.revoked_at is not None
    assert revoked.revoked_at >= before
    assert revoked.granted_at is not None  # the earlier grant is still on the record
