"""Forms for the day and the photographs.

They validate shape and nothing else. No form here saves, and none decides who may
write about whom — the view hands cleaned values to a service, and the service and
the selectors decide.

The quick-entry form is deliberately almost empty. The plan's target is a teacher
recording a room's lunch while holding a tray, so the fast path is a kind and nothing
else, with the body optional. A required field here is a field somebody types "ok"
into thirty times.
"""

from django import forms

from apps.activities.models import ActivityKind, IncidentSeverity


class QuickEntryForm(forms.Form):
    """One tap: a kind, against one child or one room."""

    kind = forms.ChoiceField(choices=ActivityKind.choices)
    body = forms.CharField(required=False, max_length=2000)


class EntryForm(forms.Form):
    """The slower path — a note worth writing properly."""

    kind = forms.ChoiceField(choices=ActivityKind.choices, label="What happened")
    body = forms.CharField(
        label="Note",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Optional — parents read this."}),
        max_length=2000,
    )
    occurred_at = forms.DateTimeField(
        label="When",
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        help_text="Leave blank for now. Set it when writing up the morning in the evening.",
    )


class IncidentForm(forms.Form):
    """A child was hurt.

    Every field is required, including `action_taken`. An incident record that says
    what happened and not what was done about it is the half that reads badly a year
    later, and it is the half a parent asks about first.
    """

    severity = forms.ChoiceField(choices=IncidentSeverity.choices, label="How serious")
    occurred_at = forms.DateTimeField(
        label="When",
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        help_text="Leave blank for now.",
    )
    what_happened = forms.CharField(
        label="What happened",
        widget=forms.Textarea(attrs={"rows": 4}),
        max_length=4000,
    )
    action_taken = forms.CharField(
        label="What we did",
        widget=forms.Textarea(attrs={"rows": 3}),
        max_length=4000,
    )


class CaptionForm(forms.Form):
    caption = forms.CharField(required=False, max_length=500)


class UploadRequestForm(forms.Form):
    """What the browser asks for before it starts a direct-to-R2 PUT.

    `content_type` is validated against a short allow-list rather than accepted as
    given, because it is signed into the presigned URL — an unchecked value would let
    a caller pre-authorise an upload of anything at all to our bucket.
    """

    ALLOWED = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}

    filename = forms.CharField(max_length=255)
    content_type = forms.CharField(max_length=100)

    def clean_content_type(self) -> str:
        value = self.cleaned_data["content_type"].lower().strip()
        if value not in self.ALLOWED:
            raise forms.ValidationError("That is not a photograph we can accept.")
        return value


class ConfirmUploadForm(forms.Form):
    """What the browser reports once R2 has accepted the object."""

    byte_size = forms.IntegerField(required=False, min_value=0)
    width = forms.IntegerField(required=False, min_value=0)
    height = forms.IntegerField(required=False, min_value=0)
    taken_at = forms.DateTimeField(required=False)
