"""Rebuild the silent field film. Requires Python, Pillow, and an FFmpeg with libx264.
Run from any directory: python media/build_film.py [path-to-ffmpeg]
"""
from pathlib import Path
import math
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont, ImageOps

source = Path(__file__).resolve().parent
assets = source.parent / "dist" / "assets"
ffmpeg = sys.argv[1] if len(sys.argv) > 1 else "ffmpeg"
W, H, FPS = 1280, 720, 24
size = (W, H)
scenes = [
    ("field-hero.webp", "01  /  THE HUB BRIEF", "Before the first run.", "Set the reporting point, shift times and rider numbers."),
    ("hub-dispatch.webp", "02  /  RIDER ONBOARDING", "Meet the field team.", "Recruiters check documents and confirm the assignment."),
    ("ev-handover.webp", "03  /  EV HANDOVER", "Keys change hands.", "For a rental EV, the team records the vehicle, rider and date."),
    ("hub-dispatch.webp", "04  /  WEEKLY RECONCILIATION", "Close the week.", "Match the paysheet to rent and dues, then check the bank result."),
]
fonts = {n:ImageFont.truetype(str(assets / ("archivo_extrabold.ttf" if n > 35 else "archivo_semibold.ttf")), n) for n in (17, 25, 67)}
gradient = Image.new("L", (1,H))
gradient.putdata([int(14 + 203*(y/H)**2.1) for y in range(H)])
gradient = gradient.resize(size)
dark = Image.new("RGB", size, (18,17,16))
def decorate(image, scene, chapter, progress):
    image = Image.composite(dark, image, gradient)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((46,45,330,85),7,fill="#211f1e")
    draw.text((61,54),"QWIKSERVE   /   FIELD FILM",font=fonts[17],fill="white")
    draw.rectangle((52,471,83,476), fill="#ff6548")
    draw.text((96,457),scene[1],font=fonts[17],fill="#fff0df")
    draw.text((47,490),scene[2],font=fonts[67],fill="white",stroke_width=0)
    draw.text((53,580),scene[3],font=fonts[25],fill="#f5ede6")
    for j in range(4):
        x=52+j*298
        draw.rectangle((x,659,x+279,662),fill="#9d9086" if j>chapter else "#f16a4e")
        if j==chapter:
            draw.rectangle((x+int(279*progress),659,x+279,662),fill="#bea99c")
    return image

enc = subprocess.Popen([ffmpeg,"-y","-hide_banner","-loglevel","error","-f","rawvideo","-pix_fmt","rgb24","-s","1280x720","-r",str(FPS),"-i","pipe:0","-an","-c:v","libx264","-preset","fast","-crf","22","-pix_fmt","yuv420p","-movflags","+faststart",str(assets/"field-film.mp4")],stdin=subprocess.PIPE)
with enc.stdin:
    for c,scene in enumerate(scenes):
        photo = Image.open(assets/scene[0]).convert("RGB")
        photo = ImageOps.fit(photo,(1408,792),centering=(.6,.48))
        # The self-authored chapter diagram follows the photographic introduction.
        decode = subprocess.Popen([ffmpeg,"-hide_banner","-loglevel","error","-ss",str(c*5.5+.55),"-i",str(source/"field-graphics.mp4"),"-frames:v","108","-pix_fmt","rgb24","-f","rawvideo","pipe:1"],stdout=subprocess.PIPE)
        with decode.stdout:
            for frame in range(8*FPS):
                t = frame/FPS
                if t < 4.0:
                    f = t / 4.0
                    zoom = 1+.035*f
                    width, height = int(W/zoom), int(H/zoom)
                    x = int((photo.width-width)*(.41+.12*f))
                    y = int((photo.height-height)*(.39+.04*f))
                    plate = photo.resize(size, Image.Resampling.BICUBIC, (x,y,x+width,y+height))
                    img = decorate(plate,scene,c,t/8)
                    if c==0 and frame==8: img.save(assets/"field-film-poster.webp",quality=87)
                if t >= 3.5:
                    data = decode.stdout.read(W*H*3)
                    if len(data)!=W*H*3: raise RuntimeError("Source film cut short")
                    diagram = Image.frombytes("RGB",size,data)
                    img = Image.blend(img,diagram,(t-3.5)/.5) if t<4 else diagram
                enc.stdin.write(img.tobytes())
        if decode.wait(): raise RuntimeError("Diagram decode failed")
if enc.wait(): raise RuntimeError("Film encode failed")

