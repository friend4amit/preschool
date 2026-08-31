"""Public website content.

Prose lives in templates — there is no CMS here and that is deliberate (docs/plan.md).
What lives in the database is only what repeats and what the school will want to edit
without a deploy: programs, educators, testimonials, and the settings in the footer.

`Enquiry` is the exception and the important one. It is the join between the two halves
of the product: the contact form on a marketing page becomes an admission in phase 2,
which is the thing a brochure site can never do.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from apps.core.models import BranchScopedModel


class PublishedQuerySet(models.QuerySet):
    def published(self):
        return self.filter(is_published=True)


class SiteSettings(models.Model):
    """Footer and contact details. One row, edited in /admin.

    Per-branch rather than global: branch two has its own address and phone, and
    phase 8 turns that on by adding a second row rather than a migration.
    """

    branch = models.OneToOneField(
        "core.Branch", on_delete=models.CASCADE, related_name="site_settings"
    )
    tagline = models.CharField(max_length=200, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    map_embed_url = models.URLField(blank=True)
    facebook_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    # Used from phase 6 to build the UPI payment link. Harmless until then.
    upi_vpa = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name_plural = "site settings"

    def __str__(self) -> str:
        return f"Settings for {self.branch}"


class Program(BranchScopedModel):
    """An age band the school admits into: Playgroup, Nursery, LKG, UKG, Daycare."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(blank=True)
    age_from_months = models.PositiveIntegerField(help_text="Youngest age admitted, in months")
    age_to_months = models.PositiveIntegerField(help_text="Oldest age admitted, in months")
    summary = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)

    objects = PublishedQuerySet.as_manager()

    class Meta:
        ordering = ["order", "age_from_months"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "slug"], name="uniq_program_slug_per_branch")
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        if self.age_to_months <= self.age_from_months:
            raise ValidationError({"age_to_months": "Must be greater than the youngest age."})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def age_range_display(self) -> str:
        """Parents think in years and half-years, not months."""

        def fmt(months: int) -> str:
            years, rem = divmod(months, 12)
            if rem == 0:
                return str(years)
            if rem == 6:
                return f"{years}½"
            return f"{years}.{rem}"

        return f"{fmt(self.age_from_months)}–{fmt(self.age_to_months)} years"


class TeamMember(BranchScopedModel):
    name = models.CharField(max_length=200)
    role = models.CharField(max_length=200, blank=True)
    credentials = models.CharField(max_length=300, blank=True)
    bio = models.TextField(blank=True)
    photo = models.ImageField(upload_to="team/", blank=True)
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)

    objects = PublishedQuerySet.as_manager()

    class Meta:
        ordering = ["order", "name"]

    def __str__(self) -> str:
        return self.name


class Testimonial(BranchScopedModel):
    """Built now, shown when there are real ones.

    The reference site's only testimonial was Elementor's sample copy. Inventing
    parent quotes for a preschool would be a bad thing to ship, so the model exists
    and the section stays off until a real parent says a real thing.
    """

    quote = models.TextField()
    author_name = models.CharField(max_length=200)
    relationship = models.CharField(
        max_length=200, blank=True, help_text="e.g. 'Mother of Aarav, Nursery'"
    )
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=False)

    objects = PublishedQuerySet.as_manager()

    class Meta:
        ordering = ["order", "-id"]

    def __str__(self) -> str:
        return f"{self.author_name}: {self.quote[:50]}"


class EnquiryStatus(models.TextChoices):
    NEW = "new", "New"
    CONTACTED = "contacted", "Contacted"
    VISITED = "visited", "Visited"
    ADMITTED = "admitted", "Admitted"
    LOST = "lost", "Lost"


class Enquiry(BranchScopedModel):
    """A prospective family, captured from the public contact form.

    Carries `branch` like everything else: once there are two branches a parent is
    enquiring about one of them, and the list has to scope for the admin who works it.
    """

    guardian_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    child_name = models.CharField(max_length=200, blank=True)
    child_dob = models.DateField(null=True, blank=True)
    program = models.ForeignKey(
        Program, on_delete=models.SET_NULL, null=True, blank=True, related_name="enquiries"
    )
    message = models.TextField(blank=True)
    source = models.CharField(max_length=100, default="website")
    status = models.CharField(
        max_length=20, choices=EnquiryStatus.choices, default=EnquiryStatus.NEW
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "enquiries"

    def __str__(self) -> str:
        return f"{self.guardian_name} ({self.phone})"
