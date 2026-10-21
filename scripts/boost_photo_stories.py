"""Prefer the story that HAS a real photo.

The image is the single biggest lever on a Facebook post's reach, and 18 of
44 X candidates carry one - the chart or screenshot the source published
with. But the bot was ranking purely on story quality, so it regularly
picked a top-scoring story that had NO image and left the visual ones
unposted. WatcherGuru posts the picture; that is the post.

So: a candidate with a real source photo gets a small score boost. Small
enough that a much better story still wins, big enough that a visual
story beats a text-only story of the same quality.
"""
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
bot = REPO / "post_bot.py"
src = bot.read_text(encoding="utf-8")

anchor = '    log(f"{len(fresh)} fresh (not yet posted)")'
boost = '''    log(f"{len(fresh)} fresh (not yet posted)")
    # Prefer a story that CARRIES A REAL PHOTO. 18 of 44 candidates have
    # one - the chart or screenshot the source published with - and a post
    # with the story's own picture is the post that works. The boost is
    # deliberately small: a much better story still wins.
    for _c in fresh:
        if _c.get("photo_url"):
            _c["score"] = round(_c.get("score", 0) + 2.5, 1)
    fresh.sort(key=lambda c: c["score"], reverse=True)'''

if "Prefer a story that CARRIES A REAL PHOTO" in src:
    print("[already applied]")
elif anchor in src:
    src = src.replace(anchor, boost, 1)
    bot.write_text(src, encoding="utf-8")
    print("[boost applied] a candidate with a real photo now scores +2.5")
else:
    print("!! anchor not found")
    raise SystemExit(1)
