"""Replace the stock-photo path with the designed card.

The pages were posting stock photos (a building, gold bars, a flag) and
getting zero engagement and near-zero views. A generic image carries no
information - nobody stops scrolling for it, and the algorithm learns the
page posts things nobody wants. The cover art of these pages is a designed
composite, and that is the standard the posts have to match.

So: every text post now renders a DESIGNED card from the post's own hook
(the number, the headline, the brand wordmark, the category strip). Same
visual language as the cover, no stock photography, no API cost, and it
renders in milliseconds.

Video posts are untouched - the video IS the visual.
"""
import re
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
BRAND = sys.argv[2] if len(sys.argv) > 2 else "ethan"
bot = REPO / "post_bot.py"
src = bot.read_text(encoding="utf-8")
changed = []

# ---- import
if "import card_design" not in src:
    src = src.replace(
        "try:\n    import growth",
        "try:\n    import card_design\n"
        "except Exception as _cerr:\n"
        "    card_design = None\n"
        "    print(f\"WARNING: card_design not loaded: {_cerr}\", flush=True)\n"
        "try:\n    import growth", 1)
    changed.append("import card_design")

# ---- the card replaces find_photo in the TEXT branch
old = """    h = item_hash(pick["link"], pick["title"])
    img, ext, src = find_photo(pick)
    if os.getenv("PHOTO_SELECTIVE", "1") == "1" \\
            and not photo_worth_posting(src):
        log(f"Photo {src} not worth posting, going text-only.")
        img, src = None, "text-only"
    post = add_credit(post, credit_for(pick["feed"], src))
    post = add_source(post, outlet_for(pick["feed"]))
    log(f"Photo: {src or 'none'} | credit added")
"""
new = """    h = item_hash(pick["link"], pick["title"])
    # DESIGNED CARD, not a stock photo. Oct 2026: the pages were posting
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
            os.getenv("CARD_BRAND", "%s"))
        ext = "jpeg"
        src = "card"
        log("Designed card rendered")
    except Exception as _cex:
        log(f"Card design failed ({_cex}) - falling back to text-only")
    post = add_credit(post, credit_for(pick["feed"], src))
    log(f"Visual: {src} | credit added")
"""
if old in src:
    src = src.replace(old, new, 1)
    changed.append("designed card replaces the stock photo")
else:
    print("  !! text-branch photo anchor not found")

bot.write_text(src, encoding="utf-8")

# ---- requirements: the Arabic shaping libs
req = REPO / "requirements.txt"
r = req.read_text(encoding="utf-8")
for line in ("arabic-reshaper>=3.0.1", "python-bidi>=0.6.6"):
    if line.split(">=")[0] not in r:
        r = r.rstrip("\n") + "\n" + line + "\n"
req.write_text(r, encoding="utf-8")
changed.append("requirements: arabic-reshaper + python-bidi")

# ---- workflow: the card brand
wf = REPO / ".github" / "workflows" / "fb-post.yml"
w = wf.read_text(encoding="utf-8")
if "CARD_BRAND" not in w:
    w = w.replace('      POST_STORIES: "1"',
                  '      POST_STORIES: "1"\n'
                  f'      CARD_BRAND: "{BRAND}"')
    wf.write_text(w, encoding="utf-8")
    changed.append(f"workflow CARD_BRAND={BRAND}")

print(f"[{REPO.name}]")
for c in changed:
    print("  -", c)
if not changed:
    print("  (nothing to do)")
