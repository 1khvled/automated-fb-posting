import os, sys, importlib.util, io
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv

REPO = Path(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot")
load_dotenv(REPO / ".env", override=False)
spec = importlib.util.spec_from_file_location("bot", REPO / "post_bot.py")
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

cands = bot.fetch_x_candidates(1440)
with_photo = [c for c in cands if c.get("photo_url")]
print(f"{len(cands)} candidates, {len(with_photo)} with a source photo\n")

from PIL import Image
OUT = REPO / "_study"
OUT.mkdir(exist_ok=True)
picks = []
for c in with_photo[:6]:
    img, ext, src = bot.find_photo(c)
    if not img:
        print(f"  {c.get('feed'):<22} {c.get('title','')[:44]:<46} -> NO PHOTO")
        continue
    im = Image.open(io.BytesIO(img))
    fn = OUT / f"pick_{len(picks)}.jpg"
    fn.write_bytes(img)
    picks.append(fn)
    print(f"  {c.get('feed'):<22} {c.get('title','')[:44]:<46} -> src={src:<12} "
          f"{im.size} {len(img):,}B  {fn.name}")

# also check a candidate whose source has NO photo (does it fall through sanely?)
nophoto = [c for c in cands if not c.get("photo_url")][:3]
print("\ncandidates with no source photo (should fall through to the curated "
      "visual, or text-only):")
for c in nophoto:
    img, ext, src = bot.find_photo(c)
    print(f"  {c.get('feed'):<22} -> src={src}")

if picks:
    # a contact sheet of what the bot would now post
    cols = 3
    tw, th = 340, 210
    rows = (len(picks) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + 20)), (18, 18, 22))
    dr = ImageDraw = None
    from PIL import ImageDraw as ID
    d = ID.Draw(sheet)
    try:
        f = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 14) if False else None
    except Exception:
        f = None
    for i, p in enumerate(picks):
        im = Image.open(p).convert("RGB")
        im.thumbnail((tw - 8, th - 8))
        x = (i % cols) * tw + 4
        y = (i // cols) * (th + 20) + 4
        sheet.paste(im, (x, y))
    sheet.save(OUT / "picks.jpg", "JPEG", quality=88)
    print("\nsheet ->", OUT / "picks.jpg")
