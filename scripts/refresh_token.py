#!/usr/bin/env python3
"""Token self-heal: keeps the Page token alive without human logins.

Chain: FB_USER_TOKEN (long-lived) --fb_exchange--> fresh user token
--> /me/accounts --> fresh Page token. Both are stored back as secrets by
the workflow, so the loop sustains itself as long as it runs daily.

Two hard-won rules (Oct 2026 outage: 212 consecutive dead runs, 2 days
dark on both pages):

1) NEVER trust expires_at == 0 ("never expires") for a PAGE or USER token.
   Facebook reported 0 for our page token, the old check said "healthy,
   nothing to do", and the token was dead 18 days later. Unknown expiry
   now means "renew" - re-minting daily is cheap, being dark is not.

2) A token that cannot SEE our page cannot heal it. /me/accounts must
   contain our page id; if it does not, the user token belongs to a
   different Facebook account and a human must re-seed it (exit 4).

Exit codes: 0 = tokens minted (workflow stores them) or already healthy,
2 = missing env, 4 = human login needed, 5 = transient Graph error.
"""
import json
import os
import sys
import time

import requests

FB_API_VERSION = "v26.0"
REFRESH_BEFORE_DAYS = 30


class PageNotManaged(RuntimeError):
    """The user token's account does not administer our page."""

    def __init__(self, managed):
        self.managed = managed
        super().__init__("page not managed by this user token")


def _out(name, value):
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def _reason(code, message):
    """Record why we stopped, one line, no quotes (shell-safe)."""
    flat = " ".join(str(message).split())[:380]
    print(f"refresh: {code} - {flat}")
    _out("reason", code)
    _out("message", flat)


def debug_token(input_token: str, app_id: str, app_secret: str) -> dict:
    try:
        r = requests.get(
            f"https://graph.facebook.com/{FB_API_VERSION}/debug_token",
            params={"input_token": input_token,
                    "access_token": f"{app_id}|{app_secret}"},
            timeout=20)
        return (r.json() or {}).get("data", {}) or {}
    except Exception:
        return {}


def token_state(debug: dict):
    """-> (is_valid, days_until_expiry or None when unknown)."""
    valid = bool(debug.get("is_valid"))
    exp = debug.get("expires_at") or 0
    if not exp:
        return valid, None
    return valid, (int(exp) - time.time()) / 86400.0


def exchange_user_token(user_token: str, app_id: str, app_secret: str) -> str:
    r = requests.get(
        f"https://graph.facebook.com/{FB_API_VERSION}/oauth/access_token",
        params={"grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": user_token},
        timeout=20)
    d = r.json() or {}
    if "access_token" not in d:
        raise RuntimeError(f"exchange failed: {json.dumps(d)[:200]}")
    return d["access_token"]


def page_token_for(user_token: str, page_id: str):
    r = requests.get(
        f"https://graph.facebook.com/{FB_API_VERSION}/me/accounts",
        params={"access_token": user_token}, timeout=20)
    d = r.json() or {}
    if "error" in d:
        raise RuntimeError(f"/me/accounts error: {json.dumps(d)[:200]}")
    managed = []
    for pg in d.get("data", []):
        managed.append(str(pg.get("id")))
        if str(pg.get("id")) == str(page_id) and pg.get("access_token"):
            return pg["access_token"], managed
    raise PageNotManaged(managed)


def verify_page_token(page_token: str, page_id: str):
    r = requests.get(
        f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}",
        params={"access_token": page_token, "fields": "id,name"}, timeout=20)
    d = r.json() or {}
    return ("name" in d), d


def main() -> int:
    app_id = os.getenv("FB_APP_ID", "").strip()
    app_secret = os.getenv("FB_APP_SECRET", "").strip()
    user_token = os.getenv("FB_USER_TOKEN", "").strip()
    page_id = os.getenv("FB_PAGE_ID", "").strip()
    page_token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    if not all([app_id, app_secret, user_token, page_id]):
        _reason("missing_env",
                "missing FB_APP_ID / FB_APP_SECRET / FB_USER_TOKEN / "
                "FB_PAGE_ID")
        return 2

    # 1. the user token must be alive, else a human has to log in once
    u_valid, u_days = token_state(debug_token(user_token, app_id, app_secret))
    if not u_valid:
        _reason("user_token_dead",
                "FB_USER_TOKEN is invalid or expired - one human login is "
                "needed (README section 3), then the loop sustains itself")
        return 4

    # 2. page token health. Unknown expiry counts as unhealthy.
    if page_token:
        p_valid, p_days = token_state(
            debug_token(page_token, app_id, app_secret))
    else:
        p_valid, p_days = False, None
    page_ok = p_valid and p_days is not None and p_days > REFRESH_BEFORE_DAYS
    user_ok = u_days is not None and u_days > REFRESH_BEFORE_DAYS
    if page_ok and user_ok:
        print("refresh: page token healthy and expiry known - nothing to do")
        _out("reason", "healthy")
        return 0

    # 3. re-mint the chain
    try:
        fresh_user = exchange_user_token(user_token, app_id, app_secret)
    except Exception as ex:
        _reason("user_token_dead",
                f"user token exchange failed - human login needed: {ex}")
        return 4
    try:
        fresh_page, managed = page_token_for(fresh_user, page_id)
    except PageNotManaged as ex:
        _reason("page_not_managed",
                f"the Facebook account behind FB_USER_TOKEN manages "
                f"{len(ex.managed)} other page(s) "
                f"({', '.join(ex.managed) if ex.managed else 'none'}) but not "
                f"our page - re-seed FB_USER_TOKEN from the account that owns "
                f"the page (README section 3)")
        return 4
    except Exception as ex:
        _reason("transient", f"/me/accounts failed: {ex}")
        return 5

    ok, chk = verify_page_token(fresh_page, page_id)
    if not ok:
        _reason("transient",
                f"fresh page token failed verification: {json.dumps(chk)[:160]}")
        return 5

    _out("user_token", fresh_user)
    _out("page_token", fresh_page)
    print("refresh: fresh tokens minted and verified - the workflow will "
          "store them as secrets")
    _out("reason", "minted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
