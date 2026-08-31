"""Forms for the public site.

Validation that is about *what a valid enquiry is* stays here at the edge; anything
about what the school then does with it belongs in services.py.
"""

from datetime import date

from django import forms
from django.utils import timezone

from apps.website.models import Program


class EnquiryForm(forms.Form):
    """Deliberately short.

    Every extra required field on an admissions form costs enquiries, and the school
    can ask the rest on the phone. Name and phone are the only things that are
    genuinely needed to call someone back.
    """

    guardian_name = forms.CharField(
        label="Your name",
        max_length=200,
        widget=forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Priya Sharma"}),
    )
    phone = forms.CharField(
        label="Phone number",
        max_length=20,
        widget=forms.TextInput(
            attrs={"autocomplete": "tel", "inputmode": "tel", "placeholder": "98765 43210"}
        ),
    )
    email = forms.EmailField(
        label="Email", required=False, widget=forms.EmailInput(attrs={"autocomplete": "email"})
    )
    child_name = forms.CharField(label="Child's name", max_length=200, required=False)
    child_dob = forms.DateField(
        label="Child's date of birth",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Helps us suggest the right programme.",
    )
    program = forms.ModelChoiceField(
        label="Programme of interest",
        queryset=Program.objects.none(),
        required=False,
        empty_label="Not sure yet",
    )
    message = forms.CharField(
        label="Anything you'd like to tell us",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    # Honeypot: bots fill every field they find. Real browsers leave it alone
    # because it is hidden and marked not-autocomplete.
    website = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"tabindex": "-1", "autocomplete": "off", "aria-hidden": "true"}
        ),
    )

    def __init__(self, *args, programs=None, **kwargs):
        super().__init__(*args, **kwargs)
        if programs is not None:
            self.fields["program"].queryset = programs

    def clean_phone(self) -> str:
        """Accept what people actually type, store what we can dial.

        Indian mobile numbers arrive as '98765 43210', '+91 98765 43210', and
        '098765-43210'. Rejecting any of those loses a real family over formatting.
        """
        raw = self.cleaned_data["phone"]
        digits = "".join(c for c in raw if c.isdigit())
        digits = digits.removeprefix("91") if len(digits) == 12 else digits
        digits = digits.lstrip("0")
        if len(digits) != 10:
            raise forms.ValidationError("Enter a 10-digit Indian mobile number.")
        return digits

    def clean_child_dob(self) -> date | None:
        dob = self.cleaned_data.get("child_dob")
        if dob and dob > timezone.localdate():
            raise forms.ValidationError("That date is in the future.")
        if dob and dob.year < timezone.localdate().year - 18:
            raise forms.ValidationError("Please check the year.")
        return dob

    def clean_website(self) -> str:
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Sorry, we couldn't accept that.")
        return ""
