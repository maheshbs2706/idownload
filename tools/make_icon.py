"""Generate assets/icon.ico and assets/hero.png (empty-state illustration)."""
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
os.makedirs(ASSETS, exist_ok=True)
W = (255, 255, 255, 255)


def icon():
    S = 512
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=110, fill=(98, 76, 240, 255))
    d.rectangle((226, 110, 286, 290), fill=W)                       # shaft
    d.polygon([(146, 260), (366, 260), (256, 380)], fill=W)         # head
    d.rounded_rectangle((136, 405, 376, 435), radius=15, fill=W)    # tray
    img.save(os.path.join(ASSETS, "icon.ico"), sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def vgrad(size, top, bottom):
    g = Image.new("RGBA", size)
    px = ImageDraw.Draw(g)
    for y in range(size[1]):
        t = y / max(size[1] - 1, 1)
        px.line([(0, y), (size[0], y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(4)))
    return g


def paste_round(base, box, radius, top, bottom):
    w, h = box[2] - box[0], box[3] - box[1]
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    base.paste(vgrad((w, h), top, bottom), box[:2], mask)


def hero():
    k = 2                                   # supersample for smooth edges
    w, h = 360 * k, 230 * k
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    # soft purple glow behind the document
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((w * .22, h * .12, w * .78, h * .95), fill=(110, 80, 255, 120))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(38 * k)))
    d = ImageDraw.Draw(img)

    # document
    x0, y0, x1, y1 = 130 * k, 52 * k, 230 * k, 178 * k
    paste_round(img, (x0 + 10 * k, y0 - 12 * k, x1 + 10 * k, y1 - 12 * k), 14 * k, (60, 58, 140, 255), (45, 42, 110, 255))
    paste_round(img, (x0, y0, x1, y1), 14 * k, (132, 118, 255, 255), (86, 72, 226, 255))
    d = ImageDraw.Draw(img)
    d.polygon([(x1 - 26 * k, y0), (x1, y0 + 26 * k), (x1 - 26 * k, y0 + 26 * k)], fill=(190, 182, 255, 255))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2 + 6 * k
    d.rectangle((cx - 6 * k, cy - 30 * k, cx + 6 * k, cy + 6 * k), fill=(40, 30, 150, 255))   # arrow shaft
    d.polygon([(cx - 22 * k, cy), (cx + 22 * k, cy), (cx, cy + 24 * k)], fill=(40, 30, 150, 255))
    d.rounded_rectangle((cx - 26 * k, cy + 32 * k, cx + 26 * k, cy + 37 * k), radius=3 * k, fill=(40, 30, 150, 255))

    def badge(cx, cy, size, top, bottom, draw, tilt=0):
        s = size * k
        tile = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        paste_round(tile, (0, 0, s, s), s // 4, top, bottom)
        draw(ImageDraw.Draw(tile), s)
        tile = tile.rotate(tilt, resample=Image.BICUBIC, expand=True)
        shadow = Image.new("RGBA", tile.size, (0, 0, 0, 0))
        shadow.putalpha(ImageChops.multiply(tile.getchannel("A"), Image.new("L", tile.size, 90)))
        shadow = shadow.filter(ImageFilter.GaussianBlur(6 * k))
        pos = (int(cx * k - tile.width / 2), int(cy * k - tile.height / 2))
        img.alpha_composite(shadow, (pos[0], pos[1] + 5 * k))
        img.alpha_composite(tile, pos)

    def youtube(t, s):
        t.polygon([(s * .4, s * .32), (s * .4, s * .68), (s * .7, s * .5)], fill=W)

    def drive(t, s):
        t.polygon([(s * .5, s * .2), (s * .78, s * .68), (s * .22, s * .68)], fill=(255, 205, 60, 255))
        t.polygon([(s * .5, s * .2), (s * .62, s * .2), (s * .88, s * .66), (s * .76, s * .66)], fill=(60, 190, 110, 255))
        t.polygon([(s * .12, s * .66), (s * .24, s * .66), (s * .38, s * .86), (s * .26, s * .86)], fill=(70, 130, 255, 255))
        t.rectangle((s * .26, s * .7, s * .76, s * .82), fill=(70, 130, 255, 255))

    def image(t, s):
        t.rounded_rectangle((s * .2, s * .24, s * .8, s * .76), radius=s // 14, fill=(205, 235, 255, 255))
        t.polygon([(s * .22, s * .74), (s * .45, s * .46), (s * .6, s * .66), (s * .7, s * .56), (s * .78, s * .74)],
                  fill=(60, 190, 190, 255))
        t.ellipse((s * .62, s * .3, s * .72, s * .4), fill=(255, 220, 90, 255))

    def video(t, s):
        t.rounded_rectangle((s * .2, s * .34, s * .8, s * .78), radius=s // 14, fill=(30, 30, 80, 255))
        t.polygon([(s * .43, s * .46), (s * .43, s * .68), (s * .62, s * .57)], fill=(150, 130, 255, 255))
        t.rectangle((s * .2, s * .22, s * .8, s * .34), fill=(235, 235, 255, 255))

    badge(86, 52, 44, (255, 80, 90, 255), (225, 40, 60, 255), youtube, tilt=14)
    badge(278, 46, 44, (255, 255, 255, 255), (225, 230, 245, 255), drive, tilt=-12)
    badge(44, 138, 44, (90, 150, 255, 255), (60, 100, 230, 255), image, tilt=12)
    badge(318, 138, 44, (150, 130, 255, 255), (100, 80, 235, 255), video, tilt=-14)

    # sparkles
    d = ImageDraw.Draw(img)
    for (sx, sy, r) in [(66, 26, 2), (300, 98, 2), (24, 98, 2), (206, 30, 2)]:
        d.ellipse(((sx - r) * k, (sy - r) * k, (sx + r) * k, (sy + r) * k), fill=(150, 130, 255, 255))
    for ang, ln, ox, oy in [(-30, 18, 250, 80), (200, 16, 108, 100), (-20, 14, 280, 114)]:
        a = math.radians(ang)
        d.line((ox * k, oy * k, (ox + ln * math.cos(a)) * k, (oy + ln * math.sin(a)) * k), fill=(140, 120, 255, 200), width=2 * k)
    img.resize((360, 230), Image.LANCZOS).save(os.path.join(ASSETS, "hero.png"))


icon()
hero()
print("assets written")
