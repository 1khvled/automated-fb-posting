#!/usr/bin/env python3
"""Designed post cards. This is what replaces the stock photos.

WHY
---
The pages were posting stock photos - a photo of a building, a photo of gold
bars, a photo of a flag - and getting zero engagement and near-zero views.
That is the correct outcome for that content: a generic image carries no
information, nobody stops scrolling for it, and the algorithm learns that the
page posts things nobody wants. The cover art of these pages is a designed
composite, and that is the visual standard the posts have to match.

So every text post now gets a DESIGNED card built from the post's own hook:
the number, the headline, the brand wordmark, the category strip. Same
visual language as the cover, zero stock photography, zero API cost, and it
renders in milliseconds.

The card is built from the REWRITTEN post, not the source, so the Arabic
page gets an Arabic card and the English page an English one.
"""
from __future__ import annotations

import io
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAVE_ARABIC = True
except Exception:      # pragma: no cover
    HAVE_ARABIC = False

W, H = 1200, 630

# ---------------------------------------------------------------- brand
BRANDS = {
    "ethan": {
        "bg_top": (5, 11, 20),
        "bg_bot": (0, 6, 13),
        "accent": (51, 177, 254),
        "text": (255, 255, 255),
        "muted": (138, 152, 172),
        "word": "ETHAN",
        "word2": "COLE",
        "strip": ["STOCKS", "ECONOMY", "INVESTING", "NEWS", "AI & TECH",
                  "GLOBAL MARKETS"],
        "lang": "en",
    },
    "market": {
        "bg_top": (10, 16, 28),
        "bg_bot": (0, 7, 15),
        "accent": (226, 179, 64),
        "text": (255, 255, 255),
        "muted": (150, 158, 172),
        "word": "سوق",
        "word2": "اليوم",
        "strip": ["GOLD", "CRYPTO", "STOCKS", "AI", "MACRO"],
        "lang": "ar",
    },
}

# ---------------------------------------------------------------- fonts
FONT_CANDIDATES_BOLD = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\tahomabd.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size: int, bold: bool = True):
    for p in (FONT_CANDIDATES_BOLD if bold else FONT_CANDIDATES):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _arabic_font(size: int, bold: bool = True):
    """An Arabic-capable font. Falls back to the Latin one (the layout then
    degrades gracefully: the big number and the topic strip are Latin anyway)."""
    ar_paths = [
        r"C:\Windows\Fonts\tahomabd.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    ]
    if not bold:
        ar_paths = [ar_paths[1]] + ar_paths[2:]
    for p in ar_paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return _font(size, bold)


def ar(text: str) -> str:
    if not HAVE_ARABIC or not text:
        return text
    try:
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def is_arabic(text: str) -> bool:
    return any("\u0600" <= c <= "\u06ff" for c in (text or ""))


# ---------------------------------------------------------------- helpers
def _text_size(d, s, f):
    try:
        b = d.textbbox((0, 0), s, font=f)
        return b[2] - b[0], b[3] - b[1]
    except Exception:
        return len(s) * 10, 20


def _fit(d, s, max_w, start, bold=True, arabic=False, min_size=16):
    size = start
    while size > min_size:
        f = _arabic_font(size, bold) if arabic else _font(size, bold)
        if _text_size(d, s, f)[0] <= max_w:
            return f
        size -= 2
    return _arabic_font(min_size, bold) if arabic else _font(min_size, bold)


def _wrap(d, s, f, max_w):
    words, lines, cur = s.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if _text_size(d, trial, f)[0] <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _letterspace(d, x, y, s, f, fill, spacing=3, anchor_right=None):
    """Draw letter-spaced text (the cover uses wide tracking on the strip)."""
    total = sum(_text_size(d, ch, f)[0] + spacing for ch in s) - spacing
    x0 = (anchor_right - total) if anchor_right is not None else x
    for ch in s:
        d.text((x0, y), ch, font=f, fill=fill)
        x0 += _text_size(d, ch, f)[0] + spacing
    return total


def _gradient(size, top, bot):
    w, h = size
    img = Image.new("RGB", (1, h))
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = (int(top[0] + (bot[0] - top[0]) * t),
                     int(top[1] + (bot[1] - top[1]) * t),
                     int(top[2] + (bot[2] - top[2]) * t))
    return img.resize((w, h), Image.BILINEAR)


# ---------------------------------------------------------------- the hook
NUM_RE = re.compile(r"([+\-−]?)\s*([$€£]?)\s*(\d[\d.,]*)\s*(%|B\b|K\b|M\b|T\b|x\b)?")


def find_number(text: str):
    """The most prominent figure in the text: the big number a card should
    lead with. Returns (string, direction) where direction is +1/-1/0.

    If there is only ONE candidate it is always used (a lone "14
    vulnerabilities" is a headline, not an id). With several, the biggest /
    most newsworthy wins."""
    if not text:
        return "", 0
    cands = NUM_RE.findall(text)
    if not cands:
        return "", 0
    parsed = []
    for sign, cur, num, suf in cands:
        try:
            v = float(re.sub(r"[^0-9.]", "", num) or 0)
        except ValueError:
            continue
        if v == 0:
            continue
        parsed.append((sign, cur, num, suf or "", v))
    if not parsed:
        return "", 0
    if len(parsed) == 1:
        sign, cur, num, suf, v = parsed[0]
    else:
        best, best_score = None, -1e9
        for sign, cur, num, suf, v in parsed:
            score = min(v, 100000)
            if suf == "%":
                score += 5000
            if cur:
                score += 2000
            if sign in "+-−":
                score += 1000
            if 1900 < v < 2100:
                score -= 6000          # a year is not a headline
            if score > best_score:
                best_score, best = score, (sign, cur, num, suf, v)
        sign, cur, num, suf, v = best
    out = f"{sign}{cur}{num}{suf}".strip()
    d = 1 if out.startswith("+") else (-1 if out.startswith("-") else 0)
    return out, d


def clean_hook(post_text: str, max_words: int = 16) -> str:
    """The first line of the post, cleaned of emoji/markup, in one sentence."""
    if not post_text:
        return ""
    line = ""
    for ln in post_text.split("\n"):
        ln = ln.strip()
        if ln:
            line = ln
            break
    line = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2190-\u21FF\u2B00-\u2BFF\uFE0F]",
                  "", line)
    line = re.sub(r"^[\W_]+", "", line)
    line = re.sub(r"[*_`#~]+", "", line)
    line = re.sub(r"\s+", " ", line).strip()
    words = line.split()
    if len(words) > max_words:
        line = " ".join(words[:max_words])
    return line


# ---------------------------------------------------------------- the card
def design_card(post_text: str, topics=None, outlet: str = "",
                brand: str = "ethan") -> bytes:
    b = BRANDS.get(brand, BRANDS["ethan"])
    lang = b["lang"]
    img = _gradient((W, H), b["bg_top"], b["bg_bot"])
    d = ImageDraw.Draw(img)

    # soft accent glow, top-right
    glow = Image.new("RGB", (W, H), b["bg_bot"])
    gd = ImageDraw.Draw(glow)
    gd.ellipse((W - 520, -340, W + 320, 400), fill=b["accent"])
    glow = glow.filter(ImageFilter.GaussianBlur(190))
    img = Image.blend(img, glow, 0.16)
    d = ImageDraw.Draw(img)

    # accent hairline at the top
    d.rectangle((0, 0, W, 6), fill=b["accent"])

    ar_page = is_arabic(post_text)

    # ---- wordmark, top-left (Arabic pages put it top-right, RTL)
    fw = _font(46, bold=True)
    fw2 = _font(46, bold=True)
    if lang == "ar" and ar_page:
        f_ar = _arabic_font(46, bold=True)
        # Arabic reads right-to-left: the FIRST word must be the RIGHTMOST.
        # So "سوق" (gold) goes on the right, "اليوم" (white) to its left.
        w1 = _text_size(d, ar(b["word"]), f_ar)[0]
        w2 = _text_size(d, ar(b["word2"]), f_ar)[0]
        x = W - 64 - (w1 + w2 + 8)
        d.text((x, 34), ar(b["word2"]), font=f_ar, fill=b["text"])
        d.text((x + w2 + 8, 34), ar(b["word"]), font=f_ar, fill=b["accent"])
    else:
        w1 = _text_size(d, b["word"], fw)[0]
        d.text((58, 34), b["word"], font=fw, fill=b["text"])
        d.text((58 + w1 + 8, 34), b["word2"], font=fw2, fill=b["accent"])

    # ---- category pill, top-right (English pages) / top-left (Arabic)
    cats = [str(t).replace("_", " ").replace("+", "").upper()
            for t in (topics or []) if t and not str(t).startswith("+")]
    cat = cats[0] if cats else ""
    if cat:
        f_pill = _font(21, bold=True)
        pw = _text_size(d, cat, f_pill)[0] + 34
        px = (W - 58 - pw) if lang != "ar" else 58
        d.rounded_rectangle((px, 38, px + pw, 74), radius=18,
                            outline=b["accent"], width=2)
        d.text((px + 17, 43), cat, font=f_pill, fill=b["accent"])

    # ---- the big number: prefer the hook's OWN number so the hero and the
    # headline never disagree
    hook = clean_hook(post_text)
    body_lines = [ln.strip() for ln in (post_text or "").split("\n") if ln.strip()]
    hook_clean = re.sub(r"^(JUST IN|BREAKING|NEW|🚨|📈|📉)\s*:?\s*", "", hook,
                        flags=re.I).strip()

    num, direction = find_number(hook_clean)
    hero_in_hook = bool(num)
    if not num:
        num, direction = find_number(post_text)

    if hero_in_hook:
        # the number IS in the headline: strip it, headline keeps the rest
        rest = hook_clean.replace(num, "", 1)
        rest = re.sub(r"\s{2,}", " ", rest).strip(" -—:،,")
        # context = the first body line that is not the headline
        context = ""
        for ln in body_lines[1:]:
            c = re.sub(r"[*_`#~]+", "", ln)
            c = re.sub(r"\s+", " ", c).strip()
            if c and c != hook and num not in c:
                context = c
                break
    else:
        # the number is in the body: the headline IS the hook, so do not
        # repeat it as the context line
        rest = hook_clean
        context = ""
        for ln in body_lines[1:]:
            c = re.sub(r"[*_`#~]+", "", ln)
            c = re.sub(r"\s+", " ", c).strip()
            if c and c != hook and num and num in c:
                context = c
                break
            if c and c != hook and not num:
                context = c
                break

    # ---- vertical rhythm: number, headline, context
    y = 132
    if num:
        f_num = _font(132, bold=True)
        while _text_size(d, num, f_num)[0] > W - 150 and f_num.size > 54:
            f_num = _font(f_num.size - 4, bold=True)
        if direction:
            d.text((58, y - 4), ("▲" if direction > 0 else "▼"),
                   font=_font(48, bold=True), fill=b["accent"])
            d.text((58 + 56, y), num, font=f_num, fill=b["accent"])
        else:
            d.text((58, y), num, font=f_num, fill=b["accent"])
        y += 152
        if rest:
            f_h = _fit(d, rest if not ar_page else ar(rest), W - 116, 40,
                       bold=False, arabic=ar_page, min_size=24)
            for ln in _wrap(d, rest if not ar_page else ar(rest), f_h,
                            W - 116)[:3]:
                d.text((58, y), ln, font=f_h, fill=b["text"])
                y += 48
            y += 10
    else:
        # no number: the headline IS the hero, drawn big. Never draw it twice.
        f_hook = _fit(d, rest if not ar_page else ar(rest), W - 116, 58,
                      bold=True, arabic=ar_page, min_size=30)
        for ln in _wrap(d, rest if not ar_page else ar(rest), f_hook,
                        W - 116)[:4]:
            d.text((58, y), ln, font=f_hook, fill=b["text"])
            y += 74
        y += 12

    if context:
        ctx = re.sub(r"[*_`#~]+", "", context)
        ctx = re.sub(r"\s+", " ", ctx).strip()
        if num and num in ctx:
            ctx = ctx.replace(num, "")
        ctx = re.sub(r"\s{2,}", " ", ctx).strip(" -—:،,")
        ctx = re.sub(r"^[\W_]+", "", ctx)[:180]
        if ctx:
            f_c = _fit(d, ctx if not ar_page else ar(ctx), W - 116, 30,
                       bold=False, arabic=ar_page, min_size=20)
            d.rectangle((58, y, 118, y + 3), fill=b["accent"])
            for ln in _wrap(d, ctx if not ar_page else ar(ctx), f_c,
                            W - 116)[:2]:
                d.text((58, y + 18), ln, font=f_c, fill=b["muted"])
                y += 40

    # ---- bottom strip, matching the cover
    strip_y = H - 74
    d.rectangle((0, strip_y - 10, W, strip_y - 8), fill=b["accent"])
    f_s = _font(19, bold=True)
    strip = "  ·  ".join(b["strip"])
    f_o = _font(19, bold=False)
    ow = _text_size(d, outlet, f_o)[0] if outlet else 0
    sw = _text_size(d, strip, f_s)[0] + (len(strip) - 1) * 3
    # never let the source collide with the strip
    if ow and sw + ow + 40 > W - 116:
        outlet = ""
        ow = 0
    if lang == "ar" and ar_page:
        _letterspace(d, 0, strip_y + 8, ar(strip), f_s, b["muted"], 2,
                     anchor_right=W - 58)
        if outlet:
            d.text((58, strip_y + 8), outlet, font=f_o, fill=b["muted"])
    else:
        _letterspace(d, 58, strip_y + 8, strip, f_s, b["muted"], 3)
        if outlet:
            d.text((W - 58 - ow, strip_y + 8), outlet, font=f_o, fill=b["muted"])

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95, optimize=True, progressive=True)
    return buf.getvalue()


def brand_for_page(page_id: str) -> str:
    return "market" if str(page_id) == "1421089964411983" else "ethan"


if __name__ == "__main__":
    import sys
    demo_en = ("JUST IN: JPMorgan just DOUBLED its SpaceX ($SPCX) price target "
               "to $500.\n\nOld target: $240\nNew target: $500\nIncrease: +108%")
    demo_ar = ("مايكل سيلور لشركة الخدمات المالية Charles Schwab: سوق الكريبتو "
               "الصاعد بدأ رسميا!\n\nارتد BTC من متوسط 200 أسبوع وزاد حوالي "
               "20,000 دولار فوق السعر")
    out = []
    for name, txt, br in (("ethan", demo_en, "ethan"), ("market", demo_ar, "market")):
        b = design_card(txt, ["stocks", "crypto"], "Reuters", br)
        p = f"_card_{br}.jpg"
        open(p, "wb").write(b)
        out.append(p)
        print("wrote", p, len(b), "bytes")
