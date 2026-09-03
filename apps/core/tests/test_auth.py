"""Login, and the one-time set-password link that replaces every email and SMS.

The link is the whole authentication story: an admin creates an account, hands over
a URL, and the family sets a password. There is no signup page, no OTP, no vendor.
So the properties worth proving are that the link works once, that it stops working
afterwards, and that a bad one says nothing useful.
"""

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.test import Client
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.core.models import Organization, Role, User
from apps.core.services import (
    create_account,
    create_branch,
    issue_set_password_token,
    resolve_set_password_token,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def branch():
    org = Organization.objects.create(name="Aaroham", slug="aaroham")
    return create_branch(organization=org, name="Main", slug="main")


@pytest.fixture
def account(branch):
    return create_account(
        phone="9800000001", full_name="Priya Sharma", branch=branch, role=Role.PARENT
    )


def set_password_url(user: User) -> str:
    uid, token = issue_set_password_token(user)
    return reverse("set_password", kwargs={"uid": uid, "token": token})


# --- account creation -----------------------------------------------------------------


def test_a_new_account_has_no_usable_password(account):
    """Not a temporary one. A temporary password is a shared secret that gets
    forwarded, written down and reused; the link cannot be."""
    assert account.has_usable_password() is False


def test_creating_the_same_account_twice_does_not_make_two(branch):
    first = create_account(phone="9800000009", branch=branch, role=Role.PARENT)
    again = create_account(phone="9800000009", branch=branch, role=Role.PARENT)
    assert first.pk == again.pk


def test_creating_an_account_grants_the_membership(account, branch):
    assert account.memberships.filter(branch=branch, role=Role.PARENT).exists()


# --- the one-time link ----------------------------------------------------------------


def test_the_link_lets_a_parent_choose_a_password(client: Client, account):
    response = client.post(
        set_password_url(account),
        {"new_password1": "chai-and-rain-42", "new_password2": "chai-and-rain-42"},
    )
    assert response.status_code == 302

    account.refresh_from_db()
    assert account.check_password("chai-and-rain-42")


def test_the_link_stops_working_once_it_has_been_used(client: Client, account):
    """The property that makes it one-time. Nothing is marked as spent — setting the
    password changes the hash, and the hash is baked into the token."""
    url = set_password_url(account)
    client.post(url, {"new_password1": "chai-and-rain-42", "new_password2": "chai-and-rain-42"})

    second_attempt = client.get(url)
    assert second_attempt.status_code == 410


def test_a_forged_link_is_refused_and_says_nothing(client: Client, account):
    uid = urlsafe_base64_encode(force_bytes(account.pk))
    response = client.get(reverse("set_password", kwargs={"uid": uid, "token": "made-up-token"}))

    assert response.status_code == 410
    # Same page as an expired link and as an unknown user: distinguishing them tells
    # the holder of a guessed link whether the account exists.
    assert b"no longer works" in response.content


def test_a_link_for_a_user_who_does_not_exist_is_refused(client: Client):
    uid = urlsafe_base64_encode(force_bytes(999999))
    token = default_token_generator.make_token(User(pk=999999, password="x"))
    response = client.get(reverse("set_password", kwargs={"uid": uid, "token": token}))
    assert response.status_code == 410


def test_resolving_a_spent_token_returns_none(account):
    """The service-level statement of the same rule, with no HTTP involved."""
    uid, token = issue_set_password_token(account)
    assert resolve_set_password_token(uid, token) == account

    account.set_password("something-new")
    account.save(update_fields=["password"])

    assert resolve_set_password_token(uid, token) is None


# --- logging in -----------------------------------------------------------------------


def test_a_parent_logs_in_with_a_phone_number(client: Client, account):
    account.set_password("chai-and-rain-42")
    account.save(update_fields=["password"])

    response = client.post(
        reverse("login"), {"username": "9800000001", "password": "chai-and-rain-42"}
    )
    assert response.status_code == 302
    assert response.wsgi_request.user.is_authenticated


def test_the_login_form_asks_for_a_phone_number_not_a_username(client: Client):
    """A parent will not recognise the word "username" — it is the one screen they
    have to get past unaided."""
    response = client.get(reverse("login"))
    assert b"Phone number" in response.content
    assert b"Username" not in response.content


def test_a_parent_lands_in_the_portal_and_staff_in_the_console(client: Client, branch, account):
    account.set_password("chai-and-rain-42")
    account.save(update_fields=["password"])
    client.force_login(account)
    assert client.get(reverse("after_login")).url == reverse("my_children")

    teacher = create_account(phone="9800000002", branch=branch, role=Role.TEACHER)
    client.force_login(teacher)
    assert client.get(reverse("after_login")).url == reverse("student_list")


def test_a_teacher_who_is_also_a_parent_lands_in_the_console(client: Client, branch):
    """The wider grant wins. Landing a teacher in the parent portal would look like
    the console had disappeared."""
    user = create_account(phone="9800000003", branch=branch, role=Role.PARENT)
    create_account(phone="9800000003", branch=branch, role=Role.TEACHER)
    client.force_login(user)
    assert client.get(reverse("after_login")).url == reverse("student_list")


def test_signing_out_is_a_post_not_a_get(client: Client, account):
    """A GET logout is hit by prefetching browser extensions, which signs people out
    while they are reading a page."""
    client.force_login(account)
    assert client.get(reverse("logout")).status_code == 405

    assert client.post(reverse("logout")).status_code == 302
    assert not client.session.get("_auth_user_id")
