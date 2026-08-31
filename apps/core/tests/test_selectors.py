"""Scoping tests.

The cross-branch case here is the ancestor of the test docs/plan.md says to keep green
forever: a parent must not reach another family's child. Student doesn't exist until
phase 2, so the branch boundary is what there is to prove today — and it is the same
boundary, one level up.
"""

import pytest
from django.contrib.auth.models import AnonymousUser

from apps.core.models import ConsentPurpose, Organization, Role
from apps.core.selectors import (
    branches_for_user,
    consents_for_guardian,
    has_active_consent,
    staff_at,
    user_has_role_at,
)
from apps.core.services import create_branch, grant_membership, record_consent

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return Organization.objects.create(name="Aaroham", slug="aaroham")


@pytest.fixture
def branch_a(org):
    return create_branch(organization=org, name="Main", slug="main")


@pytest.fixture
def branch_b(org):
    return create_branch(organization=org, name="Second", slug="second")


@pytest.fixture
def teacher_at_a(django_user_model, branch_a):
    user = django_user_model.objects.create_user(phone="9222222222", full_name="A Teacher")
    grant_membership(user=user, branch=branch_a, role=Role.TEACHER)
    return user


def test_anonymous_sees_no_branches():
    assert branches_for_user(AnonymousUser()).count() == 0


def test_user_sees_only_their_own_branch(teacher_at_a, branch_a, branch_b):
    visible = branches_for_user(teacher_at_a)
    assert list(visible) == [branch_a]
    assert branch_b not in visible


def test_superuser_sees_every_branch(django_user_model, branch_a, branch_b):
    root = django_user_model.objects.create_superuser(phone="9333333333")
    assert branches_for_user(root).count() == 2


def test_inactive_branches_are_hidden(teacher_at_a, branch_a):
    branch_a.is_active = False
    branch_a.save()
    assert branches_for_user(teacher_at_a).count() == 0


def test_membership_at_one_branch_grants_nothing_at_another(teacher_at_a, branch_a, branch_b):
    assert user_has_role_at(teacher_at_a, branch_a, Role.TEACHER)
    assert not user_has_role_at(teacher_at_a, branch_b, Role.TEACHER)


def test_role_check_is_specific_not_merely_membership(teacher_at_a, branch_a):
    """Being at a branch is not being an accountant at it."""
    assert not user_has_role_at(teacher_at_a, branch_a, Role.ACCOUNTANT)


def test_absent_consent_row_reads_as_no(django_user_model, branch_a):
    """Off by default. An absent row is a "no", never an unknown."""
    guardian = django_user_model.objects.create_user(phone="9444444444")
    assert has_active_consent(guardian, branch_a, ConsentPurpose.PHOTOS_IN_APP) is False


def test_revoked_consent_reads_as_no(django_user_model, branch_a):
    guardian = django_user_model.objects.create_user(phone="9555555555")
    record_consent(
        guardian=guardian, branch=branch_a, purpose=ConsentPurpose.PHOTOS_IN_APP, granted=True
    )
    assert has_active_consent(guardian, branch_a, ConsentPurpose.PHOTOS_IN_APP)

    record_consent(
        guardian=guardian, branch=branch_a, purpose=ConsentPurpose.PHOTOS_IN_APP, granted=False
    )
    assert has_active_consent(guardian, branch_a, ConsentPurpose.PHOTOS_IN_APP) is False


def test_consent_does_not_carry_across_branches(django_user_model, branch_a, branch_b):
    """Consent is bound to the purpose *and* the place it was given."""
    guardian = django_user_model.objects.create_user(phone="9666666666")
    record_consent(guardian=guardian, branch=branch_a, purpose=ConsentPurpose.COMMS, granted=True)
    assert has_active_consent(guardian, branch_a, ConsentPurpose.COMMS)
    assert has_active_consent(guardian, branch_b, ConsentPurpose.COMMS) is False
    assert consents_for_guardian(guardian, branch_b).count() == 0


def test_staff_listing_excludes_parents(django_user_model, branch_a, teacher_at_a):
    parent = django_user_model.objects.create_user(phone="9777777777")
    grant_membership(user=parent, branch=branch_a, role=Role.PARENT)
    staff = staff_at(branch_a)
    assert teacher_at_a in staff
    assert parent not in staff
