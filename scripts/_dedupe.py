import os, sys, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot\.env")
UT = os.getenv("FB_USER_TOKEN", "").strip()

acc = requests.get("https://graph.facebook.com/v26.0/me/accounts",
                   params={"fields": "id,name,access_token", "access_token": UT},
                   timeout=25).json().get("data", [])
T = {x["id"]: x["access_token"] for x in acc}

for pid in ("1264009986803820", "1421089964411983"):
    pt = T.get(pid)
    if not pt:
        continue
    f = requests.get(f"https://graph.facebook.com/v26.0/{pid}/feed",
                     params={"limit": 8, "fields": "id,created_time,message",
                             "access_token": pt}, timeout=25).json()
    rows = f.get("data") or []
    print("=" * 66)
    print(pid)
    # find near-duplicates posted within 5 minutes
    seen = []
    for p in rows:
        msg = (p.get("message") or "")
        key = " ".join(msg.split()[:9]).lower()
        dup = None
        for s in seen:
            if s["key"] and (key[:70] == s["key"][:70]):
                dup = s
                break
        if dup:
            r = requests.delete(f"https://graph.facebook.com/v26.0/{p['id']}",
                                params={"access_token": pt}, timeout=30)
            print(f"   DELETED duplicate {p['id']} "
                  f"({p.get('created_time')}) -> {r.status_code}")
            continue
        seen.append({"key": key, "id": p["id"]})
    for p in rows[:4]:
        c = ""
        try:
            cm = requests.get(f"https://graph.facebook.com/v26.0/{p['id']}/comments",
                              params={"limit": 20, "fields": "id,message",
                                      "access_token": pt}, timeout=20).json()
            c = str(len(cm.get("data") or []))
        except Exception:
            c = "?"
        print(f"   {p.get('created_time')} | comments {c} | "
              f"{(p.get('message') or '')[:72].replace(chr(10),' / ')}")
