"""Forms for the staff console.

Forms validate shape — a date is a date, a required field is present. They do not
decide anything: no form here saves, and none knows which branch it is for. The view
passes the cleaned values to a service, and the service decides. That is why
`StudentForm` is a plain `Form` in the places where a `ModelForm.save()` would quietly
put business logic in the presentation layer.

Choice fields that list classrooms or years are populated from a scoped queryset
handed in by the view. A form that queried for itself would be a way to enumerate
another branch's rooms from a select box.
"""

from django import forms

from apps.core.models import ConsentPurpose
from apps.people.models import (
    DocumentType,
    EmergencyContact,
    Guardian,
    Relationship,
    Staff,
    Student,
    StudentStatus,
)


class StudentSearchForm(forms.Form):
    """The student list's filter bar. A real GET form, so it works with JS off —
    htmx enhances the same markup rather than replacing it."""

    q = forms.CharField(
        required=False,
        label="Search",
        widget=forms.TextInput(
            attrs={
                "type": "search",
                "placeholder": "Name or admission number",
                "autocomplete": "off",
            }
        ),
    )
    classroom = forms.ChoiceField(required=False, label="Classroom", choices=[])
    status = forms.ChoiceField(
        required=False,
        label="Status",
        choices=[("", "Any status"), *StudentStatus.choices],
    )

    def __init__(self, *args, classrooms=None, **kwargs):
        super().__init__(*args, **kwargs)
        rooms = classrooms if classrooms is not None else []
        self.fields["classroom"].choices = [("", "Any classroom")] + [
            (str(room.pk), room.name) for room in rooms
        ]

    def clean_classroom(self) -> int | None:
        value = self.cleaned_data.get("classroom")
        return int(value) if value else None


class StudentForm(forms.ModelForm):
    """Editing an existing record. `branch` is absent on purpose: a student does not
    change branch through a form, and offering the field would let one be moved."""

    class Meta:
        model = Student
        fields = [
            "first_name",
            "last_name",
            "preferred_name",
            "date_of_birth",
            "admission_number",
            "status",
            "photo",
            "allergies",
            "medical_conditions",
            "medications",
            "blood_group",
            "doctor_name",
            "doctor_phone",
            "notes",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "allergies": forms.Textarea(attrs={"rows": 2}),
            "medical_conditions": forms.Textarea(attrs={"rows": 2}),
            "medications": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "allergies": "Shown on every roster and attendance grid, not hidden in a tab.",
            "preferred_name": "What the child actually answers to.",
        }


class GuardianForm(forms.ModelForm):
    """`user` is absent: an account is created by an explicit action with a link to
    hand over, never as a side effect of saving a contact detail."""

    class Meta:
        model = Guardian
        fields = ["full_name", "phone", "email", "address", "occupation"]
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}


class NewGuardianForm(GuardianForm):
    """Adding a guardian to a child: their details, plus how they are related to that
    particular child. The relationship belongs to the link, not to the person — a
    woman is a mother to one child and an aunt to another."""

    relationship = forms.ChoiceField(choices=Relationship.choices)
    is_primary = forms.BooleanField(
        required=False,
        label="Primary contact",
        help_text="More than one is allowed — split families routinely have two.",
    )

    class Meta(GuardianForm.Meta):
        pass


class LinkGuardianForm(forms.Form):
    """Attach an existing guardian to another child — the sibling case, which is why
    the guardian is chosen rather than retyped."""

    guardian = forms.ChoiceField(label="Guardian", choices=[])
    relationship = forms.ChoiceField(choices=Relationship.choices)
    is_primary = forms.BooleanField(
        required=False,
        label="Primary contact",
        help_text="More than one is allowed — split families routinely have two.",
    )

    def __init__(self, *args, guardians=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["guardian"].choices = [
            (str(g.pk), f"{g.full_name} — {g.phone}") for g in (guardians or [])
        ]

    def clean_guardian(self) -> int:
        return int(self.cleaned_data["guardian"])


class EmergencyContactForm(forms.ModelForm):
    class Meta:
        model = EmergencyContact
        fields = ["name", "relationship", "phone", "priority"]
        help_texts = {
            "relationship": "Grandmother, neighbour, uncle — whoever actually answers.",
            "priority": "1 is rung first.",
        }


class EnrollmentForm(forms.Form):
    """Placing a child in a room. Both querysets are scoped by the view."""

    classroom = forms.ChoiceField(label="Classroom", choices=[])
    academic_year = forms.ChoiceField(label="Academic year", choices=[])

    def __init__(self, *args, classrooms=None, years=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["classroom"].choices = [(str(c.pk), c.name) for c in (classrooms or [])]
        self.fields["academic_year"].choices = [(str(y.pk), y.name) for y in (years or [])]

    def clean_classroom(self) -> int:
        return int(self.cleaned_data["classroom"])

    def clean_academic_year(self) -> int:
        return int(self.cleaned_data["academic_year"])


class StaffForm(forms.ModelForm):
    class Meta:
        model = Staff
        fields = ["designation", "qualifications", "joined_on", "left_on", "emergency_phone"]
        widgets = {
            "joined_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "left_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }


class DocumentForm(forms.Form):
    doc_type = forms.ChoiceField(choices=DocumentType.choices, label="Type")
    file = forms.FileField(label="File")
    expires_on = forms.DateField(
        required=False,
        label="Expires on",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="Only where one applies — an immunisation record, say.",
    )


# The consent questions asked at the admissions desk, in the order they are asked.
# `photos_in_app` and `photos_shared_with_class` are separate questions on purpose:
# most classroom photos hold several children, and the second is what decides whether
# a photo may be shown to anyone but this family. See docs/plan.md.
CONSENT_PURPOSES = [
    ConsentPurpose.PHOTOS_IN_APP,
    ConsentPurpose.PHOTOS_SHARED_WITH_CLASS,
    ConsentPurpose.PHOTOS_IN_MARKETING,
    ConsentPurpose.COMMS,
]


class ConsentForm(forms.Form):
    """Every box unticked, every time. Under the DPDP Act consent is an answer given,
    not an answer assumed, so nothing here may default to True — including on the edit
    screen, where the current values are shown by the view as `initial`."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for purpose in CONSENT_PURPOSES:
            self.fields[purpose.value] = forms.BooleanField(
                required=False, initial=False, label=purpose.label
            )

    def answers(self) -> dict[str, bool]:
        return {p.value: bool(self.cleaned_data.get(p.value)) for p in CONSENT_PURPOSES}


class AdmissionForm(forms.Form):
    """Enquiry to enrolled student on one screen.

    Prefilled from the enquiry by the view, so nothing typed on the public site is
    typed again — that being the entire point of the join between the two halves of
    the product.
    """

    child_name = forms.CharField(label="Child's full name", max_length=200)
    date_of_birth = forms.DateField(
        label="Date of birth",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    preferred_name = forms.CharField(label="Known as", max_length=100, required=False)
    allergies = forms.CharField(
        label="Allergies",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Anything a teacher holding a snack needs to know.",
    )

    guardian_name = forms.CharField(label="Guardian's name", max_length=200)
    guardian_phone = forms.CharField(label="Guardian's phone", max_length=20)
    guardian_email = forms.EmailField(label="Guardian's email", required=False)
    relationship = forms.ChoiceField(choices=Relationship.choices, initial=Relationship.MOTHER)

    classroom = forms.ChoiceField(required=False, label="Classroom", choices=[])
    academic_year = forms.ChoiceField(required=False, label="Academic year", choices=[])

    open_portal_account = forms.BooleanField(
        required=False,
        initial=True,
        label="Create a portal account for this guardian",
        help_text=(
            "Creates the login and produces a one-time link to hand over. "
            "Consent is recorded against the account, so declining this skips it."
        ),
    )

    def __init__(self, *args, classrooms=None, years=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["classroom"].choices = [("", "Not decided yet")] + [
            (str(c.pk), c.name) for c in (classrooms or [])
        ]
        self.fields["academic_year"].choices = [("", "Not decided yet")] + [
            (str(y.pk), y.name) for y in (years or [])
        ]

    def clean_classroom(self) -> int | None:
        value = self.cleaned_data.get("classroom")
        return int(value) if value else None

    def clean_academic_year(self) -> int | None:
        value = self.cleaned_data.get("academic_year")
        return int(value) if value else None

    def clean(self):
        cleaned = super().clean()
        # A room without a year cannot become an Enrollment: the open-enrolment
        # constraint is per student per year, so a year is what makes the row mean
        # anything. Catch it here rather than silently dropping the classroom.
        if cleaned.get("classroom") and not cleaned.get("academic_year"):
            self.add_error("academic_year", "Pick a year as well, or leave the room undecided.")
        return cleaned


class AccountForm(forms.Form):
    """Creating a login for someone who is not a guardian — a teacher, usually."""

    phone = forms.CharField(label="Phone number", max_length=20)
    full_name = forms.CharField(label="Full name", max_length=200)
    email = forms.EmailField(required=False)
    role = forms.ChoiceField(choices=[], label="Role")

    def __init__(self, *args, roles=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = roles or []
