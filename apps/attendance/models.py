"""Who was here today, and who took them home.

Two records that look similar and are not. Attendance is an operational fact the
school corrects freely — a child marked absent who turns up at ten is edited, and
nobody minds. A pickup record is a safety record: it says which adult a child left
with, and it is the thing somebody reads back six months later when a question is
asked. So the second one carries a database constraint the first does not.

`docs/plan.md` is blunt about why this phase exists at all: an authorised-pickup list
nobody checks at the door is decoration. The `AuthorizedPickup` rows Phase 2 collected
only start earning their keep here.
"""

from django.db import models
from django.utils import timezone

from apps.core.models import BranchScopedModel, Classroom, User
from apps.people.models import AuthorizedPickup, Guardian, Staff, Student


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "Present"
    ABSENT = "absent", "Absent"
    LATE = "late", "Late"
    HALF_DAY = "half_day", "Half day"
    HOLIDAY = "holiday", "Holiday"


class AttendanceRecord(BranchScopedModel):
    """One child, one day.

    `classroom` is stored rather than derived from the open enrolment, because a
    child moves rooms mid-year and last March's register has to keep saying which
    room they were in last March. Deriving it at read time would silently rewrite
    history the day somebody is moved.
    """

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="attendance")
    classroom = models.ForeignKey(
        Classroom, on_delete=models.PROTECT, related_name="attendance", null=True, blank=True
    )
    date = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=20, choices=AttendanceStatus.choices, default=AttendanceStatus.PRESENT
    )
    arrived_at = models.TimeField(null=True, blank=True, help_text="Only for a late arrival.")
    left_at = models.TimeField(null=True, blank=True, help_text="Only for an early pickup.")
    reason = models.CharField(max_length=200, blank=True)
    marked_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="attendance_marked", null=True, blank=True
    )
    marked_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "student__first_name"]
        constraints = [
            # The plan's "marking the same day twice doesn't create duplicates",
            # enforced where nothing can bypass it. The service upserts against it.
            models.UniqueConstraint(fields=["student", "date"], name="one_attendance_per_day")
        ]
        indexes = [
            # The only two reads this table exists for: one room on one day, and
            # one child across a month.
            models.Index(fields=["classroom", "date"], name="attendance_room_day_idx"),
            models.Index(fields=["student", "date"], name="attendance_child_day_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.student} - {self.date} - {self.get_status_display()}"

    @property
    def counts_as_attended(self) -> bool:
        """What the monthly percentage counts. A half day counts — the child was here.

        Holidays are excluded from both halves of the fraction rather than counted as
        absence. A school closure is not a child's absence, and letting it read as one
        makes every percentage wrong in December.
        """
        return self.status in {
            AttendanceStatus.PRESENT,
            AttendanceStatus.LATE,
            AttendanceStatus.HALF_DAY,
        }


class PickupRecord(BranchScopedModel):
    """Which adult a child left with.

    Either an authorised person, or an explicit override carrying a reason and the
    staff member who allowed it. The check constraint is the point of the whole
    model: a release to nobody identifiable cannot be written, so the record can be
    trusted when it is read back.
    """

    attendance = models.OneToOneField(
        AttendanceRecord, on_delete=models.CASCADE, related_name="pickup"
    )
    # Whichever of these is set identifies the person. Both are nullable because a
    # guardian and an authorised pickup live in different tables, not different rows.
    authorized_pickup = models.ForeignKey(
        AuthorizedPickup, on_delete=models.PROTECT, null=True, blank=True, related_name="pickups"
    )
    guardian = models.ForeignKey(
        Guardian, on_delete=models.PROTECT, null=True, blank=True, related_name="pickups"
    )
    # The parent who phones ahead. Free text on purpose: the whole point is that this
    # person is on no list, and forcing them onto one would mean creating a permanent
    # authorisation for a single afternoon.
    override_name = models.CharField(max_length=200, blank=True)
    override_reason = models.CharField(max_length=300, blank=True)

    released_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="pickups_released", null=True, blank=True
    )
    released_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-released_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(authorized_pickup__isnull=False)
                    | models.Q(guardian__isnull=False)
                    | (~models.Q(override_name="") & ~models.Q(override_reason=""))
                ),
                name="pickup_identifies_someone",
            )
        ]

    def __str__(self) -> str:
        return f"{self.attendance.student} collected by {self.collected_by}"

    @property
    def collected_by(self) -> str:
        if self.authorized_pickup_id:
            return self.authorized_pickup.name
        if self.guardian_id:
            return self.guardian.full_name
        return self.override_name

    @property
    def was_override(self) -> bool:
        """Read on the day's summary, so the office can find the exceptions without
        reading every row."""
        return not (self.authorized_pickup_id or self.guardian_id)


class StaffAttendance(BranchScopedModel):
    """The same shape for staff, deliberately in its own table.

    Merging the two behind a generic relation would save a model and cost the thing
    that matters: a query for "who was in Nursery A today" must not be able to return
    a teacher's absence record by accident.
    """

    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name="attendance")
    date = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=20, choices=AttendanceStatus.choices, default=AttendanceStatus.PRESENT
    )
    reason = models.CharField(max_length=200, blank=True)
    marked_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="staff_attendance_marked",
        null=True,
        blank=True,
    )
    marked_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        verbose_name_plural = "staff attendance"
        constraints = [
            models.UniqueConstraint(fields=["staff", "date"], name="one_staff_attendance_per_day")
        ]

    def __str__(self) -> str:
        return f"{self.staff} - {self.date} - {self.get_status_display()}"
