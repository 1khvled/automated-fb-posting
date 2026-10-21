import os, sys, json, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv()
ut = os.getenv("FB_USER_TOKEN", "").strip()


def g(url, p):
    p["access_token"] = ut
    r = requests.get(url, params=p, timeout=25)
    return r.json()


bl = g("https://graph.facebook.com/v26.0/me/businesses",
       {"limit": 20, "fields": "id,name"}).get("data", [])
print("businesses:", len(bl))
allpages = []
for b in bl:
    bid = b["id"]
    d = g(f"https://graph.facebook.com/v26.0/{bid}/owned_facebook_accounts",
          {"limit": 50, "fields": "id,name,category,followers_count,access"})
    acc = d.get("data", [])
    print("BUSINESS %s (%s) -> %d page(s)" % (b["name"], bid, len(acc)))
    for a in acc:
        print("    %s | %s | %s | followers %s" % (
            a.get("id"), a.get("name"), a.get("category"), a.get("followers_count")))
        allpages.append(a)
    if not acc:
        print("     err:", json.dumps(d, ensure_ascii=False)[:200])
    # also pages where the user has tasks but doesn't own
    d2 = g(f"https://graph.facebook.com/v26.0/{bid}/facebook_accounts",
           {"limit": 50, "fields": "id,name,category,followers_count"})
    acc2 = d2.get("data", [])
    if len(acc2) != len(acc):
        print("   (+ all accounts w/ tasks: %d)" % len(acc2))
        for a in acc2:
            print("      %s | %s | %s | followers %s" % (
                a.get("id"), a.get("name"), a.get("category"), a.get("followers_count")))
            allpages.append(a)

print()
print("TOTAL distinct pages visible:", len(allpages))
for a in allpages:
    print("  ", a.get("id"), "|", a.get("name"))
