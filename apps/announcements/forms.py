"""The form behind a notice.

Validates shape only. It does not save, and it does not decide which rooms this user
may write to — the view narrows the classroom queryset to the ones the user actually
works at, and `services.create_announcement` refuses a room from another branch even
if something ever bypasses the form.
"""

from django import forms

from apps.core.models import Classroom


class AnnouncementForm(forms.Form):
    """Write a notice, to the school or to one room.

    Audience is a single radio-style choice rather than a checkbox plus a dropdown.
    "School-wide" and "which room" as two independent widgets is how you get a notice
    that is both, which the database then refuses at the worst possible moment.
    """

    SCHOOL = "school"

    title = forms.CharField(max_length=200, label="Title")
    body = forms.CharField(
        label="Notice",
        widget=forms.Textarea(attrs={"rows": 6}),
        max_length=8000,
    )
    audience = forms.ChoiceField(label="Who sees this", choices=[])
    expires_on = forms.DateField(
        label="Stop showing it after",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Leave blank for a notice that stays until you withdraw it.",
    )
    is_pinned = forms.BooleanField(
        label="Pin to the top",
        required=False,
        help_text="For the few that must not be scrolled past.",
    )

    def __init__(self, *args, classrooms=None, **kwargs):
        super().__init__(*args, **kwargs)
        rooms = list(classrooms or [])
        self.fields["audience"].choices = [(self.SCHOOL, "Whole school")] + [
            (str(room.pk), room.name) for room in rooms
        ]
        self._rooms = {str(room.pk): room for room in rooms}

    @property
    def classroom(self) -> Classroom | None:
        """The room chosen, or None for a school-wide notice. Valid after `is_valid`."""
        return self._rooms.get(self.cleaned_data["audience"])

    @property
    def is_school_wide(self) -> bool:
        return self.cleaned_data["audience"] == self.SCHOOL
