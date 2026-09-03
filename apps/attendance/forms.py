"""Forms for the register.

They validate shape and nothing else — no form here saves, and none decides who may
mark whom. The view hands cleaned values to a service, and the service decides.

The pickup form is the one with real work in it, because "who is allowed to collect
this child" is a question with three possible shapes and only one of them is free
text.
"""

from django import forms

from apps.attendance.models import AttendanceStatus


class MarkForm(forms.Form):
    """One tap on the grid."""

    status = forms.ChoiceField(choices=AttendanceStatus.choices)
    arrived_at = forms.TimeField(required=False)
    left_at = forms.TimeField(required=False)
    reason = forms.CharField(required=False, max_length=200)


class DetailForm(forms.Form):
    """The slower path: a late arrival with a time, or an absence with a reason."""

    status = forms.ChoiceField(choices=AttendanceStatus.choices, label="Status")
    arrived_at = forms.TimeField(
        required=False,
        label="Arrived at",
        widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        help_text="Only for a late arrival.",
    )
    left_at = forms.TimeField(
        required=False,
        label="Left at",
        widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        help_text="Only for an early pickup.",
    )
    reason = forms.CharField(required=False, max_length=200, label="Note")


class PickupForm(forms.Form):
    """Who is collecting, from this child's own list — or an override.

    `collected_by` is built from a scoped queryset handed in by the view. A form that
    queried for itself would be a way to enumerate another child's authorised adults
    from a select box, which on this particular screen is the whole thing we are
    trying to prevent.
    """

    collected_by = forms.ChoiceField(label="Collected by", choices=[])
    override_name = forms.CharField(
        required=False,
        max_length=200,
        label="Name",
        help_text="Only if the person is not on the list above.",
    )
    override_reason = forms.CharField(
        required=False,
        max_length=300,
        label="Why",
        help_text="Who authorised it, and how. This is the line somebody reads back later.",
    )

    OVERRIDE = "override"

    def __init__(self, *args, pickups=None, guardians=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [(f"guardian:{g.pk}", f"{g.full_name} (guardian)") for g in (guardians or [])]
        choices += [(f"pickup:{p.pk}", f"{p.name} ({p.relationship})") for p in (pickups or [])]
        # Last, and named plainly. Making the exception look like an ordinary option
        # is how it stops being an exception.
        choices.append((self.OVERRIDE, "Someone else — not on this list"))
        self.fields["collected_by"].choices = choices

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("collected_by") != self.OVERRIDE:
            return cleaned

        # Both, or neither. The database enforces this too; saying it here means the
        # person at the door gets a sentence instead of a 500.
        if not cleaned.get("override_name"):
            self.add_error("override_name", "Who is collecting the child?")
        if not cleaned.get("override_reason"):
            self.add_error("override_reason", "Say who authorised this, and how.")
        return cleaned
