"""Public website content.

Prose lives in templates — there is no CMS here and that is deliberate (docs/plan.md).
What lives in the database is only what repeats and what the school will want to edit
without a deploy: programs, educators, testimonials, and the settings in the footer.

`Enquiry` is the exception and the important one. It is the join between the two halves
of the product: the contact form on a marketing page becomes an admission in phase 2,
which is the thing a brochure site can never do.
"""

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.text import slugify

from apps.core.models import BranchScopedModel
from integrations.storage_r2 import public_media


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

    logo = models.ImageField(
        upload_to="marketing/site/",
        blank=True,
        storage=public_media,
        max_length=200,
        help_text="Optional. Without one the header shows the Aaroham wordmark, "
        "which is no bad thing.",
    )
    hero_image = models.ImageField(
        upload_to="marketing/site/",
        blank=True,
        storage=public_media,
        max_length=200,
        help_text="The photograph behind the home page headline. Landscape, at "
        "least 1400px wide. Without one the hero falls back to colour and type.",
    )
    hero_image_alt = models.CharField(
        max_length=200,
        blank=True,
        help_text="What the photograph shows, for a screen reader. Leave blank if "
        "it is purely decorative.",
    )
    # A separate field, not `phone`. `phone` is a display string — "080 1234 5678"
    # is the kind of thing that goes in it — and wa.me needs digits with a country
    # code and nothing else. Stripping punctuation out of `phone` would give
    # 08012345678, which wa.me rejects for having no country code.
    whatsapp_number = models.CharField(
        max_length=15,
        blank=True,
        validators=[
            RegexValidator(
                r"^\d{10,15}$",
                "Digits only, including the country code — e.g. 919876543210.",
            )
        ],
        help_text="Country code + number, digits only. Shows a WhatsApp button on "
        "every public page. Leave blank to hide it.",
    )

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
    image = models.ImageField(
        upload_to="marketing/programs/",
        blank=True,
        storage=public_media,
        max_length=200,
        help_text="Landscape, roughly 4:3. A programme without one renders as a "
        "text card rather than an empty box.",
    )
    image_alt = models.CharField(max_length=200, blank=True)
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


class ImagePlacement(models.TextChoices):
    """Where on the site an image is meant to sit.

    One model with a placement beats a named ImageField per page. `about_image`,
    `approach_image`, `inclusion_image` is three fields today and six next quarter,
    each needing a migration; this needs a row. It is also the shape docs/plan.md
    asks for — repeating content lives in tiny models editable in /admin.
    """

    GALLERY = "gallery", "Gallery — the strip on the home page"
    ABOUT = "about", "About us"
    APPROACH_PLAY = "approach_play", "Our approach — learning through play"
    APPROACH_HANDS = "approach_hands", "Our approach — hands-on and independent"
    APPROACH_VALUES = "approach_values", "Our approach — Indian values and culture"
    INCLUSION = "inclusion", "Thoughtful education"
    TEAM = "team", "Our team — the band above the educators"


class GalleryImage(BranchScopedModel):
    """A photograph of the school, placed by role rather than by page template.

    Deliberately no relation to a Student. These are marketing images — rooms,
    materials, hands at work — and docs/plan.md is explicit that a photograph of an
    identifiable child needs `photos_in_marketing` consent from that child's
    guardian, which is a different flow entirely. Nothing here goes near it.
    """

    image = models.ImageField(upload_to="marketing/gallery/", storage=public_media, max_length=200)
    alt_text = models.CharField(
        max_length=200,
        blank=True,
        help_text="What the photograph shows. Leave blank only if it is purely "
        "decorative — an empty alt is correct markup for that, a missing one is not.",
    )
    caption = models.CharField(max_length=200, blank=True)
    placement = models.CharField(
        max_length=20, choices=ImagePlacement.choices, default=ImagePlacement.GALLERY
    )
    # Which original this row came from, when it was seeded rather than uploaded.
    # It is what makes `seed_media` idempotent, and it is provenance for images
    # whose licensing may later need tracing.
    source_key = models.CharField(max_length=200, blank=True, editable=False)
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PublishedQuerySet.as_manager()

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            # Partial, so admin-uploaded rows can leave source_key blank without
            # colliding with each other.
            models.UniqueConstraint(
                fields=["branch", "source_key"],
                condition=~models.Q(source_key=""),
                name="uniq_gallery_source_per_branch",
            )
        ]

    def __str__(self) -> str:
        return self.caption or self.alt_text or f"Image {self.pk}"


class Stat(BranchScopedModel):
    """One number in the band on the home page — "1:8", "Adult to child"."""

    # A string, not an integer. The numbers a preschool actually wants to show are
    # "1:8" for the adult-to-child ratio and "18 months" for the youngest admitted,
    # and an IntegerField forces both of those out of the band.
    value = models.CharField(max_length=20)
    label = models.CharField(max_length=80)
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)

    objects = PublishedQuerySet.as_manager()

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.value} {self.label}"
