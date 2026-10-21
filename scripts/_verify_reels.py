import os, sys, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot\.env")
UT = os.getenv("FB_USER_TOKEN", "").strip()
acc = requests.get("https://graph.facebook.com/v26.0/me/accounts",
                   params={"fields": "id,name,access_token", "access_token": UT},
                   timeout=25).json().get("data", [])
OUT = Path(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot\_art")
OUT.mkdir(exist_ok=True)

for x in acc:
    pid = x.get("id")
    if pid not in ("1264009986803820", "1421089964411983"):
        continue
    pt = x.get("access_token")
    print("=" * 70)
    print(x.get("name"))
    # the newest video
    v = requests.get(f"https://graph.facebook.com/v26.0/{pid}/videos",
                     params={"limit": 2, "fields": "id,created_time,title,"
                             "description,permalink_url,source", "access_token": pt},
                     timeout=30).json()
    for item in (v.get("data") or [])[:2]:
        print("  video", item.get("id"), item.get("created_time"))
        print("    ", (item.get("description") or "")[:100].replace("\n", " / "))
        src = item.get("source") or ""
        if src:
            fn = OUT / f"video_{pid}_{item.get('id')}.mp4"
            try:
                fn.write_bytes(requests.get(src, timeout=120).content)
                from PIL import Image
                import subprocess
                print(f"     downloaded {fn.stat().st_size:,} bytes -> {fn.name}")
            except Exception as e:  # noqa: BLE001
                print("     download failed:", e)
    # the newest feed post
    f = requests.get(f"https://graph.facebook.com/v26.0/{pid}/feed",
                     params={"limit": 2, "fields": "id,created_time,message,permalink_url",
                             "access_token": pt}, timeout=25).json()
    for p in (f.get("data") or [])[:2]:
        print("  post ", p.get("id"), p.get("created_time"),
              "|", (p.get("message") or "")[:70].replace("\n", " / "))
