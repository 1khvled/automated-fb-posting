#!/usr/bin/env python3
"""Monthly token self-heal: keeps the Page token undying without logins.

Chain: FB_USER_TOKEN (long-lived, 60d) --fb_exchange--> fresh user token
--> /me/accounts --> fresh Page token (no expiry when minted from a
long-lived user token). The workflow stores both back as secrets, so the
loop sustains itself as long as it runs at least once every 60 days.

One-time manual bootstrap (README section 6) provides the first
FB_USER_TOKEN. If that token is already fully dead, this script exits 4
and a human must log in once to re-seed it.

Env: FB_APP_ID, FB_APP_SECRET, FB_USER_TOKEN, FB_PAGE_ID.
Writes page_token=/user_token= lines to $GITHUB_OUTPUT (never stdout).
"""
import json
import os
import sys
import time

import requests

FB_API_VERSION = "v26.0"
REFRESH_BEFORE_DAYS = 30


def debug_token(input_token: str, app_id: str, app_secret: str) -> dict:
    r = requests.get(
        f"https://graph.facebook.com/{FB_API_VERSION}/debug_token",
        params={"input_token": input_token,
                "access_token": f"{app_id}|{app_secret}"},
        timeout=20)
    return r.json().get("data", {})


def needs_refresh(debug: dict) -> bool:
    """True when the token is dead or expires within REFRESH_BEFORE_DAYS."""
    if not debug.get("is_valid"):
        return True
    exp = debug.get("expires_at", 0)
    if not exp:  # 0 = never expires -> healthy
        return False
    return (exp - time.time()) < REFRESH_BEFORE_DAYS * 86400


def exchange_user_token(user_token: str, app_id: str, app_secret: str) -> str:
    r = requests.get(
        f"https://graph.facebook.com/{FB_API_VERSION}/oauth/access_token",
        params={"grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": user_token},
        timeout=20)
    d = r.json()
    if "access_token" not in d:
        raise RuntimeError(f"exchange failed: {json.dumps(d)[:200]}")
    return d["access_token"]


def page_token_for(user_token: str, page_id: str) -> str:
    r = requests.get(
        f"https://graph.facebook.com/{FB_API_VERSION}/me/accounts",
        params={"access_token": user_token}, timeout=20)
    d = r.json()
    for pg in d.get("data", []):
        if str(pg.get("id")) == str(page_id) and pg.get("access_token"):
            return pg["access_token"]
    raise RuntimeError(f"page {page_id} not in /me/accounts: "
                       f"{json.dumps(d)[:200]}")


def emit(name: str, value: str):
    out = os.getenv("GITHUB_OUTPUT")
    if not out:
        raise RuntimeError("GITHUB_OUTPUT not set (run inside Actions)")
    with open(out, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def main() -> int:
    app_id = os.getenv("FB_APP_ID", "").strip()
    app_secret = os.getenv("FB_APP_SECRET", "").strip()
    user_token = os.getenv("FB_USER_TOKEN", "").strip()
    page_id = os.getenv("FB_PAGE_ID", "").strip()
    page_token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    if not all([app_id, app_secret, user_token, page_id]):
        print("refresh: missing FB_APP_ID / FB_APP_SECRET / FB_USER_TOKEN / "
              "FB_PAGE_ID")
        return 2
    if page_token:
        try:
            if not needs_refresh(debug_token(page_token, app_id, app_secret)):
                print("refresh: page token healthy, nothing to do")
                return 0
        except Exception as ex:
            print(f"refresh: debug failed ({ex}), attempting renewal")
    else:
        print("refresh: no page token set, minting fresh chain")
    try:
        fresh_user = exchange_user_token(user_token, app_id, app_secret)
    except Exception as ex:
        print(f"refresh: user token dead, human login needed once "
              f"(README 3): {ex}")
        return 4
    fresh_page = page_token_for(fresh_user, page_id)
    emit("user_token", fresh_user)
    emit("page_token", fresh_page)
    print("refresh: fresh tokens minted, workflow will store them as secrets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
