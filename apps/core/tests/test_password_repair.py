"""The admin bug, and the tool that cleans up after it.

`apps/core/tests/test_admin_access.py` proves the admin can no longer cause this.
This file proves we can find and fix the accounts it already broke — which is a
separate claim, and the one that matters to the three people who cannot log in.
"""

import pytest

from apps.core import selectors, services

pytestmark = pytest.mark.django_db


def _damage(user, raw):
    """Exactly what the plain ModelAdmin did: put the typed string in the hash column."""
    user.password = raw
    user.save(update_fields=["password"])
    return user


def test_a_plaintext_password_cannot_authenticate(django_user_model):
    """The symptom the user reported, reproduced. Worth asserting rather than assuming:
    it is the whole reason the repair exists."""
    user = _damage(django_user_model.objects.create_user(phone="9000001"), "hunter2!x")

    assert user.check_password("hunter2!x") is False


def test_the_three_password_states_are_told_apart(django_user_model):
    """`unset` is healthy — a new account waiting for its link — and must not be
    reported as damage, or every repair run buries the real cases in noise."""
    hashed = django_user_model.objects.create_user(phone="9000002", password="hunter2!x")
    unset = django_user_model.objects.create_user(phone="9000003")
    plain = _damage(django_user_model.objects.create_user(phone="9000004"), "hunter2!x")

    assert selectors.password_state(hashed) == "hashed"
    assert selectors.password_state(unset) == "unset"
    assert selectors.password_state(plain) == "plaintext"
    assert [u.pk for u in selectors.accounts_with_plaintext_passwords()] == [plain.pk]


def test_rehashing_makes_the_owners_password_work_again(django_user_model):
    plain = _damage(django_user_model.objects.create_user(phone="9000005"), "hunter2!x")

    services.rehash_password(user=plain)

    plain.refresh_from_db()
    assert plain.check_password("hunter2!x")
    assert plain.password != "hunter2!x"
    assert selectors.password_state(plain) == "hashed"


def test_invalidating_returns_the_account_to_waiting_for_a_link(django_user_model):
    plain = _damage(django_user_model.objects.create_user(phone="9000006"), "hunter2!x")

    services.invalidate_password(user=plain)

    plain.refresh_from_db()
    assert plain.check_password("hunter2!x") is False
    assert plain.has_usable_password() is False
    assert selectors.password_state(plain) == "unset"


def test_the_command_reports_and_changes_nothing_by_default(django_user_model):
    from io import StringIO

    from django.core.management import call_command

    plain = _damage(django_user_model.objects.create_user(phone="9000007"), "hunter2!x")
    out = StringIO()

    call_command("repair_passwords", stdout=out)

    plain.refresh_from_db()
    assert selectors.password_state(plain) == "plaintext", "The report changed data."
    assert "9000007" in out.getvalue()
    # The value is somebody's password and this output lands in scrollback and CI logs.
    assert "hunter2!x" not in out.getvalue()


def test_the_command_refuses_both_answers_at_once(django_user_model):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    _damage(django_user_model.objects.create_user(phone="9000008"), "hunter2!x")

    with pytest.raises(CommandError):
        call_command("repair_passwords", "--rehash", "--invalidate")


def test_the_command_rehashes_when_told_to(django_user_model):
    from io import StringIO

    from django.core.management import call_command

    plain = _damage(django_user_model.objects.create_user(phone="9000009"), "hunter2!x")

    call_command("repair_passwords", "--rehash", stdout=StringIO())

    plain.refresh_from_db()
    assert plain.check_password("hunter2!x")
