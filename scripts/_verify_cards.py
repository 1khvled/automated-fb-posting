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
    f = requests.get(f"https://graph.facebook.com/v26.0/{pid}/feed",
                     params={"limit": 2, "fields": "id,created_time,message,"
                             "full_picture,permalink_url", "access_token": pt},
                     timeout=25).json()
    rows = f.get("data") or []
    print("=" * 70)
    print(x.get("name"))
    for p in rows:
        print("  ", p.get("created_time"), "|", p.get("permalink_url"))
        print("     ", (p.get("message") or "")[:110].replace("\n", " / "))
        fp = p.get("full_picture")
        if fp:
            fn = OUT / f"post_{pid}_{p['id'].split('_')[-1]}.jpg"
            try:
                fn.write_bytes(requests.get(fp, timeout=60).content)
                from PIL import Image
                print(f"      IMAGE -> {fn.name} {Image.open(fn).size}")
            except Exception as e:  # noqa: BLE001
                print("      image fetch failed:", e)
        else:
            print("      (no image - text post)")
