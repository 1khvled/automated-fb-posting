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
    print("=" * 74)
    print(x.get("name"), pid)
    f = requests.get(f"https://graph.facebook.com/v26.0/{pid}/feed",
                     params={"limit": 8, "fields": "id,created_time,message,"
                             "full_picture,permalink_url", "access_token": pt},
                     timeout=30).json()
    for i, p in enumerate(f.get("data") or []):
        fp = p.get("full_picture")
        fn = OUT / f"cur_{pid}_{i}.jpg"
        size = 0
        if fp:
            try:
                fn.write_bytes(requests.get(fp, timeout=60).content)
                size = fn.stat().st_size
            except Exception:
                pass
        msg = (p.get("message") or "").replace("\n", " / ")[:58]
        print(f"  {i} {p.get('created_time')} img={size:>7}B  {msg}")
        print(f"      {fn.name if fp else '(no image)'}")
