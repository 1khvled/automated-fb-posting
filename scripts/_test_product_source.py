import json
import os
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = Path(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot")
sys.path.insert(0, str(REPO / "scripts"))
import product_source as ps

# a synthetic post, to prove the machinery before the real content lands
tmp = Path(tempfile.mkdtemp())
img = tmp / "test.jpg"
from PIL import Image
Image.new("RGB", (1200, 630), (20, 30, 50)).save(img)

post = {
    "id": "test-1",
    "lang": "en",
    "title": "1 terminal. 4 indicators. 0 cloud fees.",
    "body": "StockerAI runs the whole model on your machine. The EdgeTrading Oscillator, COT Index, COT Report, Seasonality and Valuation sit next to it in TradingView.",
    "hashtags": ["#ethancole", "#finance", "#stockmarket", "#investing", "#trading"],
    "image": str(img),
    "questions": ["Which one would you use first?"],
    "cta": "EdgeTrading Pro - link in the first comment",
}
jf = tmp / "product_posts.json"
jf.write_text(json.dumps([post], ensure_ascii=False, indent=1), encoding="utf-8")

print("load_posts     :", len(ps.load_posts(jf)))
print("check_post     :", ps.check_post(post) or "OK")
state = {}
cands = ps.candidates(state, jf)
print("candidates     :", len(cands))
c = cands[0]
print("  title        :", c["title"])
print("  is_product   :", c["is_product"], "| score", c["score"])
print("  local_photo  :", Path(c["local_photo"]).name, "exists:", Path(c["local_photo"]).exists())
print("  keywords     :", c["keywords"])
print("daily_count    :", ps.daily_count(state))
ps.mark_used(state, c["product_id"])
print("after mark_used: daily_count =", ps.daily_count(state))
print("rotation order :", [x["product_id"] for x in ps.candidates(state, jf)])

# a post that must FAIL the checks
bad = dict(post, id="bad-1", title="A post with no number at all",
           hashtags=["#a", "#b"], body="Read more at https://example.com")
print("\nbad post check :", ps.check_post(bad))
