# Brand assets

`qwikserve-logo.png` is the master lockup — winged Q above the QWIKSERVE
wordmark, red on white, 1200×1200. Everything in `app/src/main/res` that shows
the mark is generated from it by `tools/make_icons.py`; edit the master and
re-run rather than touching the PNGs by hand.

Three crops come out of it, because one image cannot do all three jobs:

| Output | What it is | Why not the whole lockup |
|---|---|---|
| `mipmap-*/ic_launcher*` | the winged mark, knocked out white on a red tile | the wordmark is unreadable at 48dp, and a tile of solid brand red carries further across a home screen than a white square with a small picture in it. |
| `drawable-xxxhdpi/qwik_logo.png` | winged Q, no wordmark, red on nothing | the sign-in screen sets "Qwikserve" in Archivo underneath; a baked-in wordmark prints the name twice. |
| `drawable-xxxhdpi/splash_logo.png` | the same mark, squared | centred in a square canvas, over `@color/splash_background`. |

## Why the launcher icon is inverted

The first version of this used **the roundel alone** — the disc is already a
circle, which is what an adaptive mask wants, and the wings are a few pixels
tall at 48dp. It was rejected on sight, and rightly: the wings are what makes
the mark this company's rather than a generic letter in a circle.

What makes a mark 2.5× wider than it is tall work at icon size is the
inversion. White on red holds its detail down to 48dp where thin red feathers
on white turn to mush, and the red fills the tile so the icon's whole shape is
brand. The mark is drawn at **0.70 of the 108dp canvas**: a launcher shows only
the central 72dp, so that is a hair wider than the visible circle and the
outermost feather tips graze its edge. Sizes either side were rendered masked
at 48, 72 and 108 and looked at before this one was picked — smaller left the Q
too small to read, larger cut the wings to stumps.

The splash is **not** inverted. A splash is the app's own background rather
than a tile, so the mark stays red on the near-white the app already paints.

## Two details in the generator worth knowing before changing it

* **White is knocked out only where it touches the border.** The Q's counter is
  an enclosed island of white, so it is a shape in its own right rather than a
  hole showing the wallpaper.
* **The adaptive foreground punches the Q through to transparent** instead of
  painting it. `ic_launcher.xml` points `monochrome` at the same image, and an
  opaque fill there would theme as a featureless blob. Punched through, the red
  `ic_launcher_background` shows the Q on a normal launcher and the alpha gives
  a correct themed icon.
* **The legacy square and round icons are derived from the adaptive
  foreground**, by taking the same central 72dp and flattening it onto the red,
  so the two can never drift apart.

## Colours

`#C22121` is the median of the master's red pixels, not a colour picked by eye,
and it is what the launcher tile is painted (`@color/ic_launcher_background`).

It is deliberately **not** `Qwik.Accent` (`#EC3013`), the brighter red the
Compose theme uses for buttons and tags. The icon carries the logo, so it is
the logo's red; the UI's accent is tuned for small elements on a near-white
screen. If the master logo is ever redrawn in a different red, re-run the
generator and update the colour here — the number is printed by the script's
`RED` constant.
