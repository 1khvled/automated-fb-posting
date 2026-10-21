"""Sample the brand colours from each page's cover art so the new post
cards match the pages exactly."""
import sys
from collections import Counter
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

for tag, path in (("ETHAN", r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot\_art\cover_1264009986803820.jpg"),
                  ("MARKET", r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot\_art\cover_1421089964411983.jpg")):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    print("=" * 60)
    print(tag, im.size)
    # most saturated pixels = the accent colour
    px = list(im.resize((w // 3, h // 3)).getdata())
    sat = []
    for r, g, b in px:
        mx, mn = max(r, g, b), min(r, g, b)
        if mx > 90 and (mx - mn) > 55:
            sat.append((r, g, b))
    if sat:
        cnt = Counter(sat).most_common(6)
        for (r, g, b), n in cnt:
            print(f"   accent #{r:02X}{g:02X}{b:02X}  ({n} px)")
    # darkest = background
    dk = Counter(p for p in px if sum(p) < 90).most_common(3)
    for (r, g, b), n in dk:
        print(f"   dark   #{r:02X}{g:02X}{b:02X}  ({n} px)")
    # brightest near-white
    wh = Counter(p for p in px if sum(p) > 700).most_common(2)
    for (r, g, b), n in wh:
        print(f"   light  #{r:02X}{g:02X}{b:02X}  ({n} px)")
