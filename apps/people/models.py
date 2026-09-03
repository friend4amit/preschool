"""Students, the adults around them, and the records a preschool cannot operate without.

Three decisions here are load-bearing and are not conveniences to be tidied away later.

1. **A guardian is never a column on the student.** Siblings share guardians and split
   families have two primary contacts, so the link is a many-to-many *through*
   `StudentGuardian`, which carries the relationship and who to call first.
2. **`EmergencyContact` is not a `Guardian`.** The person a school actually rings is
   often a grandparent or a neighbour with no legal guardianship and no portal account.
   Modelling them as guardians would either grant them a login or lose them entirely.
3. **`AuthorizedPickup` has a validity window from day one.** The common case is
   temporary — "her uncle, this Friday only" — and with split families this is a legal
   question, not a convenience. A boolean here would have to be widened after the first
   awkward afternoon.

`Staff` is a profile attached to a `User`, not a parallel identity: a teacher gets an
account exactly as a parent does, and their `BranchMembership` carries the role. There
is one account system.

Every model here carries `branch` via `BranchScopedModel`, and none of them scope
themselves — `for_user()` in selectors.py does that, explicitly, at each call site.
"""

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.core.models import AcademicYear, BranchScopedModel, Classroom, User


def student_document_path(instance: "Document", filename: str) -> str:
    return f"students/{instance.student_id}/documents/{filename}"


def pickup_photo_path(instance: "AuthorizedPickup", filename: str) -> str:
    return f"students/{instance.student_id}/pickup/{filename}"


class StudentStatus(models.TextChoices):
    ENROLLED = "enrolled", "Enrolled"
    WAITLIST = "waitlist", "Waitlist"
    LEFT = "left", "Left"


class Student(BranchScopedModel):
    """A child.

    The medical fields are here rather than in a separate profile table on purpose:
    they are read on every roster and attendance grid, and the person who needs them
    is holding a snack, not browsing records. A join to reach an allergy is a join
    somebody will skip.
    """

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    # What the child answers to, which is frequently not the name on the certificate.
    preferred_name = models.CharField(max_length=100, blank=True)
    date_of_birth = models.DateField()
    admission_number = models.CharField(max_length=30, blank=True)
    photo = models.ImageField(upload_to="students/photos/", blank=True)
    status = models.CharField(
        max_length=20, choices=StudentStatus.choices, default=StudentStatus.ENROLLED
    )

    # --- child safety. Not a "later" tab. ---
    allergies = models.TextField(blank=True)
    medical_conditions = models.TextField(blank=True)
    medications = models.TextField(blank=True)
    blood_group = models.CharField(max_length=5, blank=True)
    doctor_name = models.CharField(max_length=200, blank=True)
    doctor_phone = models.CharField(max_length=20, blank=True)

    notes = models.TextField(blank=True)
    guardians = models.ManyToManyField(
        "people.Guardian", through="people.StudentGuardian", related_name="students"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # History on Student and Consent only, not everywhere. These are the two a
    # parent might one day dispute — "you changed my child's allergy record" and
    # "I never agreed to that" — and a table of every edit to every model is a
    # cost with no reader. Payment joins them in Phase 6.
    history = HistoricalRecords()

    class Meta:
        ordering = ["first_name", "last_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "admission_number"],
                condition=~models.Q(admission_number=""),
                name="uniq_admission_number_per_branch",
            )
        ]

    def __str__(self) -> str:
        return self.display_name

    @property
    def display_name(self) -> str:
        first = self.preferred_name or self.first_name
        return f"{first} {self.last_name}".strip()

    @property
    def has_medical_flags(self) -> bool:
        """Drives the marker on rosters. Deliberately broad — a teacher would rather
        check a record that turns out to be routine than miss one that isn't."""
        return bool(self.allergies or self.medical_conditions or self.medications)


class Guardian(BranchScopedModel):
    """A parent or legal guardian.

    `user` is nullable because a guardian exists in the records the moment an
    admission is taken, and the portal account is created afterwards — by an admin,
    who then hands over a one-time set-password link. A guardian with no account is
    a normal, long-lived state, not an error.
    """

    user = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="guardian_profile"
    )
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    occupation = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "phone"], name="uniq_guardian_phone_branch")
        ]

    def __str__(self) -> str:
        return self.full_name


class Relationship(models.TextChoices):
    MOTHER = "mother", "Mother"
    FATHER = "father", "Father"
    GRANDPARENT = "grandparent", "Grandparent"
    SIBLING = "sibling", "Sibling"
    LEGAL_GUARDIAN = "legal_guardian", "Legal guardian"
    OTHER = "other", "Other"


class StudentGuardian(models.Model):
    """The link, and what it means.

    No `branch` of its own: both ends carry one, and duplicating it here would create
    a third place for them to disagree.
    """

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="guardian_links")
    guardian = models.ForeignKey(Guardian, on_delete=models.CASCADE, related_name="student_links")
    relationship = models.CharField(max_length=20, choices=Relationship.choices)
    # Who to call first. More than one may be primary — split families routinely have
    # two, and forcing a single one would make the office pick a favourite.
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "guardian"], name="uniq_student_guardian_pair"
            )
        ]

    def __str__(self) -> str:
        return f"{self.guardian} — {self.get_relationship_display()} of {self.student}"


class EmergencyContact(BranchScopedModel):
    """Who to ring when the guardians cannot be reached.

    Separate from `Guardian` deliberately: this person needs no account, holds no
    legal guardianship, and may be a neighbour. `priority` is the calling order, and
    an enrolment is not complete without at least one of these.
    """

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="emergency_contacts"
    )
    name = models.CharField(max_length=200)
    relationship = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    priority = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["priority", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.relationship})"


class AuthorizedPickup(BranchScopedModel):
    """Someone allowed to take a child home, for a stated period.

    The window is the point. Most authorisations are temporary, and an expired one
    that still reads as valid is the failure mode this model exists to prevent.
    """

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="authorized_pickups"
    )
    name = models.CharField(max_length=200)
    relationship = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    # So the person at the gate can check a face, not just a name.
    photo = models.ImageField(upload_to=pickup_photo_path, blank=True)
    valid_from = models.DateField(default=timezone.localdate)
    # Null means open-ended — a parent's sibling who collects every week.
    valid_to = models.DateField(null=True, blank=True)
    authorized_by = models.ForeignKey(
        Guardian, on_delete=models.PROTECT, related_name="pickups_authorized"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gte=models.F("valid_from")),
                name="pickup_window_ends_after_it_starts",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.relationship})"

    def is_valid_on(self, day) -> bool:
        if day < self.valid_from:
            return False
        return self.valid_to is None or day <= self.valid_to


class Enrollment(BranchScopedModel):
    """Student x classroom x academic year, with the dates.

    In `people` rather than `core`: AcademicYear and Classroom belong to the
    organisation and exist before any child does, but an enrolment is a fact about a
    student. Putting it in core would point that dependency the wrong way.
    """

    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="enrollments")
    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT, related_name="enrollments")
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.PROTECT, related_name="enrollments"
    )
    joined_on = models.DateField(default=timezone.localdate)
    # Null means still enrolled. A row is never deleted — a child who left in March is
    # part of that year's roll, and the attendance and invoices still point at it.
    left_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-joined_on"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "academic_year"],
                condition=models.Q(left_on__isnull=True),
                name="one_open_enrollment_per_student_per_year",
            ),
            models.CheckConstraint(
                condition=models.Q(left_on__isnull=True)
                | models.Q(left_on__gte=models.F("joined_on")),
                name="enrollment_ends_after_it_starts",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.student} in {self.classroom} ({self.academic_year})"

    @property
    def is_open(self) -> bool:
        return self.left_on is None


class Staff(BranchScopedModel):
    """A teacher, administrator or accountant.

    A profile on a `User`, not a second identity. The role that governs permissions
    lives on `BranchMembership`; `designation` here is what goes on a name badge.
    """

    user = models.OneToOneField(User, on_delete=models.PROTECT, related_name="staff_profile")
    designation = models.CharField(max_length=100, blank=True)
    qualifications = models.CharField(max_length=300, blank=True)
    joined_on = models.DateField(null=True, blank=True)
    left_on = models.DateField(null=True, blank=True)
    emergency_phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "staff"
        ordering = ["user__full_name"]

    def __str__(self) -> str:
        return f"{self.user} — {self.designation}" if self.designation else str(self.user)

    @property
    def is_current(self) -> bool:
        return self.left_on is None


class DocumentType(models.TextChoices):
    BIRTH_CERTIFICATE = "birth_certificate", "Birth certificate"
    IMMUNISATION = "immunisation", "Immunisation record"
    GUARDIAN_ID = "guardian_id", "Guardian ID"
    ADDRESS_PROOF = "address_proof", "Address proof"
    PHOTO = "photo", "Photograph"
    OTHER = "other", "Other"


class Document(BranchScopedModel):
    """A file against a student. Small, but every school needs it, and it is far
    easier to add now than to retrofit into a settled student page later."""

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=30, choices=DocumentType.choices)
    file = models.FileField(upload_to=student_document_path)
    # Only some types expire — an ID does, a birth certificate does not.
    expires_on = models.DateField(null=True, blank=True)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="documents_uploaded", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_doc_type_display()} — {self.student}"
