"""Regex-based version of the photo fix, for the two repos whose code differs
slightly in whitespace. Same intent:
  - the story's own photo first (gated)
  - the generated card only as a last resort
  - the reel uses the photo as its background
"""
import re
import shutil
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
BRAND = "market" if "soq" in REPO.name or "market" in REPO.name else "ethan"
bot = REPO / "post_bot.py"
src = bot.read_text(encoding="utf-8")
changed = []

# ---- the text branch: a real photo, the card only as a last resort
pat = re.compile(
    r"    # DESIGNED CARD, not a stock photo\..*?"
    r"    log\(f\"Visual: \{src\} \| credit added\"\)\n", re.S)
m = pat.search(src)
if m:
    new = '''    # A REAL PHOTO of the story, first. The article's own image is the
    # actual story, shot by an actual photographer; a generic image search
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
                os.getenv("CARD_BRAND", "%s"))
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
''' % BRAND
    src = src[:m.start()] + new + src[m.end():]
    changed.append("the text branch uses a real photo; the card is the last resort")
else:
    print("  !! text-branch anchor not found")

# ---- the reel: a real photo as the background
pat2 = re.compile(
    r"(                    vid = reel\.build_reel\(\n"
    r"                        vpost, vpick\.get\(\"keywords\", \[\]\),\n"
    r"                        outlet_for\(vpick\[\"feed\"\]\),\n"
    r"                        os\.getenv\(\"CARD_BRAND\", \"[a-z]+\"\),\n"
    r"                        LANG,\n"
    r"                        llm=lambda s, u: gen_gemini\(\"gemini-3\.5-flash\", s, u\))")
m2 = pat2.search(src)
if m2:
    new2 = m2.group(1).replace(
        "                        llm=lambda s, u: gen_gemini(\"gemini-3.5-flash\", s, u))",
        "                        llm=lambda s, u: gen_gemini(\"gemini-3.5-flash\", s, u),\n"
        "                        photo=(_photo[0] if _photo and _photo[0] else None))")
    new2 = ("                    _photo = find_photo(vpick)\n" + new2)
    src = src[:m2.start()] + new2 + src[m2.end():]
    changed.append("the reel uses the story photo as its background")
else:
    print("  !! reel anchor not found")

bot.write_text(src, encoding="utf-8")
print(f"[{REPO.name}]")
for c in changed:
    print("  -", c)
if not changed:
    print("  (nothing to do)")
