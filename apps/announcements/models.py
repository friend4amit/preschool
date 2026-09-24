"""What the school tells every parent at once, and who has read it.

Phase 7. Two models, and the second one is the interesting one.

`Announcement` borrows `ActivityEntry`'s targeting exactly: school-wide or one
classroom, never both and never neither, enforced by a CheckConstraint rather than by
whichever service happened to write the row. A parent's feed unions the two the same
way the photo feed does.

`AnnouncementRead` is a **per-item read receipt**, and it is a table rather than a
session key on purpose. `apps/activities/context_processors.py` explains at length why
the photo badge lives in the session — "since last visit" is a browser-local question
and a migration would buy nothing — and then says where that stops being true:

    for a per-item read receipt — which Phase 7 wants for announcements — it would
    not be, and that is the point at which this earns a column.

This is that point. "Has this guardian read the fee-hike notice" is a question about a
person and a notice, not about a browser, and the office will eventually ask it out
loud. The photo badge is deliberately left alone.
"""

from django.db import models
from django.utils import timezone

from apps.core.models import BranchScopedModel, Classroom, User


class Announcement(BranchScopedModel):
    """One notice, to the whole school or to one room.

    Unpublished is the default, the same as photographs and the day's entries: a
    half-written notice about a fee revision is not something a draft state should
    have to be remembered for.

    `expires_on` is a *date* and nullable. Most notices are events — sports day, a
    holiday, a PTM — and stop being news the day after. A notice with no expiry is
    the permanent kind ("the gate code changed"), so the nullable case is the
    exception rather than a forgotten field.
    """

    title = models.CharField(max_length=200)
    body = models.TextField()

    # Exactly one of these, like ActivityEntry. Null classroom means the whole school.
    classroom = models.ForeignKey(
        Classroom, on_delete=models.PROTECT, related_name="announcements", null=True, blank=True
    )
    is_school_wide = models.BooleanField(default=False)

    # Pinned notices sit above the rest of the feed regardless of date. Reserved for
    # the handful a parent should not have to scroll for; nothing enforces restraint
    # but the office, which is the right place for that judgement.
    is_pinned = models.BooleanField(default=False)

    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True)

    author = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="announcements", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Pinned first, then newest published. `published_at` is null while a draft,
        # and NULLS FIRST would float every draft to the top of the staff list; the
        # staff list is the only place drafts appear, and "newest draft first" is
        # what a writer expects there, so the null ordering is left explicit.
        ordering = ["-is_pinned", models.F("published_at").desc(nulls_first=True), "-id"]
        indexes = [
            models.Index(fields=["-published_at"], name="announce_published_idx"),
            models.Index(fields=["classroom", "-published_at"], name="announce_room_idx"),
        ]
        constraints = [
            # School-wide XOR one room. A row with neither reaches nobody; a row with
            # both would appear twice in the feed of a parent whose child is in that
            # room, which is the same bug ActivityEntry's constraint prevents.
            models.CheckConstraint(
                condition=(
                    models.Q(is_school_wide=True, classroom__isnull=True)
                    | models.Q(is_school_wide=False, classroom__isnull=False)
                ),
                name="announcement_school_xor_classroom",
            )
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def audience(self) -> str:
        return "Whole school" if self.is_school_wide else str(self.classroom)

    def has_expired(self, *, on=None) -> bool:
        if self.expires_on is None:
            return False
        return self.expires_on < (on or timezone.localdate())


class AnnouncementRead(models.Model):
    """This guardian read this notice, at this moment.

    Not branch-scoped, and that is deliberate rather than an omission: the row holds
    no school data of its own, only a pair of foreign keys whose *targets* are both
    scoped already. `StudentGuardian` in apps/people is the same shape for the same
    reason. Phase 8's registry walk should find this and leave it alone.

    `guardian` is a `User` rather than a `people.Guardian` because the receipt records
    an account signing in and looking at something. A guardian with no portal account
    cannot read a notice, so there is nothing to record for them.
    """

    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="reads")
    guardian = models.ForeignKey(User, on_delete=models.CASCADE, related_name="announcement_reads")
    read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["announcement", "guardian"], name="announcement_read_once"
            )
        ]
        indexes = [models.Index(fields=["guardian"], name="announce_read_guardian_idx")]

    def __str__(self) -> str:
        return f"{self.guardian} read {self.announcement}"
