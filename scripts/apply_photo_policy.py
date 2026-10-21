"""Apply the final photo policy to the exact code shapes in each repo.

  1. the text branch: the REAL photo, or text-only. No generated card.
  2. the video branch: the REAL source video. The generated reel is opt-in
     (REELS=1), because a generated reel is AI slop and the page is judged
     on whether the content is real.
"""
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
BRAND = "market" if ("soq" in REPO.name or "market" in REPO.name) else "ethan"
bot = REPO / "post_bot.py"
src = bot.read_text(encoding="utf-8")
changed = []

# ---------------------------------------------------------------- the text branch
CARD_BLOCK = """    # DESIGNED CARD, not a stock photo. Oct 2026: the pages were posting
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
""" % BRAND

PHOTO_BLOCK = """    # THE REAL PHOTO. The source account's own image - the chart, the
    # screenshot, the photo it was published with - or the article's
    # editorial image. The curated composites and the generic image
    # searches are what made this feed look like clip art; they are the
    # fallback now. And the generated card is gone from this path: if
    # there is no real photo, the post goes out text-only. A text post
    # beats a fake one.
    post = add_source(post, outlet_for(pick["feed"]))
    img, ext, src = find_photo(pick)
    if img:
        log(f"Photo: {src}")
    else:
        log("No real photo for this story - posting text-only")
        img, ext, src = None, None, "text-only"
    post = add_credit(post, credit_for(pick["feed"], src))
    log(f"Visual: {src} | credit added")
"""

if CARD_BLOCK in src:
    src = src.replace(CARD_BLOCK, PHOTO_BLOCK, 1)
    changed.append("text branch: the REAL photo, or text-only")
elif PHOTO_BLOCK in src:
    changed.append("text branch already on the real-photo policy")
else:
    print("  !! text-branch anchor not found")

# ---------------------------------------------------------------- the video branch
OLD_A = """                    vid = None
                    try:
                        if reel is None:
                            raise RuntimeError("reel module not available")
                        vid = reel.build_reel(
                            vpost, vpick.get("keywords", []),
                            outlet_for(vpick["feed"]),
                            os.getenv("CARD_BRAND", "%s"),
                            LANG,
                            llm=lambda s, u: gen_gemini("gemini-3.5-flash", s, u))
                        if vid:
                            log("Generated reel built (original content)")
                    except Exception as _rex:
                        log(f"reel build failed: {_rex}")
                    if not vid:
                        vid = _download_video(vpick["video_url"])
                        if vid:
                            log("Falling back to the downloaded footage")
""" % BRAND

OLD_B = """                vid = None
                try:
                    if reel is None:
                        raise RuntimeError("reel module not available")
                    vid = reel.build_reel(
                        vpost, vpick.get("keywords", []),
                        outlet_for(vpick["feed"]),
                        os.getenv("CARD_BRAND", "%s"),
                        LANG,
                        llm=lambda s, u: gen_gemini("gemini-3.5-flash", s, u))
                    if vid:
                        log("Generated reel built (original content)")
                except Exception as _rex:
                    log(f"reel build failed: {_rex}")
                if not vid:
                    vid = _download_video(vpick["video_url"])
                    if vid:
                        log("Falling back to the downloaded footage")
""" % BRAND

NEW_A = """                    # A REAL reel: the actual video the source posted. The
                    # generated reel is opt-in (REELS=1) - a generated one
                    # is AI slop, and the page is judged on whether the
                    # content is real.
                    vid = None
                    if os.getenv("REELS", "0") == "1":
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
                                photo=(_photo[0] if _photo and _photo[0] else None))
                            if vid:
                                log("Generated reel built (REELS=1)")
                        except Exception as _rex:
                            log(f"reel build failed: {_rex}")
                    if not vid:
                        vid = _download_video(vpick["video_url"])
                        if vid:
                            log("Posted the real video from the source")
""" % BRAND

NEW_B = NEW_A.replace("\n                    ", "\n                ") \
              .replace("                    # A REAL reel", "                # A REAL reel") \
              .replace("                    vid = None", "                vid = None") \
              .replace("                    if os.getenv", "                if os.getenv") \
              .replace("                    if not vid:", "                if not vid:") \
              .replace("                        vid = _download_video", "                    vid = _download_video") \
              .replace("                            log(\"Posted the real video from the source\")",
                       "                        log(\"Posted the real video from the source\")")

for old, new, label in ((OLD_A, NEW_A, "A"), (OLD_B, NEW_B, "B")):
    if old in src:
        src = src.replace(old, new, 1)
        changed.append(f"video branch ({label}): the real source video; the "
                       f"generated reel is opt-in")
        break
else:
    print("  !! video-branch anchor not found")

bot.write_text(src, encoding="utf-8")
print(f"[{REPO.name}]")
for c in changed:
    print("  -", c)
if not changed:
    print("  (nothing to do)")
