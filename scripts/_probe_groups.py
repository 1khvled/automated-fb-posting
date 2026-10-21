"""Can we auto-share into Facebook Groups again?

The old Groups API (`POST /{group-id}/feed` with publish_to_groups) is
deprecated for new apps. But sharing a PAGE POST into groups is a
different, still-supported endpoint:

    POST /{page-id}/sharedposts
      target_id : the group id
      message   : the comment text
      link      : the permalink of the page post (or photo_id)

This script proves three things:
  1. a group NAME can be resolved to its numeric id from the public URL
     (facebook.com/groups/<name> redirects to /groups/<id>/) -- no login
     needed for public groups
  2. the sharedposts endpoint is recognised by the API
  3. what the API says when the page is not a member of the group, so we
     know the difference between "no permission" and "wrong endpoint"
"""
import os, re, sys, json, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv

load_dotenv(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot\.env")
UT = os.getenv("FB_USER_TOKEN", "").strip()
acc = requests.get("https://graph.facebook.com/v26.0/me/accounts",
                   params={"fields": "id,name,access_token", "access_token": UT},
                   timeout=25).json().get("data", [])
PAGE = {x["id"]: x for x in acc}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def resolve_group(name: str) -> str:
    """Group name -> numeric id, from the public redirect. No login."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "", name)
    for url in (f"https://www.facebook.com/groups/{slug}",
                f"https://m.facebook.com/groups/{slug}"):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=25,
                             allow_redirects=True)
            for m in re.finditer(r"/groups/(\d{6,})", r.text + " " + r.url):
                return m.group(1)
            m = re.search(r"groupId[\"':= ]+(\d{6,})", r.text)
            if m:
                return m.group(1)
        except Exception as e:  # noqa: BLE001
            print(f"   resolve error: {type(e).__name__}")
    return ""


print("=" * 70)
print("1) NAME -> GROUP ID (public redirect, no login)")
for nm in ("Bitcoin", "investing", "StockMarket"):
    gid = resolve_group(nm)
    print(f"   {nm!r:<14} -> {gid or 'not resolved'}")

print()
print("=" * 70)
print("2) is /{page-id}/sharedposts a live endpoint?")
for pid, label in (("1264009986803820", "Ethan Cole"),
                    ("1421089964411983", "Market Today")):
    pt = PAGE[pid]["access_token"]
    # a read attempt tells us whether the edge exists
    r = requests.get(f"https://graph.facebook.com/v26.0/{pid}/sharedposts",
                     params={"access_token": pt, "limit": 1}, timeout=25)
    try:
        d = r.json()
    except Exception:
        d = {}
    err = (d.get("error") or {}).get("message", "")
    print(f"   {label:<14} GET sharedposts -> HTTP {r.status_code}")
    print(f"      {err[:150] if err else ('OK, edge exists' if 'data' in d else str(d)[:120])}")

print()
print("=" *70)
print("3) try an actual share into a group (expect a membership/permission error,")
print("   which is what proves the endpoint is right)")
gid = resolve_group("Bitcoin")
for pid, label in (("1264009986803820", "Ethan Cole"),):
    pt = PAGE[pid]["access_token"]
    # find a recent post of this page to share
    f = requests.get(f"https://graph.facebook.com/v26.0/{pid}/feed",
                     params={"limit": 1, "fields": "id,permalink_url",
                             "access_token": pt}, timeout=25).json()
    post = (f.get("data") or [{}])[0]
    link = post.get("permalink_url")
    print(f"   {label}: sharing post {post.get('id')}")
    if not gid:
        print("      (no group id resolved, trying the endpoint with a fake id to see the error)")
        gid = "123456789012345"
    r = requests.post(f"https://graph.facebook.com/v26.0/{pid}/sharedposts",
                      params={"access_token": pt},
                      json={"target_id": gid, "message": "test share",
                            "link": link} if link else
                           {"target_id": gid, "message": "test share"},
                      timeout=25)
    try:
        d = r.json()
    except Exception:
        d = {"raw": r.text[:200]}
    print(f"      HTTP {r.status_code}: {json.dumps(d, ensure_ascii=False)[:320]}")
