"""Convert the Udgam photographs and attach them to the marketing models.

A convenience, never a dependency. Every image this writes is an ordinary upload the
school can replace in /admin, and every template guards on the image being absent —
so the site works whether or not this has ever been run.

Three things it does that matter:

1. **Converts.** The originals are 1.4-4.2 MB RGBA PNGs. docs/plan.md requires the
   site to work "on a real, cheap Android phone over mobile data", and a 4 MB hero
   fails that outright. These come out as WebP at a few widths for `srcset`.
2. **Never upscales.** The library caps at 1430-1747px. A 1920w variant would be a
   blurry enlargement that costs bytes and buys nothing, so every target width is
   clamped to the source.
3. **Refuses the blocked files.** One of them is a named person who must not appear
   anywhere on this site; the others carry watermarks or burnt-in text. The check is
   both an exact-stem list and a regex, because a regex catches a renamed copy and a
   generated thumbnail that a list would miss.
"""

import re
from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image, ImageOps

from apps.core.selectors import current_branch_fallback
from apps.website.models import GalleryImage, ImagePlacement, Program, SiteSettings

# --- what must never be published -----------------------------------------------------

# Belt: catches a rename, a generated thumbnail, any future file naming her.
BLOCKED = re.compile(r"surashree|shome", re.IGNORECASE)

# Braces: the specific files, and why each one is out.
BLOCKED_STEMS = {
    "surashree-shome": "a named person who must not appear on this site (docs/plan.md)",
    "group-70": "visible dreamstime watermark",
    "group-71": "visible dreamstime watermark",
    "group-72": "visible dreamstime watermark",
    "udgam": "phone numbers and 'Coming Soon' baked into the image",
    "group-42": "'BACK TO SCHOOL' baked into the image",
    "early-child-care-and-education": "course-title text baked into the image",
}


# A WordPress generated size: "-1024x768". Used to decide whether a longer name is
# a thumbnail of a blocked original or an unrelated file that merely shares a prefix
# — "udgam.png" is blocked, "udgam-family-kids.png" is a different photograph.
THUMBNAIL_SUFFIX = re.compile(r"^-\d+x\d+$")


def is_blocked(name: str) -> str | None:
    """The reason this file may not ship, or None. Takes a filename or a path."""
    stem = Path(name).stem.lower()
    if BLOCKED.search(name):
        return BLOCKED_STEMS["surashree-shome"]
    for blocked, reason in BLOCKED_STEMS.items():
        if stem == blocked:
            return reason
        if stem.startswith(blocked) and THUMBNAIL_SUFFIX.match(stem[len(blocked) :]):
            return reason
    return None


# --- what goes where ------------------------------------------------------------------

# (source, widths). Widths are targets; each is clamped to the source width.
HERO = ("2026/02/kids-plying-banner.png", (1440, 960, 640))
TEAM_BAND = ("2026/02/aboutus-hero-banner.png", (1440, 960))

PLACED = {
    # The warmest image in the library — a teacher mid-explanation in a marigold
    # saree, children shot from behind. No identifiable face, so no consent
    # question, and the only file whose colour temperature matches the palette.
    ImagePlacement.ABOUT: ("2026/02/class-techer.png", (800, 480), "A teacher with her class"),
    # This page is about children who need the room adjusted around them, and this
    # is the one photograph in the library whose subject is exactly that.
    ImagePlacement.INCLUSION: (
        "2026/02/realistic-scene-with-young-children-with-autism-playing-2-1.png",
        (800, 480),
        "Two children working on a wooden puzzle together",
    ),
    ImagePlacement.APPROACH_PLAY: (
        "2026/02/g-img-01.png",
        (640, 400),
        "A toddler playing a wooden xylophone",
    ),
    ImagePlacement.APPROACH_HANDS: (
        "2026/02/cute-little-indian-asian-kids-playing-with-toys-blocks-having-fun-while-"
        "sitting-table-isolated-white-background-3-1.png",
        (640, 400),
        "Children building with blocks at a table",
    ),
    ImagePlacement.APPROACH_VALUES: (
        "2026/02/plyin-kids-father.png",
        (640, 400),
        "A father and son reading together at home",
    ),
    ImagePlacement.TEAM: (TEAM_BAND[0], TEAM_BAND[1], "A teacher and children at a craft table"),
}

GALLERY = [
    ("2026/02/udgam-family-kids.png", "Two children building with blocks"),
    ("2026/02/mission-boys.png", "Children pulling together on a rope"),
    ("2026/03/kid-box-img-1.webp.png", "A child in a paint-spattered smock"),
    ("2026/02/plying-guide.png", "An adult guiding a child through a puzzle"),
    ("2026/02/value-calture-kid.png", "A child with a paper windmill"),
]
GALLERY_WIDTHS = (800, 400)

# Programme slug -> source. A programme whose source is missing simply keeps no
# image and renders as a text card.
PROGRAM_IMAGES = {
    "playgroup": "2026/02/g-img-04.png",
    "nursery": (
        "2026/02/cute-little-indian-asian-kids-playing-with-toys-blocks-having-fun-while-"
        "sitting-table-isolated-white-background-3-1.png"
    ),
    "lkg": "2026/03/kid-box-img-1.webp.png",
    "ukg": "2026/02/mission-boys.png",
    "daycare-afterschool": "2026/02/udgam-family-kids.png",
}
PROGRAM_WIDTHS = (800, 400)

# Warm paper, not white. Every original here is RGBA, and flattening onto white
# would leave a bright halo wherever the cut-out edge meets the page background.
MATTE = "#fbf7f1"
QUALITY = 72


class Command(BaseCommand):
    help = "Convert the Udgam photographs into WebP and attach them to the site."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            required=True,
            help="Path to the WordPress uploads directory, e.g. "
            "C:/work/learn/udgam/wp-content/uploads",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report, write nothing.")
        parser.add_argument(
            "--force", action="store_true", help="Re-convert images that are already attached."
        )

    def handle(self, *args, **options):
        # Required with no default, like backup_database: guessing a path that
        # exists on one laptop and not on the VPS is how a command silently
        # half-works.
        source = Path(options["source"])
        if not source.is_dir():
            raise CommandError(f"--source is not a directory: {source}")

        branch = current_branch_fallback()
        if branch is None:
            raise CommandError("No active Branch. Run `manage.py seed` first.")

        self.source, self.dry_run, self.force = source, options["dry_run"], options["force"]
        self.counts = {"attached": 0, "unchanged": 0, "missing": 0, "blocked": 0}

        with transaction.atomic():
            self._hero(branch)
            self._placed(branch)
            self._gallery(branch)
            self._programs(branch)
            if self.dry_run:
                transaction.set_rollback(True)

        summary = "  ".join(f"{k}={v}" for k, v in self.counts.items())
        style = self.style.WARNING if self.dry_run else self.style.SUCCESS
        self.stdout.write(style(f"\n{'(dry run) ' if self.dry_run else ''}{summary}"))
        if self.counts["missing"]:
            self.stdout.write(
                self.style.WARNING(
                    "Some sources were missing. That is not fatal — those slots stay "
                    "empty and the pages render without them."
                )
            )

    # --- the slots --------------------------------------------------------------------

    def _hero(self, branch):
        settings_row, _ = SiteSettings.objects.get_or_create(branch=branch)
        name = self._convert(HERO[0], "hero", HERO[1])
        attached = name and self._attach(settings_row, "hero_image", name)
        if attached and not settings_row.hero_image_alt:
            settings_row.hero_image_alt = "Children playing with building blocks"
            settings_row.save(update_fields=["hero_image_alt"])

    def _placed(self, branch):
        for placement, (rel, widths, alt) in PLACED.items():
            folder = f"gallery/{placement}"
            name = self._convert(rel, folder, widths)
            if not name:
                continue
            row, created = GalleryImage.objects.get_or_create(
                branch=branch,
                source_key=rel,
                defaults={"placement": placement, "alt_text": alt, "image": name},
            )
            if not created:
                row.placement, row.alt_text = placement, alt
                row.save(update_fields=["placement", "alt_text"])
                self._attach(row, "image", name)

    def _gallery(self, branch):
        for order, (rel, alt) in enumerate(GALLERY):
            name = self._convert(rel, "gallery/strip", GALLERY_WIDTHS)
            if not name:
                continue
            row, created = GalleryImage.objects.get_or_create(
                branch=branch,
                source_key=rel,
                defaults={
                    "placement": ImagePlacement.GALLERY,
                    "alt_text": alt,
                    "order": order,
                    "image": name,
                },
            )
            if not created:
                self._attach(row, "image", name)

    def _programs(self, branch):
        for slug, rel in PROGRAM_IMAGES.items():
            program = Program.objects.filter(branch=branch, slug=slug).first()
            if program is None:
                self.stdout.write(f"  no such programme, skipping: {slug}")
                continue
            name = self._convert(rel, "programs", PROGRAM_WIDTHS)
            if name and self._attach(program, "image", name) and not program.image_alt:
                program.image_alt = f"Children in the {program.name} room"
                program.save(update_fields=["image_alt"])

    # --- the work ---------------------------------------------------------------------

    def _convert(self, rel: str, folder: str, widths) -> str | None:
        """Write every width as WebP. Returns the storage name of the largest."""
        reason = is_blocked(rel)
        if reason:
            self.counts["blocked"] += 1
            self.stdout.write(self.style.ERROR(f"  blocked  {rel} — {reason}"))
            return None

        src = self.source / rel
        if not src.exists():
            self.counts["missing"] += 1
            self.stdout.write(self.style.WARNING(f"  missing  {rel}"))
            return None

        image = self._load(src)
        # Trimmed hard: these names go into a varchar column, and the WordPress
        # originals run to 90 characters before the width suffix is added.
        stem = Path(rel).stem.lower().replace(".", "-")[:32].strip("-")
        # Never upscale, and drop a width that is within a whisker of a bigger one.
        targets = sorted({min(w, image.width) for w in widths}, reverse=True)
        targets = [w for i, w in enumerate(targets) if i == 0 or targets[i - 1] / w >= 1.25]

        largest = None
        for width in targets:
            name = f"marketing/{folder}/{stem}-{width}.webp"
            if largest is None:
                largest = name
            self._write(image, width, name)
        return largest

    def _load(self, src: Path) -> Image.Image:
        image = ImageOps.exif_transpose(Image.open(src))
        if image.mode in ("RGBA", "LA", "P"):
            flat = Image.new("RGB", image.size, MATTE)
            image = image.convert("RGBA")
            flat.paste(image, mask=image.split()[-1])
            return flat
        return image.convert("RGB")

    def _write(self, image: Image.Image, width: int, name: str) -> None:
        from django.core.files.storage import storages

        storage = storages["public_media"]
        if storage.exists(name) and not self.force:
            return
        if self.dry_run:
            self.stdout.write(f"  would write  {name}  ({width}px)")
            return

        height = round(image.height * width / image.width)
        # centering biases the crop upward: faces sit high in these photographs, and
        # it also crops away the malformed hands the AI-generated ones have at the
        # bottom edge.
        resized = ImageOps.fit(
            image, (width, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.4)
        )
        buffer = BytesIO()
        resized.save(buffer, "WEBP", quality=QUALITY, method=6)
        if storage.exists(name):
            storage.delete(name)
        storage.save(name, ContentFile(buffer.getvalue()))
        self.stdout.write(f"  wrote  {name}  ({len(buffer.getvalue()) // 1024} KB)")

    def _attach(self, obj, field: str, name: str) -> bool:
        if getattr(obj, field).name == name and not self.force:
            self.counts["unchanged"] += 1
            return False
        if not self.dry_run:
            setattr(obj, field, name)
            obj.save(update_fields=[field])
        self.counts["attached"] += 1
        return True
