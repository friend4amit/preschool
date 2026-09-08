"""The admin is an operator tool, not a staff surface.

docs/plan.md decides this; without a test it is only prose, and the failure mode is
silent: a branch admin who reaches /admin sees every branch's data.
"""

import pytest
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.urls import reverse

from apps.core.models import Organization, Role
from apps.core.services import create_branch, grant_membership

pytestmark = pytest.mark.django_db

# The BranchMembership inline's empty management form. Its prefix is the FK's
# related_name, and the admin rejects a POST that arrives without it.
EMPTY_MEMBERSHIP_INLINE = {
    "memberships-TOTAL_FORMS": "0",
    "memberships-INITIAL_FORMS": "0",
    "memberships-MIN_NUM_FORMS": "0",
    "memberships-MAX_NUM_FORMS": "1000",
}


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


# --------------------------------------------------------------------------------
# The password field
# --------------------------------------------------------------------------------
#
# These exist because the admin shipped with `User` on a plain `ModelAdmin`. Django
# renders `password` as what the model says it is — an ordinary CharField — so an
# operator resetting a parent's password through /admin saved the RAW STRING into
# the hash column. Three accounts in the production database were left unable to log
# in, with their passwords sitting readable in every pg_dump taken afterwards.
#
# Nothing in the test suite noticed, because nothing asserted anything about the form.


def test_the_admin_never_offers_an_editable_password_box(client, django_user_model):
    """The change form must show a hash and a link to the change-password screen —
    never a text input that writes straight to the column."""
    root = django_user_model.objects.create_superuser(phone="9000000003", password="pw")
    parent = django_user_model.objects.create_user(phone="9000000004", password="pw")
    client.force_login(root)

    response = client.get(reverse("admin:core_user_change", args=[parent.pk]))
    form = response.context["adminform"].form

    assert isinstance(form.fields["password"], ReadOnlyPasswordHashField), (
        "User is registered on a plain ModelAdmin. Typing into this field stores the "
        "raw string as the password hash and locks the account out permanently."
    )


def test_saving_a_user_in_the_admin_cannot_destroy_their_password(client, django_user_model):
    """The behavioural version of the test above, and the one that actually describes
    the bug: edit a user, save, and the password must still work."""
    root = django_user_model.objects.create_superuser(phone="9000000005", password="pw")
    parent = django_user_model.objects.create_user(phone="9000000006", password="hunter2!x")
    client.force_login(root)

    client.post(
        reverse("admin:core_user_change", args=[parent.pk]),
        {
            "phone": parent.phone,
            "full_name": "Renamed In Admin",
            "email": "",
            "is_active": "on",
            "date_joined_0": "2026-01-01",
            "date_joined_1": "00:00:00",
            **EMPTY_MEMBERSHIP_INLINE,
        },
    )

    parent.refresh_from_db()
    assert parent.full_name == "Renamed In Admin", "The edit did not go through."
    assert parent.check_password("hunter2!x"), (
        "Saving the change form destroyed the password hash — the exact failure that "
        "locked three production accounts out."
    )


def test_adding_a_user_in_the_admin_hashes_the_password(client, django_user_model):
    root = django_user_model.objects.create_superuser(phone="9000000007", password="pw")
    client.force_login(root)

    client.post(
        reverse("admin:core_user_add"),
        {
            "phone": "9000000008",
            "full_name": "Created In Admin",
            "usable_password": "true",
            "password1": "Aaroham#2026x",
            "password2": "Aaroham#2026x",
            **EMPTY_MEMBERSHIP_INLINE,
        },
    )

    made = django_user_model.objects.filter(phone="9000000008").first()
    assert made is not None, "The add form did not create the user."
    assert made.password != "Aaroham#2026x", "The password was stored in plain text."
    assert made.check_password("Aaroham#2026x")
