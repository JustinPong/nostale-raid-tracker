"""Draws assets/icon.png + assets/icon.ico (treasure chest + returned tick). Run once after tweaking."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024
OUT = Path(__file__).resolve().parent


def gradient(size, top_left, bottom_right):
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (x + y) / (w + h - 2)
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(top_left, bottom_right))
    return img


def mask(size, draw_fn):
    m = Image.new("L", size, 0)
    draw_fn(ImageDraw.Draw(m))
    return m


def paste_gradient(canvas, box, c1, c2, draw_fn):
    x0, y0, x1, y1 = box
    g = gradient((x1 - x0, y1 - y0), c1, c2)
    m = mask((x1 - x0, y1 - y0), draw_fn)
    canvas.paste(g, (x0, y0), m)


def star(d, cx, cy, r, fill):
    k = r * 0.28
    d.polygon([(cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k),
               (cx, cy + r), (cx - k, cy + k), (cx - r, cy), (cx - k, cy - k)], fill=fill)


def build():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # background tile
    bg = gradient((S, S), (49, 46, 129), (147, 51, 234))
    img.paste(bg, (0, 0), mask((S, S), lambda d: d.rounded_rectangle((24, 24, S - 24, S - 24), 220, fill=255)))
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((180, 160, 860, 760), fill=(250, 204, 21, 70))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(90)))

    # chest shadow
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((230, 470, 810, 830), 60, fill=(15, 10, 40, 150))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(30)), (10, 26))

    gold, gold_dark, ink = (251, 191, 36), (180, 83, 9), (69, 26, 3)
    # body
    paste_gradient(img, (220, 470, 804, 812), (217, 119, 6), (120, 53, 15),
                   lambda d: d.rounded_rectangle((0, 0, 583, 341), 48, fill=255))
    # lid (dome)
    paste_gradient(img, (220, 268, 804, 500), (245, 158, 11), (146, 64, 14),
                   lambda d: (d.rounded_rectangle((0, 60, 583, 231), 40, fill=255),
                              d.ellipse((0, 0, 583, 200), fill=255)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((220, 470, 804, 812), 48, outline=ink, width=14)
    d.arc((220, 268, 804, 468), 180, 360, fill=ink, width=14)
    d.line((220, 368, 220, 480), fill=ink, width=14)
    d.line((804, 368, 804, 480), fill=ink, width=14)
    # gold trims
    d.rectangle((220, 462, 804, 506), fill=gold, outline=ink, width=10)
    for x in (300, 682):
        d.rectangle((x, 300, x + 42, 812), fill=gold, outline=ink, width=10)
    # lock plate + keyhole
    d.rounded_rectangle((452, 420, 572, 580), 26, fill=(253, 230, 138), outline=ink, width=12)
    d.ellipse((494, 470, 530, 506), fill=ink)
    d.polygon([(500, 495), (524, 495), (532, 548), (492, 548)], fill=ink)
    # sparkles
    star(d, 812, 214, 70, (254, 240, 138))
    star(d, 724, 140, 34, (254, 240, 138))
    star(d, 214, 230, 40, (254, 249, 195))

    # returned-tick badge
    d.ellipse((616, 616, 948, 948), fill=(255, 255, 255))
    paste_gradient(img, (636, 636, 928, 928), (74, 222, 128), (21, 128, 61),
                   lambda dd: dd.ellipse((0, 0, 291, 291), fill=255))
    d = ImageDraw.Draw(img)
    d.line([(704, 790), (765, 852), (870, 724)], fill=(255, 255, 255), width=44, joint="curve")
    for x, y in ((704, 790), (870, 724)):
        d.ellipse((x - 22, y - 22, x + 22, y + 22), fill=(255, 255, 255))
    return img


if __name__ == "__main__":
    icon = build()
    icon.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    icon.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    preview = Image.new("RGBA", (256 + 128 + 64 + 32 + 16 + 60, 260), (32, 32, 32, 255))
    x = 10
    for n in (256, 128, 64, 32, 16):
        preview.alpha_composite(icon.resize((n, n), Image.LANCZOS), (x, 2))
        x += n + 10
    preview.save(OUT / "_preview.png")
    print("ok")
