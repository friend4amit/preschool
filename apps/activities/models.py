"""The day a child had, and the photographs of it.

Phase 4. Three ideas live here and they are deliberately not one:

1. `ActivityEntry` — the casual feed. A meal, a nap, a note. Published in a batch at
   the end of the day and *seen*.
2. `IncidentReport` — its own model, never an ActivityEntry kind. When a child is
   hurt, "we told the parent" has to be a record rather than a memory, so this one
   is *acknowledged*, with a timestamp, and cannot be satisfied by a parent merely
   scrolling past it.
3. `MediaAsset` / `MediaTag` — the photographs. The bucket is private and the bytes
   are served by short-lived presigned GET URLs generated after a consent check
   (docs/plan.md). Nothing here holds a public URL, because a URL that works without
   passing through our permission code makes every rule below decorative.

Tagging is done by a teacher, two taps. There is no face recognition on children and
there will not be — it is a legal and reputational minefield under the DPDP Act, and
the teacher already knows who is in the photo.
"""

from django.db import models
from django.utils import timezone

from apps.core.models import BranchScopedModel, Classroom, User
from apps.people.models import Student


class ActivityKind(models.TextChoices):
    MEAL = "meal", "Meal"
    NAP = "nap", "Nap"
    LEARNING = "learning", "Learning"
    NOTE = "note", "Note"
    MILESTONE = "milestone", "Milestone"


class ActivityEntry(BranchScopedModel):
    """One thing that happened, to one child or to a whole room.

    `student` and `classroom` are both nullable and exactly one is set. The bulk path
    — "everyone napped" — writes a single classroom row rather than thirty student
    rows, because thirty rows is what makes a teacher stop using the feature by
    Wednesday. The parent's feed unions the two.
    """

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="activity_entries", null=True, blank=True
    )
    classroom = models.ForeignKey(
        Classroom, on_delete=models.PROTECT, related_name="activity_entries", null=True, blank=True
    )
    kind = models.CharField(max_length=20, choices=ActivityKind.choices)
    body = models.TextField(blank=True)

    # When it happened, not when it was typed. Teachers write the morning up in the
    # evening; ordering a feed by created_at shows a parent their child's day
    # backwards.
    occurred_at = models.DateTimeField(default=timezone.now)

    author = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="activity_entries", null=True, blank=True
    )
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["-occurred_at"], name="activity_occurred_idx"),
            models.Index(fields=["student", "-occurred_at"], name="activity_student_idx"),
        ]
        constraints = [
            # Exactly one target. A row with neither belongs to nobody and would
            # never appear in a feed; a row with both would appear in one feed twice.
            models.CheckConstraint(
                condition=(
                    models.Q(student__isnull=False, classroom__isnull=True)
                    | models.Q(student__isnull=True, classroom__isnull=False)
                ),
                name="activity_targets_student_xor_classroom",
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} — {self.student or self.classroom}"


class IncidentSeverity(models.TextChoices):
    MINOR = "minor", "Minor"
    MODERATE = "moderate", "Moderate"
    SERIOUS = "serious", "Serious"


class IncidentReport(BranchScopedModel):
    """A child was hurt, and this is the record that the family was told.

    Separate from ActivityEntry on purpose. The feed's semantics are "published, and
    parents will see it"; an incident's are "acknowledged by a named person at a known
    time". Folding this into a `kind` would quietly downgrade the second into the
    first, and that difference is the whole reason the record exists.
    """

    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="incidents")
    severity = models.CharField(max_length=20, choices=IncidentSeverity.choices)
    occurred_at = models.DateTimeField(default=timezone.now)
    what_happened = models.TextField()
    action_taken = models.TextField()

    # PROTECT, not SET_NULL: "which member of staff dealt with this" must not become
    # unanswerable because somebody left the school.
    staff_responsible = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="incidents_responsible"
    )
    reported_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="incidents_reported", null=True, blank=True
    )

    acknowledged_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="incidents_acknowledged", null=True, blank=True
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [models.Index(fields=["student", "-occurred_at"], name="incident_student_idx")]

    def __str__(self) -> str:
        return f"{self.get_severity_display()} incident — {self.student}"

    @property
    def is_acknowledged(self) -> bool:
        return self.acknowledged_at is not None


class UploadState(models.TextChoices):
    """A presigned direct-to-R2 PUT means the browser talks to Cloudflare and then
    tells us about it — two steps that can fail independently.

    PENDING is the row written before the browser starts. STORED is set once the
    object is confirmed to exist. FAILED is what the nightly reconciliation marks a
    row whose object never arrived. Without these three states you accumulate storage
    you are paying for and cannot see.
    """

    PENDING = "pending", "Pending"
    STORED = "stored", "Stored"
    FAILED = "failed", "Failed"


class MediaAsset(BranchScopedModel):
    """One photograph in the private bucket.

    Holds a key, never a URL. `.url()` on a public storage would be a permanent
    unauthenticated link to a photograph of a child; the selector issues a
    short-lived presigned GET instead, and only after the consent gate has run.
    """

    key = models.CharField(max_length=500, unique=True)
    content_type = models.CharField(max_length=100, blank=True)
    byte_size = models.PositiveIntegerField(null=True, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    # Generated in the background; absent until the worker has been round.
    thumbnail_key = models.CharField(max_length=500, blank=True)

    caption = models.CharField(max_length=500, blank=True)

    # From EXIF where the phone recorded it, falling back to upload time. The feed
    # orders on this, so an evening upload of the morning's photos still reads
    # forwards.
    taken_at = models.DateTimeField(default=timezone.now)

    uploaded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="media_uploaded", null=True, blank=True
    )
    upload_state = models.CharField(
        max_length=20, choices=UploadState.choices, default=UploadState.PENDING
    )
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    students = models.ManyToManyField(
        Student, through="activities.MediaTag", related_name="media_assets"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-taken_at", "-id"]
        indexes = [
            models.Index(fields=["-taken_at"], name="media_taken_idx"),
            models.Index(fields=["upload_state"], name="media_upload_state_idx"),
        ]

    def __str__(self) -> str:
        return self.caption or self.key


class MediaTag(models.Model):
    """This child is in this photograph. Applied by a teacher, never automatically.

    No `branch` of its own: both ends carry one, and a third copy is a third place
    for them to disagree.
    """

    media = models.ForeignKey(MediaAsset, on_delete=models.CASCADE, related_name="tags")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="media_tags")
    tagged_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="media_tags_applied", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["media", "student"], name="uniq_media_student_tag")
        ]

    def __str__(self) -> str:
        return f"{self.student} in {self.media}"
