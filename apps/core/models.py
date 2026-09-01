"""Core domain models: the organisation, its branches, who belongs to them, and consent.

Two rules from docs/plan.md are load-bearing here and cost nothing today:

1. `User` is custom from migration 0001. Swapping AUTH_USER_MODEL later is one of
   the few genuinely painful things to undo in Django.
2. Every model carrying school data has a `branch` FK, even though exactly one
   Branch row exists at launch. Retrofitting a tenant key across forty tables once
   real data exists is a rewrite; adding the column now is one line.

Note what is deliberately absent: any automatic scoping. The default manager stays
unscoped, and `for_user()` lives in selectors.py. Middleware or thread-local scoping
silently breaks migrations, loaddata, shell sessions, and background tasks — none of
which have a request.
"""

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """Phone-number manager. No email is required — many parents don't have one."""

    use_in_migrations = True

    def _create(self, phone: str, password: str | None, **extra):
        if not phone:
            raise ValueError("A phone number is required.")
        user = self.model(phone=phone, **extra)
        # No usable password by default: accounts are created by an admin, who then
        # hands over a one-time set-password link. There is no signup page.
        user.set_password(password) if password else user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, phone: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(phone, password, **extra)

    def create_superuser(self, phone: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if not extra["is_staff"] or not extra["is_superuser"]:
            raise ValueError("A superuser must have is_staff and is_superuser set.")
        return self._create(phone, password, **extra)


class User(AbstractUser):
    """Identity for staff and parents alike. Phone is the username: every parent has
    one and no parent reliably has email."""

    username = None  # replaced by `phone`
    phone = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True)
    full_name = models.CharField(max_length=200, blank=True)

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        ordering = ["full_name", "phone"]

    def __str__(self) -> str:
        return self.full_name or self.phone


class Organization(models.Model):
    """The school as a business. One row, for a long time."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class Branch(models.Model):
    """A physical location. Exactly one at launch; the switcher stays hidden until
    there are two. Everything with school data points at one of these."""

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="branches"
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField()
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    # Place of supply is per branch, and branch two may register separately.
    gstin = models.CharField(max_length=15, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "branches"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "slug"], name="uniq_branch_slug_per_org"
            )
        ]

    def __str__(self) -> str:
        return self.name


class BranchScopedModel(models.Model):
    """Abstract base for anything holding school data.

    Carries the FK and nothing else — no scoped manager. Scoping is applied
    explicitly in selectors so it is greppable in review and cannot silently
    apply where there is no request.
    """

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="+")

    class Meta:
        abstract = True


class Role(models.TextChoices):
    SUPERADMIN = "superadmin", "Superadmin"
    BRANCH_ADMIN = "branch_admin", "Branch admin"
    TEACHER = "teacher", "Teacher"
    PARENT = "parent", "Parent"
    ACCOUNTANT = "accountant", "Accountant"


class BranchMembership(models.Model):
    """User x branch x role.

    A role column on User alone cannot express a teacher who moves branches, or an
    owner who sees all of them. This can.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "branch", "role"], name="uniq_membership_per_role"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.get_role_display()} at {self.branch}"


class ConsentPurpose(models.TextChoices):
    """Four purposes, and the distinction between the first two is the one that matters.

    Most classroom photos contain several children, so a single "photos" flag would
    show child B's face to child A's family on the strength of A's consent — which is
    backwards. PHOTOS_SHARED_WITH_CLASS is what makes the rule enforceable: a photo is
    publishable only if *every* tagged child carries it.
    """

    PHOTOS_IN_APP = "photos_in_app", "Show photos of our child, to us"
    PHOTOS_SHARED_WITH_CLASS = (
        "photos_shared_with_class",
        "Our child may appear in photos shown to other enrolled families",
    )
    PHOTOS_IN_MARKETING = "photos_in_marketing", "Our child may appear in public marketing"
    COMMS = "comms", "We may be contacted about school matters"


class Consent(BranchScopedModel):
    """Per-guardian, per-purpose, versioned, revocable, and off by default.

    Under the DPDP Act consent is bound to the purpose it was given for, so this is
    a record of a specific answer to a specific question at a specific time — not a
    boolean on a profile.
    """

    guardian = models.ForeignKey(User, on_delete=models.CASCADE, related_name="consents")
    purpose = models.CharField(max_length=40, choices=ConsentPurpose.choices)
    granted = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    granted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    recorded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="consents_recorded", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["guardian", "purpose", "branch"], name="uniq_consent_per_purpose"
            )
        ]

    def __str__(self) -> str:
        state = "granted" if self.is_active else "not granted"
        return f"{self.guardian} — {self.get_purpose_display()} ({state})"

    @property
    def is_active(self) -> bool:
        return self.granted and self.revoked_at is None

    def revoke(self) -> None:
        self.granted = False
        self.revoked_at = timezone.now()


class AcademicYear(BranchScopedModel):
    """A school year — "2026-27". Phase 2.

    Lives in core rather than people because it belongs to the organisation: it
    exists before any child is enrolled, and it still exists when none are. The
    same reasoning puts Classroom here and Enrollment in apps/people.
    """

    name = models.CharField(max_length=20)
    start_date = models.DateField()
    end_date = models.DateField()
    # Explicit rather than derived from today's date: a school is mid-admissions
    # for next year while this year is still running, and "current" is a decision
    # the office makes, not a calendar fact.
    is_current = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "name"], name="uniq_year_name_per_branch"),
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F("start_date")),
                name="year_ends_after_it_starts",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Classroom(BranchScopedModel):
    """A room and the group in it — "Nursery A".

    Deliberately not tied to an academic year: the room outlives the cohort. What
    changes yearly is who is enrolled in it, which is what Enrollment records.
    """

    name = models.CharField(max_length=100)
    capacity = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"], name="uniq_classroom_name_per_branch"
            )
        ]

    def __str__(self) -> str:
        return self.name
