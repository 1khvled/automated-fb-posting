"""Live test of the growth engine against the real pages.

Posts a seed comment on the latest post of each page and sends the share
kit to Telegram. Proves the whole loop end to end.
"""
import os, sys, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import growth

load_dotenv(HERE.parent / ".env", override=False)
UT = os.getenv("FB_USER_TOKEN", "").strip()
acc = requests.get("https://graph.facebook.com/v26.0/me/accounts",
                   params={"fields": "id,name,access_token", "access_token": UT},
                   timeout=25).json().get("data", [])
T = {x["id"]: x.get("access_token", "") for x in acc}

Q = {"1264009986803820": "Where does this sit in your portfolio right now?",
     "1421089964411983": "وين هاد الخبر من رايك في استثمارتك دابا؟"}

for pid in ("1264009986803820", "1421089964411983"):
    pt = T.get(pid)
    if not pt:
        print(pid, "-> no token")
        continue
    os.environ["FB_PAGE_ID"] = pid
    os.environ["FB_PAGE_ACCESS_TOKEN"] = pt
    f = requests.get(f"https://graph.facebook.com/v26.0/{pid}/feed",
                     params={"limit": 2, "fields": "id,created_time,message",
                             "access_token": pt}, timeout=25).json()
    rows = f.get("data") or []
    if not rows:
        print(pid, "-> no posts")
        continue
    p = rows[0]
    print("=" * 66)
    print(pid, "|", p.get("created_time"))
    print("  post:", (p.get("message") or "")[:80].replace("\n", " / "))
    existing = requests.get(f"https://graph.facebook.com/v26.0/{p['id']}/comments",
                            params={"limit": 20, "fields": "id,message",
                                    "access_token": pt}, timeout=20).json()
    print("  comments before:", len(existing.get("data") or []))
    cid = growth.post_seed_comment(p["id"], Q[pid])
    print("  seed comment id:", cid or "(FAILED)")
    after = requests.get(f"https://graph.facebook.com/v26.0/{p['id']}/comments",
                         params={"limit": 20, "fields": "id,message",
                                 "access_token": pt}, timeout=20).json()
    print("  comments after :", len(after.get("data") or []))
    for c in (after.get("data") or []):
        print("     >", (c.get("message") or "")[:90])

# the share kit to Telegram
variants = growth.share_variants(
    "JPMorgan doubles its SpaceX price target to $500",
    "JUST IN: JPMorgan just DOUBLED its SpaceX price target to $500.\n"
    "Old target: $240\nNew target: $500\nIncrease: +108%",
    ["stocks", "ai"],
    "Full breakdown on the page - link below.")
url = "https://www.facebook.com/1264009986803820/posts/122126708889472689"
msg = growth.format_share_kit("JPMorgan doubles its SpaceX price target to $500",
                               url, variants, "en")
print("=" * 66)
print("TELEGRAM PAYLOAD ->", "sent" if growth._telegram(msg) else "FAILED")
print(msg[:900])
