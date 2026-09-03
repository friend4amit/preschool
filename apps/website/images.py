"""How a seeded image's width variants are named.

Shared by `seed_media`, which writes the files, and the `srcset` template filter,
which points at them. They have to agree exactly — a filter that names a width the
seeder never wrote produces a 404 inside a `srcset`, which browsers fail silently
and nobody notices until an image stops appearing on one screen size.

Naming: `marketing/<folder>/<stem>-<width>.webp`, and the model field stores the
largest. Everything else is derivable from that name, which is why there is no table
of variants to keep in sync.
"""

import re

# The width suffix the seeder appends. Anchored, so it cannot match a stem that
# happens to end in digits.
WIDTH_SUFFIX = re.compile(r"-(\d+)\.webp$")


def variant_widths(available: int, targets) -> list[int]:
    """The widths that actually exist, largest first.

    Never upscales: a target wider than the source is clamped down to it, which is
    why a 350px original asked for 640 and 400 yields a single 350px file rather
    than two blurry enlargements.
    """
    return sorted({min(int(t), int(available)) for t in targets}, reverse=True)


def stored_width(name: str) -> int | None:
    """The width baked into a seeded filename, or None for an admin upload.

    An admin uploading through /admin gets one file at whatever size they chose, and
    no `srcset` — correct, and the reason this returns None rather than guessing.
    """
    match = WIDTH_SUFFIX.search(name or "")
    return int(match.group(1)) if match else None
