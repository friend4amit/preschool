"""Auth forms.

Two small overrides, both because the username field is a phone number. Django's
stock labels say "Username", which is exactly the word a parent will not recognise
on the one screen they have to get past.
"""

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.forms import SetPasswordForm as DjangoSetPasswordForm


class PhoneAuthenticationForm(AuthenticationForm):
    """Login by phone number. There is no signup page — an admin created this account."""

    username = forms.CharField(
        label="Phone number",
        max_length=20,
        widget=forms.TextInput(
            attrs={"autofocus": True, "autocomplete": "username", "inputmode": "tel"}
        ),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        # The stock message names the username field, which here would read
        # "correct phone number and password" — fine — but it also invites a
        # parent to try signing up. Say who to ask instead.
        "invalid_login": (
            "That phone number and password don't match. If you haven't set a "
            "password yet, ask the school office for your link."
        ),
    }


class SetPasswordForm(DjangoSetPasswordForm):
    """Used by the one-time link. Relabelled for a first-time set rather than a reset."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].label = "Choose a password"
        self.fields["new_password2"].label = "Type it again"
