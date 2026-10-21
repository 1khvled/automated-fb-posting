"""Re-point both bots at their own page and configure both pages.

The truth after the user reactivated the pages:
  1264009986803820  "Ethan Cole"                  -> ethan-cole-fb-bot  (English)
  1421089964411983  "سوق اليوم The Market Today" -> soq-alyoum-fb-bot  (Arabic)

Both were DEACTIVATED (Facebook's word for a disabled page), not deleted - a
deactivated page returns "Object does not exist" from the Graph API and 404s
to logged-out visitors, which is exactly what made them look gone.

The watcher had pointed the ethan bot at the Arabic page by mistake. This
fixes that, gives each repo its own page, and configures both pages with a
PAGE token (the user token returns #210 for page fields).
"""
import os, sys, json, subprocess, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv

V = "v26.0"
ETHAN = "1khvled/automated-fb-posting"
MARKET = "1khvled/market-today-automation"
LOCAL = {
    "ethan": Path(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot"),
    "market": Path(r"C:\Users\Abdelli\Documents\soq-alyoum-fb-bot"),
}
PAGES = {
    "ethan": {"id": "1264009986803820", "name": "Ethan Cole",
              "about": ("Finance + AI, explained without the noise. Markets, money "
                        "and machine intelligence - one read, one minute. "
                        "LEVEL UP YOUR SETUP."),
              "website": "https://ethancole.page", "category": "Finance"},
    "market": {"id": "1421089964411983", "name": "سوق اليوم The Market Today",
               "about": ("سوق اليوم - أخبار الأسواق.Require: نتابع لكم أهم ما يحدث في "
                         "الأسواق والآ有力.crypto والذكاء الاصطناعي. "
                         "MARKET TODAY - markets, money and machine intelligence, "
                         "in one minute."),
               "website": "https://market-today.page", "category": "Finance"},
}

load_dotenv(LOCAL["ethan"] / ".env", override=False)
UT = os.getenv("FB_USER_TOKEN", "").strip()


def g(path, params=None, tok=None):
    p = dict(params or {})
    p["access_token"] = tok or UT
    r = requests.get(f"https://graph.facebook.com/{V}{path}", params=p, timeout=25)
    try:
        return r.json()
    except Exception:
        return {"raw": r.text[:200]}


def p(path, body, tok):
    r = requests.post(f"https://graph.facebook.com/{V}{path}",
                      params={"access_token": tok}, json=body, timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text[:200]}


def set_secret(repo, name, value):
    r = subprocess.run(["gh", "secret", "set", name, "--repo", repo, "--body", value],
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()[:110]


def enable(repo, wf="fb-post.yml"):
    r = subprocess.run(["gh", "api", "-X", "PUT",
                        f"repos/{repo}/actions/workflows/{wf}/enable"],
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()[:110]


def trigger(repo, wf="fb-post.yml"):
    r = subprocess.run(["gh", "workflow", "run", wf, "--repo", repo],
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()[:110]


# ---------------------------------------------------------------- tokens
acc = g("/me/accounts", {"fields": "id,name,access_token,category,is_published"})
print("pages this token can manage:")
tokens = {}
for x in acc.get("data", []):
    print(f"   {x.get('id'):>18} | {x.get('name')!r:<34} | {x.get('category')} | fans?")
    tokens[x.get("id")] = x.get("access_token", "")

# ---------------------------------------------------------------- configure
for key, repo in (("ethan", ETHAN), ("market", MARKET)):
    cfg = PAGES[key]
    pid = cfg["id"]
    ptok = tokens.get(pid)
    print(f"\n=== {key.upper()} -> {repo} (page {pid}) ===")
    if not ptok:
        print("  no page token - skipping")
        continue
    ok = g(f"/{pid}", {"fields": "id,name"}, ptok)
    if "name" not in ok:
        print("  page token not usable:", json.dumps(ok)[:160])
        continue
    print(f"  page token ok: {ok.get('name')}")

    for f in ("about", "website", "category"):
        st, d = p(f"/{pid}", {f: cfg[f]}, ptok)
        print(f"  set {f:<9} -> {st} {'ok' if 'error' not in d else str(d.get('error'))[:80]}")

    # secrets
    for name, val in (("FB_PAGE_ID", pid), ("FB_PAGE_ACCESS_TOKEN", ptok),
                      ("FB_USER_TOKEN", UT)):
        good, msg = set_secret(repo, name, val)
        print(f"  secret {name:<22} -> {'set' if good else msg}")

    # local .env
    envp = LOCAL[key] / ".env"
    try:
        txt = envp.read_text(encoding="utf-8")
        import re
        txt = re.sub(r"(?m)^FB_PAGE_ID=.*$", f"FB_PAGE_ID={pid}", txt)
        txt = re.sub(r"(?m)^FB_PAGE_ACCESS_TOKEN=.*$", f"FB_PAGE_ACCESS_TOKEN={ptok}", txt)
        envp.write_text(txt, encoding="utf-8")
        print("  local .env updated")
    except Exception as e:  # noqa: BLE001
        print(f"  local .env: {e}")

    # page art (fetch what is already there so we can match it)
    art = g(f"/{pid}", {"fields": "cover,profile_picture"}, ptok)
    print("  existing art:", json.dumps(art, ensure_ascii=False)[:200])
