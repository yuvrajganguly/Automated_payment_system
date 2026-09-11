# Brand assets

`qwikserve-logo.png` is the master lockup — winged Q above the QWIKSERVE
wordmark, red on white, 1200×1200. Everything in `app/src/main/res` that shows
the mark is generated from it by `tools/make_icons.py`; edit the master and
re-run rather than touching the PNGs by hand.

Three crops come out of it, because one image cannot do all three jobs:

| Output | What it is | Why not the whole lockup |
|---|---|---|
| `mipmap-*/ic_launcher*` | the roundel alone | at 48dp the wings are a red smear, and an adaptive icon's mask clips their tips whatever you do. The roundel is already a circle, which is what the mask wants. |
| `drawable-xxxhdpi/qwik_logo.png` | winged Q, no wordmark | the sign-in screen sets "Qwikserve" in Archivo underneath; a baked-in wordmark prints the name twice. |
| `drawable-xxxhdpi/splash_logo.png` | winged Q, squared | same mark, centred in a square canvas. |

Two details in the generator worth knowing before changing it:

* **White is knocked out only where it touches the border.** The Q's counter is
  an enclosed island of white and stays opaque, so the mark keeps a white Q
  instead of showing whatever sits behind it.
* **The adaptive foreground knocks the Q through to transparent** instead of
  painting it white. `ic_launcher.xml` points `monochrome` at the same image,
  and an opaque white Q there would fill in and leave a featureless red blob
  on a themed-icon launcher. Knocked through, the white `ic_launcher_background`
  shows the Q on a normal launcher and the alpha gives a correct themed icon.
