"""Put the good photos back, and make the generated card the last resort.

The pages were posting the story's OWN photo last - behind curated subject
visuals, a Google search and an Openverse search. Those two search fallbacks
are where the bad images came from: a random Openverse hit is a photo of
some unrelated thing, and a Google image search for "gold" returns a photo
of a gold bar. The article's own hero image is the actual story, shot by
an actual photographer, and it was being discarded.

So the order becomes:

  1. the story's own image (photo_url, then the og:image) - but only if it
     PASSES A PHOTO GATE: big enough, and enough colour variety to be a
     photograph rather than a logo card, a tracker pixel or a flat graphic
  2. the curated subject visuals (the face, the logo, the split card)
  3. the curated topic photos
  4. Google, then Openverse - and only if they look like a real photo

And the generated card stops being the default: it is now the fallback for
when there is no usable photo at all, instead of a text-only post.

The reel gets the same treatment: the photo becomes the background of the
scenes, with the type on top, instead of a typographic card.
"""
import re
import shutil
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
bot = REPO / "post_bot.py"
src = bot.read_text(encoding="utf-8")
changed = []

GATE = '''
def _looks_like_photo(data: bytes) -> bool:
    """Is this a real photograph, or a logo / tracker pixel / flat graphic?

    The bad images on the page were never the article's own photo - they
    were what a generic image SEARCH turned up. But the article's photo
    is not always a photo either: plenty of sites use a logo card or a
    1200x1200 banner as their og:image. So the gate is:
      - big enough to be a real editorial image
      - enough colour variety to be a photograph (a flat graphic has a
        few dozen distinct colours, a photo has thousands)
      - not a tiny file
    """
    try:
        from PIL import Image
        import io as _io
        im = Image.open(_io.BytesIO(data)).convert("RGB")
    except Exception:
        return False
    w, h = im.size
    if w < 800 or h < 450:
        return False
    if len(data) < 25000:
        return False
    try:
        small = im.resize((80, 80), Image.BILINEAR).quantize(colors=48)
        colours = len(set(small.getdata()))
    except Exception:
        return False
    return colours >= 18


'''

# ---- 1. the gate function
if "_looks_like_photo" not in src:
    anchor = "def find_photo(candidate: dict):"
    src = src.replace(anchor, GATE.lstrip("\n") + anchor, 1)
    changed.append("added the photo gate")

# ---- 2. the text branch: photo first, the card only as a last resort
old_text = """    # DESIGNED CARD, not a stock photo. Oct 2026: the pages were posting
    # stock imagery (a building, gold bars, a flag) and getting zero
    # engagement and near-zero views - a generic image carries no
    # information, so nobody stops for it. The cover art of these pages is
    # a designed composite; the posts now match it.
    post = add_source(post, outlet_for(pick["feed"]))
    img, ext, src = None, None, "text-only"
    try:
        if card_design is None:
            raise RuntimeError("card_design not available")
        img = card_design.design_card(
            post, pick.get("keywords", []), outlet_for(pick["feed"]),
            os.getenv("CARD_BRAND", "ethan"))
        ext = "jpeg"
        src = "card"
        log("Designed card rendered")
    except Exception as _cex:
        log(f"Card design failed ({_cex}) - falling back to text-only")
    post = add_credit(post, credit_for(pick["feed"], src))
    log(f"Visual: {src} | credit added")
"""
new_text = """    # A REAL PHOTO of the story, first. The article's own image is the
    # actual story shot by an actual photographer; a generic image search
    # is not. The generated card is only the fallback for when there is no
    # usable photo at all.
    post = add_source(post, outlet_for(pick["feed"]))
    img, ext, src = find_photo(pick)
    if not img:
        try:
            if card_design is None:
                raise RuntimeError("card_design not available")
            img = card_design.design_card(
                post, pick.get("keywords", []), outlet_for(pick["feed"]),
                os.getenv("CARD_BRAND", "ethan"))
            ext = "jpeg"
            src = "card"
            log("No usable photo - generated card instead")
        except Exception as _cex:
            log(f"Card design failed ({_cex}) - text-only")
            img, ext, src = None, None, "text-only"
    else:
        log(f"Photo: {src}")
    post = add_credit(post, credit_for(pick["feed"], src))
    log(f"Visual: {src} | credit added")
"""
if old_text in src:
    src = src.replace(old_text, new_text, 1)
    changed.append("the text branch uses a real photo; the card is the last resort")
else:
    print("  !! text-branch card anchor not found")

# ---- 3. the reel: a real photo as the background
old_reel = """                vid = None
                try:
                    if reel is None:
                        raise RuntimeError("reel module not available")
                    vid = reel.build_reel(
                        vpost, vpick.get("keywords", []),
                        outlet_for(vpick["feed"]),
                        os.getenv("CARD_BRAND", "%s"),
                        LANG,
                        llm=lambda s, u: gen_gemini("gemini-3.5-flash", s, u))"""
new_reel = """                vid = None
                try:
                    if reel is None:
                        raise RuntimeError("reel module not available")
                    _photo = find_photo(vpick)
                    vid = reel.build_reel(
                        vpost, vpick.get("keywords", []),
                        outlet_for(vpick["feed"]),
                        os.getenv("CARD_BRAND", "%s"),
                        LANG,
                        llm=lambda s, u: gen_gemini("gemini-3.5-flash", s, u),
                        photo=(_photo[0] if _photo and _photo[0] else None))""" % (
    "ethan" if "ethan" in REPO.name else "market")
if old_reel in src:
    src = src.replace(old_reel, new_reel, 1)
    changed.append("the reel uses the story photo as its background")
else:
    print("  !! reel anchor not found")

# ---- 4. move the story art to the FRONT of find_photo
m = re.search(
    r"    # 2\. source art fallback.*?\n    if not raw:\n        gdata, _gext = _google_photo\(",
    src, re.S)
if m:
    block = m.group(0)
    # cut the story-art part out of the block (up to the google fallback)
    story_part = block.split("    if not raw:\n        gdata, _gext = _google_photo(")[0]
    rest = "    if not raw:\n        gdata, _gext = _google_photo(" + \
        block.split("    if not raw:\n        gdata, _gext = _google_photo(")[1]
    new_block = story_part.replace(
        "    # 2. source art fallback (demoted from first: editorial hero images are\n"
        "    # generic as often as apt)",
        "    # THE STORY'S OWN PHOTO, FIRST. This is the actual story, shot by an\n"
        "    # actual photographer. It used to be demoted behind curated subject\n"
        "    # visuals and two image searches - and a generic image search is\n"
        "    # where the bad images came from. The gate rejects logo cards, tracker\n"
        "    # pixels and flat graphics.") + rest
    # insert the story part at the very top of find_photo
    src = src.replace(block, new_block, 1)
    # now move the story part (with its gate) to the top of find_photo
    mm = re.search(
        r"    # THE STORY'S OWN PHOTO, FIRST\..*?\n    if raw and not _big_enough\(raw\[0\]\):\n"
        r"        log\(\"Source/og photo too small, falling through to curated photos\"\)\n"
        r"        raw = None\n", src, re.S)
    if mm:
        story = mm.group(0)
        # remove it from its current place
        src = src.replace(story, "", 1)
        # insert it right after find_photo's docstring
        anchor = "    # 1. subject visuals: person/face, entity logo, topic scenes"
        src = src.replace(anchor, story + anchor, 1)
        # and return it when it passes the photo gate
        src = src.replace(
            "    # 1. subject visuals: person/face, entity logo, topic scenes\n"
            "    vimg, vext, vsrc = select_visuals(candidate)",
            "    if raw and _looks_like_photo(raw[0]):\n"
            "        log(f\"Using the story's own photo ({raw[1]})\")\n"
            "        return raw[0], \"jpeg\", raw[1]\n"
            "    if raw:\n"
            "        log(\"Story photo is not a real photo (logo/graphic/small) - \"\n"
            "            \"using the curated subject visual instead\")\n"
            "        raw = None\n\n"
            "    # 1. subject visuals: person/face, entity logo, topic scenes\n"
            "    vimg, vext, vsrc = select_visuals(candidate)", 1)
        changed.append("the story's own photo now wins, gated by _looks_like_photo")
    else:
        print("  !! story-art block not matched for the move")
else:
    print("  !! source-art block not found")

bot.write_text(src, encoding="utf-8")

# ---- 5. the reel module: accept a photo background
rl = REPO / "scripts" / "reel.py"
if rl.exists():
    r = rl.read_text(encoding="utf-8")
    if "photo: bytes | None = None" not in r:
        r = r.replace(
            'def build_reel(post_text: str, topics=None, outlet: str = "", brand: str = "ethan",\n'
            '               lang: str = "en", llm=None, workdir: Path | None = None) -> bytes:',
            'def build_reel(post_text: str, topics=None, outlet: str = "", brand: str = "ethan",\n'
            '               lang: str = "en", llm=None, workdir: Path | None = None,\n'
            '               photo: bytes | None = None) -> bytes:')
        # the scenes get the photo as a background
        r = r.replace(
            "    scenes = [\n"
            "        (_scene_brand(brand, tag, tag), 3.0),\n"
            "        (_scene_number(brand, num, direction, hook, lang), 6.0),\n"
            "        (_scene_end(brand, cta, \"  ·  \".join(b[\"strip\"]), lang), 3.5),\n"
            "    ]",
            "    scenes = [\n"
            "        (_scene_brand(brand, tag, tag, photo), 3.0),\n"
            "        (_scene_number(brand, num, direction, hook, lang, photo), 6.0),\n"
            "        (_scene_end(brand, cta, \"  ·  \".join(b[\"strip\"]), lang, photo), 3.5),\n"
            "    ]")
        # and the scene builders accept + use it
        r = r.replace(
            "def _scene_brand(brand: str, topic: str, tag: str) -> Image.Image:\n"
            "    b = cd.BRANDS.get(brand, cd.BRANDS[\"ethan\"])\n"
            "    img = cd._gradient((VW, VH), b[\"bg_top\"], b[\"bg_bot\"])\n"
            "    d = ImageDraw.Draw(img)",
            "def _scene_brand(brand: str, topic: str, tag: str,\n"
            "                 photo: bytes | None = None) -> Image.Image:\n"
            "    b = cd.BRANDS.get(brand, cd.BRANDS[\"ethan\"])\n"
            "    img = cd._gradient((VW, VH), b[\"bg_top\"], b[\"bg_bot\"])\n"
            "    if photo:\n"
            "        img = _photo_bg(img, photo)\n"
            "    d = ImageDraw.Draw(img)")
        r = r.replace(
            "def _scene_number(brand: str, num: str, direction: int, headline: str,\n"
            "                   lang: str) -> Image.Image:\n"
            "    b = cd.BRANDS.get(brand, cd.BRANDS[\"ethan\"])\n"
            "    img = cd._gradient((VW, VH), b[\"bg_top\"], b[\"bg_bot\"])\n"
            "    d = ImageDraw.Draw(img)",
            "def _scene_number(brand: str, num: str, direction: int, headline: str,\n"
            "                   lang: str, photo: bytes | None = None) -> Image.Image:\n"
            "    b = cd.BRANDS.get(brand, cd.BRANDS[\"ethan\"])\n"
            "    img = cd._gradient((VW, VH), b[\"bg_top\"], b[\"bg_bot\"])\n"
            "    if photo:\n"
            "        img = _photo_bg(img, photo)\n"
            "    d = ImageDraw.Draw(img)")
        r = r.replace(
            "def _scene_end(brand: str, cta: str, strip: str, lang: str) -> Image.Image:\n"
            "    b = cd.BRANDS.get(brand, cd.BRANDS[\"ethan\"])\n"
            "    img = cd._gradient((VW, VH), b[\"bg_top\"], b[\"bg_bot\"])\n"
            "    d = ImageDraw.Draw(img)",
            "def _scene_end(brand: str, cta: str, strip: str, lang: str,\n"
            "               photo: bytes | None = None) -> Image.Image:\n"
            "    b = cd.BRANDS.get(brand, cd.BRANDS[\"ethan\"])\n"
            "    img = cd._gradient((VW, VH), b[\"bg_top\"], b[\"bg_bot\"])\n"
            "    if photo:\n"
            "        img = _photo_bg(img, photo)\n"
            "    d = ImageDraw.Draw(img)")
        # the background helper
        r = r.replace(
            "# ---------------------------------------------------------------- scenes",
            '''# ---------------------------------------------------------------- scenes
def _photo_bg(base: Image.Image, photo: bytes) -> Image.Image:
    """The story's own photo as the background, darkened so the type reads."""
    try:
        from PIL import ImageFilter
        im = Image.open(io.BytesIO(photo)).convert("RGB")
        scale = max(VW / im.width, VH / im.height)
        im = im.resize((int(im.width * scale) + 1, int(im.height * scale) + 1),
                       Image.LANCZOS)
        x = (im.width - VW) // 2
        y = (im.height - VH) // 2
        im = im.crop((x, y, x + VW, y + VH))
        im = im.filter(ImageFilter.GaussianBlur(3))
        # darken so the white type always reads
        base = Image.blend(base, im, 0.55)
        return Image.blend(base, Image.new("RGB", (VW, VH), (0, 0, 0)), 0.42)
    except Exception:
        return base


''')
        rl.write_text(r, encoding="utf-8")
        changed.append("reel scenes take the photo as a background")
        shutil.copy2(rl, Path(r"C:\Users\Abdelli\Documents\soq-alyoum-fb-bot\scripts\reel.py"))

print(f"[{REPO.name}]")
for c in changed:
    print("  -", c)
if not changed:
    print("  (nothing to do)")
