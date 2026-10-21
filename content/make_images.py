#!/usr/bin/env python3
"""
make_images.py — build the 1200x630 product-post images for the
EdgeTrading Pro campaign and emit content/product_posts.json.

The images are NOT abstract graphics: every one of them is a REAL
screenshot of the product (the StockerAI terminal rendered from its own
output HTML, or a real TradingView chart of the EdgeTrading indicators
taken from the shipped product assets), with one short line of type
over it in the brand's own dark aesthetic.

Usage:
    python make_images.py --lang en
    python make_images.py --lang ar

Dependencies: pillow, arabic-reshaper, python-bidi
"""
import argparse
import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- paths
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CONTENT = os.path.join(REPO, "content")
IMG_DIR = os.path.join(CONTENT, "img")

# Where the real product assets live. Override with --assets if the
# machine layout differs.
DEFAULT_ASSETS = os.path.join(
    os.environ.get("TEMP", "/tmp"), "opencode", "etdocs")

# ---------------------------------------------------------------- brand
# Terminal dark system (app/static/css/theme.css + the dashboard's own
# inline design tokens): deep matte black, volcanic panel, steel border,
# muted corporate blue accent, signal green/red.
INK = {
    "bg": (8, 9, 11),
    "panel": (13, 14, 18),
    "border": (28, 30, 36),
    "text": (243, 244, 246),
    "muted": (156, 163, 175),
    "accent": (63, 97, 236),
    "green": (16, 185, 129),
    "amber": (245, 158, 11),
}
W, H = 1200, 630

FONT_EN = r"C:\Windows\Fonts\segoeuib.ttf"
FONT_EN_BOLD = r"C:\Windows\Fonts\segoeuib.ttf"
FONT_MONO = r"C:\Windows\Fonts\consolab.ttf"
FONT_AR = r"C:\Windows\Fonts\tahomabd.ttf"
FONT_AR_BODY = r"C:\Windows\Fonts\tahoma.ttf"

# ---------------------------------------------------------------- sources
# Each entry: (source file, crop box or None, caption anchor)
# Crop boxes were chosen on the real renders so the product stays the
# subject of the frame.
SOURCES = {
    "cot_index":    ("web/image1.jpg", None),
    "seasonality":  ("web/image2.jpg", None),
    "smart_money":  ("web/image3.jpg", None),
    "valuation":    ("web/image4.jpg", None),
    "hero":         ("web/image5.jpg", None),
    "cot_report":   ("pdfimg/p2_1.png", None),
    "val_settings": ("pdfimg/p4_2.png", None),
    "combo":        ("pdfimg/p5_1.png", None),
    "term_overview": ("shots/nvda_dash.png", (0, 0, 1600, 840)),
    "term_stats":   ("shots/nvda_stats.png", (0, 160, 1600, 1000)),
    "hub":          ("shots/hub_index.png", (0, 120, 1600, 960)),
    "screener":     ("shots/screener.png", (0, 60, 1600, 900)),
    "guide":        ("shots/guide_top.png", (0, 40, 1600, 880)),
}


# ---------------------------------------------------------------- helpers
def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def shape_ar(text):
    """Arabic shaping + bidi so PIL (no raqm) renders it correctly."""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        r = arabic_reshaper.reshape(text)
        try:
            return get_display(r, base_dir="R")
        except TypeError:
            return get_display(r)
    except Exception:
        return text


def fit_cover(im, size, box=None):
    """Crop (optional box), then scale-to-cover and centre-crop."""
    if box:
        im = im.crop(box)
    tw, th = size
    sw, sh = im.size
    scale = max(tw / sw, th / sh)
    nw, nh = max(tw, int(sw * scale + 0.5)), max(th, int(sh * scale + 0.5))
    im = im.resize((nw, nh), Image.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return im.crop((left, top, left + tw, top + th))


def fit_contain(im, size, bg=(0, 0, 0)):
    """Letterbox on a black canvas so nothing of the product is cut."""
    tw, th = size
    sw, sh = im.size
    scale = min(tw / sw, th / sh)
    nw, nh = int(sw * scale + 0.5), int(sh * scale + 0.5)
    canvas = Image.new("RGB", size, bg)
    canvas.paste(im.resize((nw, nh), Image.LANCZOS), ((tw - nw) // 2, (th - nh) // 2))
    return canvas


def wrap(draw, text, font, max_w):
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def scrim(img, start=0.28, bottom_alpha=242, power=0.80):
    """Bottom gradient so the headline stays legible over any chart,
    without hiding the product behind an opaque plate."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    h = img.size[1]
    y0 = int(h * start)
    for y in range(y0, h):
        t = (y - y0) / max(1, (h - 1 - y0))
        a = int(bottom_alpha * (t ** power))
        d.line([(0, y), (img.size[0], y)], fill=(4, 5, 7, a))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["en", "ar"], required=True)
    ap.add_argument("--assets", default=DEFAULT_ASSETS)
    ap.add_argument("--spec", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    spec_path = args.spec or os.path.join(args.assets, f"posts_{args.lang}.json")
    out_dir = args.out or IMG_DIR
    os.makedirs(out_dir, exist_ok=True)

    spec = json.load(open(spec_path, encoding="utf-8"))
    brand = spec["meta"]["brand_line"]
    arabic = args.lang == "ar"
    accent = INK["accent"]

    posts = []
    for p in spec["posts"]:
        key = p["image_src"]
        rel, box = SOURCES[key]
        base = os.path.join(args.assets, rel)
        out_path = os.path.join(out_dir, p["id"] + ".jpg")
        raw = Image.open(base)
        img = fit_cover(raw.convert("RGB"), (W, H), box)
        img = scrim(img)
        d = ImageDraw.Draw(img)
        pad = 58

        text = shape_ar(p["image_headline"]) if arabic else p["image_headline"]
        fpath = FONT_AR if arabic else FONT_EN
        size = 48 if arabic else 46
        font = _font(fpath, size)
        max_w = W - 2 * pad
        lines = wrap(d, text, font, max_w)
        while size > 24 and (len(lines) > 2 or
                             any(d.textlength(l, font=font) > max_w for l in lines)):
            size -= 2
            font = _font(fpath, size)
            lines = wrap(d, text, font, max_w)
        y = 392
        # vertical accent bar framing the headline
        d.rectangle([pad - 16, y, pad - 11, y + int(size * 1.22 * len(lines))],
                    fill=accent)
        for ln in lines:
            d.text((pad, y), ln, font=font, fill=INK["text"],
                   stroke_width=3, stroke_fill=(0, 0, 0))
            y += int(size * 1.22)

        bf = _font(FONT_MONO, 19)
        btxt = brand
        tw = d.textlength(btxt, font=bf)
        d.text((W - pad - tw, H - 52), btxt, font=bf, fill=(210, 214, 222),
               stroke_width=2, stroke_fill=(0, 0, 0))

        img.save(out_path, "JPEG", quality=92, optimize=True)
        print("image:", out_path)

        entry = {
            "id": p["id"],
            "lang": p["lang"],
            "title": p["title"],
            "body": p["body"],
            "hashtags": p["hashtags"],
            "image": os.path.abspath(out_path),
            "questions": p["questions"],
            "cta": p["cta"],
            "source": p["source"],
            "image_headline": p["image_headline"],
        }
        posts.append(entry)

    out_json = args.out and os.path.join(
        os.path.dirname(args.out), "product_posts.json") or os.path.join(
        CONTENT, "product_posts.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    print("json:", out_json, len(posts), "posts")


if __name__ == "__main__":
    sys.exit(main())
