"""Template helpers for responsive images.

`srcset` is the one that earns its place. A 1430px hero is 50 KB and a 640px one is
18 KB, and on the mobile connections these families actually have that is the
difference between a photograph that appears and one that does not. It is also
strictly more useful than a <picture> element here: WebP has been supported
everywhere that matters since 2020, so a JPEG fallback would double the storage and
the seed command to serve almost nobody, while srcset saves real bytes on every
phone.
"""

from django import template

from apps.website.images import stored_width, variant_widths

register = template.Library()


@register.filter
def srcset(image, widths: str) -> str:
    """`{{ program.image|srcset:"800,400" }}` -> "…-800.webp 800w, …-400.webp 400w".

    Returns an empty string for an image the seeder did not write — an /admin upload
    is a single file, and the templates guard on this being empty rather than
    emitting `srcset=""`, which is invalid and which one of the page tests forbids.
    """
    if not image:
        return ""
    available = stored_width(image.name)
    if available is None:
        return ""

    url = image.url
    base = url[: url.rfind(f"-{available}.webp")]
    targets = [int(w) for w in widths.split(",") if w.strip().isdigit()]
    return ", ".join(f"{base}-{w}.webp {w}w" for w in variant_widths(available, targets))
