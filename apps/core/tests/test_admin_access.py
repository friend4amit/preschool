"""The admin is an operator tool, not a staff surface.

docs/plan.md decides this; without a test it is only prose, and the failure mode is
silent: a branch admin who reaches /admin sees every branch's data.
"""

import pytest
from django.urls import reverse

from apps.core.models import Organization, Role
from apps.core.services import create_branch, grant_membership

pytestmark = pytest.mark.django_db


@pytest.fixture
def branch():
    org = Organization.objects.create(name="Aaroham", slug="aaroham")
    return create_branch(organization=org, name="Main", slug="main")


def test_superuser_reaches_the_admin(client, django_user_model):
    root = django_user_model.objects.create_superuser(phone="9000000001", password="pw")
    client.force_login(root)
    assert client.get(reverse("admin:index")).status_code == 200


def test_branch_admin_is_redirected_away_from_the_admin(client, django_user_model, branch):
    """A branch admin is trusted with their own branch — via purpose-built screens,
    not via a surface that would hand them every other branch as well."""
    user = django_user_model.objects.create_user(phone="9000000002", password="pw", is_staff=True)
    grant_membership(user=user, branch=branch, role=Role.BRANCH_ADMIN)
    client.force_login(user)
    assert client.get(reverse("admin:index")).status_code == 302


def test_anonymous_is_redirected_away_from_the_admin(client):
    assert client.get(reverse("admin:index")).status_code == 302
