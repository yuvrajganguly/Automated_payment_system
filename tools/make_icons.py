"""Regenerate the Qwikserve app icons and login/splash marks from the master PNG.

The master is android/brand/qwikserve-logo.png: winged Q, then the QWIKSERVE
wordmark, red on white. Run from the repo root::

    python -m tools.make_icons

Three different crops come out of it, because one image cannot do all three
jobs:

  * the LAUNCHER icon is the roundel alone. At 48dp the wings are a red smear
    and an adaptive icon's mask would cut their tips off regardless — the
    roundel is already a circle, which is exactly what the mask wants.
  * the LOGIN mark is the winged Q without the wordmark: the screen sets
    "Qwikserve" in Archivo underneath, so baking a second wordmark in would
    print the name twice.
  * the SPLASH is the same winged mark, centred in a square.

White is knocked out to transparency ONLY where it is connected to the border.
The Q's counter is enclosed white and stays opaque, so the mark keeps a white
Q rather than showing whatever sits behind it.
"""

import pathlib

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = pathlib.Path(__file__).resolve().parent.parent
SRC = HERE / "android/brand/qwikserve-logo.png"
RES = HERE / "android/app/src/main/res"

# Measured off the 3000px original, not guessed: the roundel is a true circle.
# Kept as fractions so a differently sized master still works.
_K = 1 / 3000
ROUNDEL_F = (1497 * _K, 1486 * _K, 264 * _K)  # centre x, centre y, radius
MARK_BOX_F = (459 * _K, 931 * _K, 2537 * _K, 1751 * _K)  # wordmark excluded


def load_transparent() -> Image.Image:
    im = Image.open(SRC).convert("RGBA")
    a = np.array(im)
    rgb = a[..., :3].astype(int)
    white = rgb.sum(axis=2) > 720
    # Only the white that reaches the border becomes transparent; the white
    # inside the Q is its own island and must survive.
    lab, n = ndimage.label(white)
    border = set(lab[0, :]) | set(lab[-1, :]) | set(lab[:, 0]) | set(lab[:, -1])
    border.discard(0)
    outside = np.isin(lab, list(border))
    a[..., 3] = np.where(outside, 0, 255)
    return Image.fromarray(a, "RGBA")


def roundel(img: Image.Image, knockout: bool) -> Image.Image:
    """The disc, cropped square. ``knockout`` makes the Q transparent instead
    of white — wanted for the adaptive foreground, because that same image is
    also the monochrome/themed icon, where an opaque white Q would fill in and
    leave a featureless blob."""
    n = img.size[0]
    cx, cy, r = (round(v * n) for v in ROUNDEL_F)
    box = (cx - r, cy - r, cx + r, cy + r)
    out = img.crop(box).copy()
    a = np.array(out)
    # Anything outside the disc goes, so the wings that overlap it cannot
    # leave stray red in the corners.
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    outside_disc = ((xx - w / 2) ** 2 + (yy - h / 2) ** 2) > (r - 1) ** 2
    a[outside_disc, 3] = 0
    if knockout:
        rgb = a[..., :3].astype(int)
        a[(rgb.sum(axis=2) > 720) & (a[..., 3] > 0), 3] = 0
    return Image.fromarray(a, "RGBA")


def fit(img: Image.Image, canvas: int, frac: float, bg=None) -> Image.Image:
    """Scale ``img`` to ``frac`` of a square canvas and centre it."""
    side = max(1, round(canvas * frac))
    scaled = img.resize((side, side), Image.LANCZOS)
    out = Image.new("RGBA", (canvas, canvas), bg or (0, 0, 0, 0))
    out.paste(scaled, ((canvas - side) // 2, (canvas - side) // 2), scaled)
    return out


def main() -> None:
    master = load_transparent()

    # ── launcher ────────────────────────────────────────────────────────────
    # Adaptive foreground: 108dp canvas, only the inner 72dp is guaranteed
    # visible. 0.66 keeps the whole disc inside that safe circle on every
    # mask shape a launcher might apply.
    fg = roundel(master, knockout=True)
    legacy = roundel(master, knockout=False)
    for name, px in (
        ("mdpi", 108),
        ("hdpi", 162),
        ("xhdpi", 216),
        ("xxhdpi", 324),
        ("xxxhdpi", 432),
    ):
        fit(fg, px, 0.66).save(f"{RES}/mipmap-{name}/ic_launcher_foreground.png")
    # Legacy icons are unmasked squares on older launchers, so they carry the
    # white themselves and can sit a little larger.
    for name, px in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        square = fit(legacy, px, 0.82, bg=(255, 255, 255, 255)).convert("RGB")
        square.save(f"{RES}/mipmap-{name}/ic_launcher.png")
        # Round variant: same art, the launcher applies the circle.
        square.save(f"{RES}/mipmap-{name}/ic_launcher_round.png")

    # ── login + splash ──────────────────────────────────────────────────────
    n = master.size[0]
    mark = master.crop(tuple(round(v * n) for v in MARK_BOX_F))
    w, h = mark.size
    logo_w = 720
    mark.resize((logo_w, round(h * logo_w / w)), Image.LANCZOS).save(
        f"{RES}/drawable-xxxhdpi/qwik_logo.png"
    )
    splash = Image.new("RGBA", (640, 640), (0, 0, 0, 0))
    sw = 560
    sm = mark.resize((sw, round(h * sw / w)), Image.LANCZOS)
    splash.paste(sm, ((640 - sw) // 2, (640 - sm.size[1]) // 2), sm)
    splash.save(f"{RES}/drawable-xxxhdpi/splash_logo.png")
    print("written")


if __name__ == "__main__":
    main()
