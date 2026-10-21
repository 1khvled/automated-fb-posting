import os, sys, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot\.env")
UT = os.getenv("FB_USER_TOKEN", "").strip()
acc = requests.get("https://graph.facebook.com/v26.0/me/accounts",
                   params={"fields": "id,name,access_token", "access_token": UT},
                   timeout=25).json().get("data", [])
T = {x["id"]: x["access_token"] for x in acc}

# same story posted twice: "JPMorgan ... SpaceX ... $500" at 16:06:40 and 16:07:13
pt = T["1264009986803820"]
f = requests.get("https://graph.facebook.com/v26.0/1264009986803820/feed",
                 params={"limit": 8, "fields": "id,created_time,message",
                         "access_token": pt}, timeout=25).json()
rows = f.get("data") or []
for p in rows:
    m = (p.get("message") or "")
    if "SPCX" in m and "500" in m and p.get("created_time", "").startswith("2026-10-21T16:07"):
        r = requests.delete(f"https://graph.facebook.com/v26.0/{p['id']}",
                            params={"access_token": pt}, timeout=30)
        print(f"deleted duplicate {p['id']} -> {r.status_code}")
print("done")
