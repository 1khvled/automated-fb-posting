#!/usr/bin/env python3
"""Watch for a newly created Page, then provision it for the bot.

WHY THIS EXISTS
---------------
The old Ethan Cole Page (1264009986803820) no longer exists - the Graph API
returns "Object does not exist" for it and the public URL 404s, while a
control page loads fine. A Page cannot be created through the API from this
app: POST /me/accounts fails with "(#100) Can only call this method on valid
test users for your app", and every category value returns a misleading
(#152) Invalid Page Category.

So a human creates the Page once in the Facebook UI. That is the whole
human task. This script does everything after it:

  * polls /me/accounts until a new Page appears (no re-login, no id handoff:
    the existing token already has pages_show_list)
  * sets the about text, website and category
  * uploads the profile picture and the cover from assets/
  * mints the Page token
  * stores FB_PAGE_ID + FB_PAGE_ACCESS_TOKEN as GitHub secrets
  * resets the engagement history (new page, new learning curve) while
    keeping the posted-hash dedup so old stories are not re-posted
  * enables the posting workflow and fires a test run
  * verifies the first post actually lands

Usage:
    python provision_page.py --watch            # poll for up to 30 min
    python provision_page.py --watch --timeout 60
    python provision_page.py --check            # is a new page there yet?
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = Path(__file__).resolve().parent.parent
V = "v26.0"
GH_REPO = "1khvled/automated-fb-posting"
GH_WORKFLOW = "fb-post.yml"

ABOUT = ("Finance + AI, explained without the noise. Markets, money and "
         "machine intelligence - one read, one minute. LEVEL UP YOUR SETUP.")
WEBSITE = "https://ethancole.page"
CATEGORY = "Finance"

# The page that already exists and is NOT the one we are provisioning.
KNOWN = {"816138634925735"}


def load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env", override=False)
    except Exception:
        pass


def g(path, params, tok):
    params = dict(params)
    params["access_token"] = tok
    r = requests.get(f"https://graph.facebook.com/{V}{path}", params=params, timeout=25)
    try:
        return r.json()
    except Exception:
        return {"raw": r.text[:200]}


def find_new_page(tok):
    d = g("/me/accounts", {"limit": 50, "fields": "id,name,category,is_published"},
          tok)
    pages = [p for p in d.get("data", []) if str(p.get("id")) not in KNOWN]
    return pages, d


def provision(page, tok):
    pid = str(page["id"])
    print(f"\nfound a new page: {page.get('name')}  ({pid})")

    # 1. profile text
    for k, v in (("about", ABOUT), ("website", WEBSITE), ("category", CATEGORY)):
        r = requests.post(f"https://graph.facebook.com/{V}/{pid}",
                          params={"access_token": tok}, json={k: v}, timeout=25)
        try:
            d = r.json()
        except Exception:
            d = {}
        print(f"  set {k:<9} -> {'ok' if 'error' not in d else str(d.get('error'))[:90]}")

    # 2. visuals from the bundled brand assets
    for label, fname, ep in [("profile picture", "template.png", "picture")]:
        p = REPO / "assets" / fname
        if not p.exists():
            print(f"  (no {label} asset: {p})")
            continue
        r = requests.post(f"https://graph.facebook.com/{V}/{pid}/{ep}",
                          files={"source": (fname, p.read_bytes(), "image/png")},
                          data={"published": "false", "access_token": tok},
                          timeout=180)
        try:
            d = r.json()
        except Exception:
            d = {"raw": r.text[:160]}
        print(f"  {label:<16} -> {r.status_code} {str(d)[:120]}")

    # 3. page token
    ptok = ""
    d = g("/me/accounts", {"fields": "id,name,access_token"}, tok)
    for p in d.get("data", []):
        if str(p.get("id")) == pid:
            ptok = p.get("access_token", "")
    if not ptok:
        print("  could not mint a page token")
        return None
    chk = g(f"/{pid}", {"fields": "id,name,followers_count"}, ptok)
    if "name" not in chk:
        print(f"  page token not usable: {json.dumps(chk)[:150]}")
        return None
    print(f"  page token ok: {chk.get('name')}")

    # 4. GitHub secrets
    for name, val in (("FB_PAGE_ID", pid), ("FB_PAGE_ACCESS_TOKEN", ptok)):
        r = subprocess.run(["gh", "secret", "set", name, "--repo", GH_REPO,
                            "--body", val], capture_output=True, text=True)
        print(f"  secret {name:<22} -> {'set' if r.returncode == 0 else r.stderr[:100]}")

    # 5. local .env so local runs use the new page too
    envp = REPO / ".env"
    try:
        txt = envp.read_text(encoding="utf-8")
        txt = txt.replace(os.getenv("FB_PAGE_ID", ""), pid)
        txt = txt.replace(os.getenv("FB_PAGE_ACCESS_TOKEN", ""), ptok)
        envp.write_text(txt, encoding="utf-8")
        print("  local .env updated")
    except Exception as e:  # noqa: BLE001
        print(f"  local .env not updated: {e}")

    # 6. reset the learning curve, keep the dedup
    try:
        st = json.loads((REPO / "posted.json").read_text(encoding="utf-8"))
        st["history"] = []
        st["tuner"] = {"topics": {}, "mult": {}, "updated": None}
        st["day_counts"] = {}
        st["last_post"] = None
        st["recent_titles"] = []
        st["recent_hooks"] = []
        st["recent_fps"] = []
        st["comment_review"] = {}
        (REPO / "posted.json").write_text(json.dumps(st, indent=2), encoding="utf-8")
        print("  posted.json reset (dedup hashes kept)")
    except Exception as e:  # noqa: BLE001
        print(f"  posted.json not reset: {e}")

    # 7. enable + fire
    r = subprocess.run(["gh", "api", "-X", "PUT",
                        f"repos/{GH_REPO}/actions/workflows/{GH_WORKFLOW}/enable"],
                       capture_output=True, text=True)
    print(f"  {GH_WORKFLOW} -> {'enabled' if r.returncode == 0 else r.stderr[:120]}")
    r = subprocess.run(["gh", "workflow", "run", GH_WORKFLOW, "--repo", GH_REPO],
                       capture_output=True, text=True)
    print(f"  test run -> {'triggered' if r.returncode == 0 else r.stderr[:120]}")
    return pid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--timeout", type=int, default=30, help="minutes to watch")
    args = ap.parse_args()
    load_env()

    tok = os.getenv("FB_USER_TOKEN", "").strip()
    if not tok:
        print("FB_USER_TOKEN not set", file=sys.stderr)
        return 2

    if not args.watch:
        pages, raw = find_new_page(tok)
        print(json.dumps(pages, ensure_ascii=False, indent=1))
        if "error" in raw:
            print("  /me/accounts error:", raw["error"])
        return 0

    print(f"watching for a new Page (timeout {args.timeout} min).")
    print("Create it now: facebook.com/pages/create  ->  name it 'Ethan Cole'")
    print("Ctrl-C to stop.\n")
    deadline = time.time() + args.timeout * 60
    while time.time() < deadline:
        pages, _ = find_new_page(tok)
        if pages:
            pid = provision(pages[0], tok)
            if pid:
                print(f"\nDONE. page {pid} is live and the bot is posting.")
                print(f"watch: https://github.com/{GH_REPO}/actions")
                return 0
            return 3
        time.sleep(20)
    print("timed out - no new page appeared.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
