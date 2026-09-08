"""Generate the PWA icons from the theme tokens. Run once; the output is committed.

A script rather than a design file because the mark is geometry, not artwork: a
rounded square in `--color-leaf-deep` with a sprout in `--color-spring`. Regenerating
it after a palette change is `uv run python scripts/make_icons.py` rather than a round
trip through a drawing tool nobody has installed.

Two sizes, because that is what a manifest needs, plus a maskable variant. Maskable
matters more than it sounds: Android crops an icon to whatever shape the launcher
uses, so the artwork needs a safe zone or the sprout loses its leaves on a circular
launcher. Same drawing, smaller, on a filled square.

    uv run python scripts/make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "static" / "img"

LEAF_DEEP = (58, 84, 39)  # --color-leaf-deep
SPRING = (170, 214, 136)  # --color-spring
CREAM = (251, 247, 241)  # --color-surface

# Draw once, large, and downsample. Anti-aliasing for free, and the curves survive it.
CANVAS = 1024


def _sprout(*, inset: float) -> Image.Image:
    """The mark on a transparent ground: a stem and two leaves, centred.

    Always drawn at CANVAS and downsampled by the caller — that is where the
    anti-aliasing comes from, so this takes no size of its own.

    `inset` is the fraction of the canvas left empty around the drawing. The maskable
    icon needs a large one — Android's safe zone is the middle 80% of the circle, and
    anything outside it is the launcher's to crop.
    """
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = CANVAS * inset
    span = CANVAS - 2 * pad
    mid = CANVAS / 2
    stem_w = span * 0.055

    # Stem: from the base up to just past the middle.
    draw.rounded_rectangle(
        [mid - stem_w / 2, pad + span * 0.30, mid + stem_w / 2, pad + span * 0.96],
        radius=stem_w / 2,
        fill=SPRING,
    )

    # Two leaves, one either side, drawn as an ellipse rotated about the point where
    # it meets the stem. Rotating a whole layer rather than computing a polygon keeps
    # the edge smooth; mirroring it gives the second leaf for free, so the shape is
    # defined once and cannot drift out of symmetry.
    pivot_y = pad + span * 0.34
    pivot = (mid, pivot_y)
    leaf = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    ImageDraw.Draw(leaf).ellipse(
        [mid - span * 0.31, pivot_y - span * 0.085, mid + span * 0.02, pivot_y + span * 0.085],
        fill=SPRING,
    )
    img.alpha_composite(leaf.rotate(-48, center=pivot, resample=Image.BICUBIC))
    img.alpha_composite(
        leaf.transpose(Image.FLIP_LEFT_RIGHT).rotate(48, center=pivot, resample=Image.BICUBIC)
    )
    return img


def _icon(size: int, *, maskable: bool) -> Image.Image:
    ground = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(ground)
    if maskable:
        # A full bleed square. The launcher decides the shape; we must not.
        draw.rectangle([0, 0, CANVAS, CANVAS], fill=LEAF_DEEP)
        ground.alpha_composite(_sprout(inset=0.24))
    else:
        draw.rounded_rectangle([0, 0, CANVAS, CANVAS], radius=CANVAS * 0.22, fill=LEAF_DEEP)
        ground.alpha_composite(_sprout(inset=0.14))
    return ground.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for size in (192, 512):
        path = OUT / f"icon-{size}.png"
        _icon(size, maskable=False).save(path)
        written.append(path)
    for size in (192, 512):
        path = OUT / f"icon-maskable-{size}.png"
        _icon(size, maskable=True).save(path)
        written.append(path)

    # The browser tab. A 32px PNG rather than an .ico — every browser this site
    # supports reads one, and it is the same drawing at a size where the rounded
    # corners still read.
    favicon = OUT / "favicon.png"
    _icon(32, maskable=False).save(favicon)
    written.append(favicon)

    # Apple ignores the manifest and wants its own tag, on an opaque ground: iOS
    # composites a transparent touch icon onto black.
    apple = Image.new("RGB", (180, 180), CREAM)
    mark = _icon(180, maskable=False)
    apple.paste(mark, (0, 0), mark)
    path = OUT / "apple-touch-icon.png"
    apple.save(path)
    written.append(path)

    for path in written:
        print(f"{path.relative_to(OUT.parents[1])}  {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
