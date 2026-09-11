"""Regenerate the Qwikserve app icons and the login / splash marks.

The master is ``android/brand/qwikserve-logo.png``: a winged Q roundel with the
QWIKSERVE wordmark under it, red on white. Run from the repo root::

    python -m tools.make_icons

Three crops come out of it, because one image cannot do all three jobs.

**The launcher icon is the winged mark, knocked out white on a red tile.**
The first attempt at this used the roundel alone — the disc is already a
circle, which is what an adaptive mask wants, and the wings are only a few
pixels tall at 48 dp. It was rejected on sight, correctly: the wings are what
makes the mark *this* company's rather than a generic letter in a circle, and
without them the icon is a Q in a ring.

What makes the wide mark work at icon size is the inversion. A red tile fills
the whole icon, so the shape of the icon is the brand's colour rather than a
white square with a small picture on it, and white-on-red is the highest
contrast available — the feathers survive down to 48 dp where thin red strokes
on white turn to mush. The mark is drawn at 0.70 of the 108 dp canvas: a
launcher shows only the central 72 dp, so that is a hair wider than the
visible circle and the outermost feather tips graze its edge. Sizes either
side of it were rendered masked at 48, 72 and 108 and looked at before this
one was chosen; smaller left the Q too small to read, larger cut the wings
back to stumps.

The other two:

  * the LOGIN mark is the winged Q the right way round (red on nothing), with
    no wordmark: the screen sets "Qwikserve" in Archivo underneath, so baking
    a second wordmark in would print the name twice.
  * the SPLASH is the same mark, centred in a square.

White is knocked out to transparency ONLY where it is connected to the border,
so the Q's counter — an enclosed island of white — survives as its own shape
rather than becoming a hole showing the wallpaper.
"""

import pathlib

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = pathlib.Path(__file__).resolve().parent.parent
SRC = HERE / "android/brand/qwikserve-logo.png"
RES = HERE / "android/app/src/main/res"

# Measured off the 3000 px original, not guessed. Kept as fractions so a
# differently sized master still works.
_K = 1 / 3000
ROUNDEL_F = (1497 * _K, 1486 * _K, 264 * _K)  # centre x, centre y, radius
MARK_BOX_F = (459 * _K, 931 * _K, 2537 * _K, 1751 * _K)  # wordmark excluded

# The mark's own red, the median of its red pixels. Also written into
# values/colors.xml as ic_launcher_background — keep the two in step.
RED = (194, 33, 33, 255)
WHITE = (255, 255, 255, 255)

# 108 dp adaptive canvas, of which a launcher shows the central 72.
SAFE = 72 / 108
MARK_WIDTH = 0.70  # of the 108 dp canvas — see the module docstring

DENSITIES = (("mdpi", 1), ("hdpi", 1.5), ("xhdpi", 2), ("xxhdpi", 3), ("xxxhdpi", 4))


def load_transparent() -> Image.Image:
    im = Image.open(SRC).convert("RGBA")
    a = np.array(im)
    rgb = a[..., :3].astype(int)
    white = rgb.sum(axis=2) > 720
    # Only white that reaches the border becomes transparent; the white inside
    # the Q is its own island and must survive.
    lab, _ = ndimage.label(white)
    border = set(lab[0, :]) | set(lab[-1, :]) | set(lab[:, 0]) | set(lab[:, -1])
    border.discard(0)
    a[..., 3] = np.where(np.isin(lab, list(border)), 0, 255)
    return Image.fromarray(a, "RGBA")


def winged_mark(master: Image.Image) -> Image.Image:
    n = master.size[0]
    return master.crop(tuple(round(v * n) for v in MARK_BOX_F))


def knockout(mark: Image.Image, color=WHITE) -> Image.Image:
    """Recolour the mark and punch the Q through to transparency.

    Every inked pixel becomes ``color``; the white that was the Q glyph becomes
    a hole, so the tile's red shows through it. That is what turns the mark
    inside out — white wings and a white disc with a red Q — and it is also
    what makes the same image usable as the ``monochrome`` layer, where an
    opaque fill would theme as a featureless blob.
    """
    a = np.array(mark).copy()
    inked = a[..., 3] > 0
    glyph = (a[..., :3].astype(int).sum(axis=2) > 720) & inked
    a[inked, 0], a[inked, 1], a[inked, 2] = color[:3]
    a[glyph, 3] = 0
    return Image.fromarray(a, "RGBA")


def ink_centre(mark: Image.Image) -> tuple[float, float]:
    """Where the mark's weight actually is, as a fraction of its box.

    The wings sweep upward, so the bounding box and the ink are not centred on
    the same point and centring on the box leaves the Q sitting low with a band
    of empty red above it.
    """
    ys, xs = np.nonzero(np.array(mark)[..., 3] > 0)
    return xs.mean() / mark.size[0], ys.mean() / mark.size[1]


def foreground(mark: Image.Image, canvas: int, *, bg=None, color=WHITE) -> Image.Image:
    """The mark on a ``canvas``-square adaptive foreground."""
    cx, cy = ink_centre(mark)
    m = knockout(mark, color)
    w = round(canvas * MARK_WIDTH)
    h = round(m.size[1] * w / m.size[0])
    m = m.resize((w, h), Image.LANCZOS)
    out = Image.new("RGBA", (canvas, canvas), bg or (0, 0, 0, 0))
    out.paste(m, (round(canvas / 2 - cx * w), round(canvas / 2 - cy * h)), m)
    return out


def as_launcher_sees_it(fg: Image.Image, px: int, *, circle: bool) -> Image.Image:
    """The legacy icon: what the adaptive pair actually renders as.

    Derived from the same foreground rather than composed separately, so the
    old square icon and the adaptive one cannot drift apart. The central 72 dp
    of the 108 is the visible window; a round launcher then masks it.
    """
    keep = round(fg.size[0] * SAFE)
    off = (fg.size[0] - keep) // 2
    vis = fg.crop((off, off, off + keep, off + keep)).resize((px, px), Image.LANCZOS)
    tile = Image.new("RGBA", (px, px), RED)
    tile.paste(vis, (0, 0), vis)
    if not circle:
        return tile
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, px - 1, px - 1), fill=255)
    out = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    out.paste(tile, (0, 0), mask)
    return out


def main() -> None:
    master = load_transparent()
    mark = winged_mark(master)

    # ── launcher ────────────────────────────────────────────────────────────
    for name, scale in DENSITIES:
        # Adaptive foreground: white mark on transparent. The red comes from
        # the background layer (@color/ic_launcher_background), which is what
        # lets a launcher move the two against each other.
        fg = foreground(mark, round(108 * scale))
        fg.save(f"{RES}/mipmap-{name}/ic_launcher_foreground.png")
        # Legacy icons for launchers that predate adaptive ones: the same
        # composition, flattened onto the red.
        px = round(48 * scale)
        as_launcher_sees_it(fg, px, circle=False).convert("RGB").save(
            f"{RES}/mipmap-{name}/ic_launcher.png"
        )
        as_launcher_sees_it(fg, px, circle=True).save(f"{RES}/mipmap-{name}/ic_launcher_round.png")

    # ── login + splash ──────────────────────────────────────────────────────
    # The right way round here: red mark on nothing, over the light background
    # both screens already paint. Generated at 4× the size the screens draw it
    # at, which is the whole point of this pass — the old pair was soft.
    w, h = mark.size
    logo_w = 1440
    mark.resize((logo_w, round(h * logo_w / w)), Image.LANCZOS).save(
        f"{RES}/drawable-xxxhdpi/qwik_logo.png"
    )
    side = 1280
    splash = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sw = round(side * 0.875)
    sm = mark.resize((sw, round(h * sw / w)), Image.LANCZOS)
    splash.paste(sm, ((side - sw) // 2, (side - sm.size[1]) // 2), sm)
    splash.save(f"{RES}/drawable-xxxhdpi/splash_logo.png")
    print("written")


if __name__ == "__main__":
    main()
