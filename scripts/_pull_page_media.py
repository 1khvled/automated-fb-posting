import os, sys, json, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()
ut = os.getenv("FB_USER_TOKEN", "").strip()
pid = "816138634925735"
out = Path("_page_media")
out.mkdir(exist_ok=True)

pt = requests.get("https://graph.facebook.com/v26.0/me/accounts",
                   params={"access_token": ut}, timeout=25).json()["data"][0]["access_token"]

ph = requests.get(f"https://graph.facebook.com/v26.0/{pid}/photos",
                  params={"limit": 50, "fields": "id,created_time,name,images",
                          "access_token": pt}, timeout=25).json()
print("photos:", len(ph.get("data") or []))
for x in ph.get("data") or []:
    imgs = x.get("images") or []
    if not imgs:
        continue
    # the API returns either plain URL strings or {height,width,source:{url}}
    urls = []
    for i in imgs:
        if isinstance(i, str):
            urls.append(i)
        elif isinstance(i, dict):
            s = i.get("source")
            if isinstance(s, str):
                urls.append(s)
            elif isinstance(s, dict) and s.get("url"):
                urls.append(s["url"])
    if not urls:
        continue
    src = urls[0]
    fn = out / f"photo_{x['id']}.jpg"
    r = requests.get(src, timeout=40, headers={"User-Agent": "Mozilla/5.0"})
    fn.write_bytes(r.content)
    print(f"  {x['id']} {x.get('created_time')} -> {fn.name} ({len(r.content)} bytes) {src[:80]}")

feed = requests.get(f"https://graph.facebook.com/v26.0/{pid}/feed",
                    params={"limit": 20,
                            "fields": "id,created_time,message,full_picture,permalink_url",
                            "access_token": pt}, timeout=25).json()
print("\n== full feed ==")
for x in feed.get("data") or []:
    print("-" * 70)
    print(x.get("created_time"), "|", x.get("permalink_url"))
    print(x.get("message"))

print("\n== page media ==")
for x in feed.get("data") or []:
    if x.get("full_picture"):
        print(" ", x["id"], x["full_picture"][:100])
