#!/usr/bin/env python3
"""Re-seed the Facebook credentials for a Page. One human login, then done.

THE PROBLEM (Oct 2026)
-----------------------
The posting bot and its self-heal both failed with:

    refresh: page_not_managed - the Facebook account behind FB_USER_TOKEN
    manages 1 other page(s) (816138634925735) but not our page

A Page token inherits the life of the user token that minted it. When the
Facebook profile that owned the Page lost admin rights (or the Page moved to
another profile), the Page token returns error 190 - "This Page access token
belongs to a Page that is not accessible" - and NOTHING can fix it from the
server side. Re-minting from the same user token reproduces the same dead
token. The only fix is one interactive login on the Facebook profile that
actually administers the Page.

THE FIX (about two minutes)
---------------------------
1. Open https://developers.facebook.com/tools/explorer
2. Log in with the Facebook PROFILE that administers the Page (this is the
   step people get wrong - it must be the profile with admin rights on the
   Page, not the one that created the App).
3. Get a User Access Token with these scopes:
       pages_show_list
       pages_manage_posts
       pages_read_engagement
       pages_manage_metadata
4. Paste it below (or pass it as --user-token).

The script then:
  * exchanges it for a long-lived user token
  * lists the Pages that token can actually manage
  * if the target Page is there: mints a Page token, stores both as GitHub
    secrets, re-enables the posting workflow, and verifies the whole chain
  * if it is not: tells you exactly which Pages that token manages, so you
    know which Facebook profile you are logged into

Never prints a token.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FB_API_VERSION = "v26.0"
DEFAULT_REPO = "1khvled/automated-fb-posting"
DEFAULT_PAGE = "1264009986803820"   # Ethan Cole
DEFAULT_WORKFLOW = "fb-post.yml"


def load_local_env() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    for p in ("../.env", ".env",
              r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot\.env"):
        if os.path.exists(p):
            load_dotenv(p, override=False)


def exchange(user_token: str, app_id: str, app_secret: str) -> str:
    r = requests.get(f"https://graph.facebook.com/{FB_API_VERSION}/oauth/access_token",
                     params={"grant_type": "fb_exchange_token",
                             "client_id": app_id,
                             "client_secret": app_secret,
                             "fb_exchange_token": user_token},
                     timeout=25)
    d = r.json() or {}
    if "access_token" not in d:
        raise RuntimeError(f"exchange failed: {json.dumps(d)[:250]}")
    return d["access_token"]


def managed_pages(user_token: str) -> list:
    r = requests.get(f"https://graph.facebook.com/{FB_API_VERSION}/me/accounts",
                     params={"access_token": user_token, "limit": 50,
                             "fields": "id,name,category,tasks"},
                     timeout=25)
    d = r.json() or {}
    if "error" in d:
        raise RuntimeError(f"/me/accounts failed: {json.dumps(d)[:250]}")
    return d.get("data", [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-token", default="")
    ap.add_argument("--page-id", default=DEFAULT_PAGE)
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    ap.add_argument("--dry-run", action="store_true",
                    help="check only, do not touch the GitHub secrets")
    args = ap.parse_args()

    load_local_env()
    app_id = os.getenv("FB_APP_ID", "").strip()
    app_secret = os.getenv("FB_APP_SECRET", "").strip()
    if not (app_id and app_secret):
        print("FB_APP_ID / FB_APP_SECRET not set (put them in .env)", file=sys.stderr)
        return 2

    print("=" * 70)
    print("  RE-SEED THE FACEBOOK CREDENTIALS")
    print("=" * 70)
    print("Get a User Access Token from")
    print("  https://developers.facebook.com/tools/explorer")
    print("scopes: pages_show_list, pages_manage_posts, pages_read_engagement,")
    print("        pages_manage_metadata")
    print("Log in with the Facebook PROFILE that administers the Page.")
    print("-" * 70)

    token = args.user_token or getpass.getpass("Paste the user token: ").strip()
    if not token:
        print("no token given", file=sys.stderr)
        return 2

    try:
        fresh = exchange(token, app_id, app_secret)
    except Exception as e:  # noqa: BLE001
        print(f"\nFAILED to exchange the token: {e}")
        print("The token is probably expired or was copied with the '...' suffix.")
        return 3

    try:
        pages = managed_pages(fresh)
    except Exception as e:  # noqa: BLE001
        print(f"\nFAILED to list pages: {e}")
        return 3

    print(f"\nThis token administers {len(pages)} page(s):")
    for p in pages:
        mark = "  <-- TARGET" if str(p.get("id")) == str(args.page_id) else ""
        print(f"   {p.get('id'):>18}  {p.get('name')}{mark}")

    target = next((p for p in pages if str(p.get("id")) == str(args.page_id)), None)
    if not target:
        print("\n" + "=" * 70)
        print("  THE TARGET PAGE IS NOT IN THAT LIST.")
        print("=" * 70)
        print("You are logged into the wrong Facebook profile, or the profile")
        print("no longer has admin rights on the Page.")
        print("\nWhat to do:")
        print("  1. Open the Page in a browser while logged into the profile that")
        print("     owns it (Page settings -> Page access -> your profile).")
        print("  2. Give THAT profile full control of the Page.")
        print("  3. Log into the Graph API Explorer with the SAME profile and")
        print("     repeat this script.")
        if len(pages) == 1:
            print(f"\n(For reference, the only page this token can see is "
                  f"{pages[0].get('name')} - {pages[0].get('id')}. That is the")
            print(" AZTech Store page, not the Ethan Cole page.)")
        return 4

    page_token = target.get("access_token")
    if not page_token:
        print("the target page returned no page token", file=sys.stderr)
        return 4

    chk = requests.get(f"https://graph.facebook.com/{FB_API_VERSION}/{args.page_id}",
                        params={"fields": "id,name,followers_count",
                                "access_token": page_token}, timeout=25).json()
    if "name" not in (chk or {}):
        print(f"the minted page token is not usable: {json.dumps(chk)[:200]}")
        return 4
    print(f"\nOK. The Page token works: {chk.get('name')} "
          f"({chk.get('followers_count')} followers)")

    if args.dry_run:
        print("\n--dry-run: nothing was written to GitHub.")
        return 0

    for name, value in (("FB_USER_TOKEN", fresh),
                        ("FB_PAGE_ACCESS_TOKEN", page_token)):
        r = subprocess.run(["gh", "secret", "set", name, "--repo", args.repo,
                            "--body", value], capture_output=True, text=True)
        print(f"  secret {name}: {'ok' if r.returncode == 0 else r.stderr[:120]}")

    r = subprocess.run(["gh", "api", "-X", "PUT",
                        f"repos/{args.repo}/actions/workflows/{args.workflow}/enable"],
                       capture_output=True, text=True)
    print(f"  {args.workflow}: {'enabled' if r.returncode == 0 else r.stderr[:160]}")

    r = subprocess.run(["gh", "workflow", "run", args.workflow, "--repo", args.repo],
                       capture_output=True, text=True)
    print(f"  test run: {'triggered' if r.returncode == 0 else r.stderr[:160]}")
    print("\nDone. Watch the run here:")
    print(f"  https://github.com/{args.repo}/actions/workflows/{args.workflow}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
