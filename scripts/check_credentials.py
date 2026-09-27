#!/usr/bin/env python3
"""Weekly credential health check: Facebook Page token (valid + days of
life left via debug_token) and every Gemini key (models-list probe, no
generation cost). Problems go to Telegram + non-zero exit (the workflow
also opens a [bot-alert] issue). Silent when all healthy.

Needs: FB_PAGE_ACCESS_TOKEN, FB_APP_ID, FB_APP_SECRET (app token is used
only to READ token metadata), GEMINI_API_KEYS, plus Telegram secrets
for alerts.
"""
import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from notify_telegram import send_telegram  # noqa: E402

UA = {"User-Agent": "ethan-cole-fb-bot/1.0"}
problems: list[str] = []

# 1. Facebook Page token: alive?
page_token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
try:
    r = requests.get("https://graph.facebook.com/v26.0/me",
                     params={"access_token": page_token}, timeout=20,
                     headers=UA)
    d = r.json()
    if "error" in d:
        problems.append("FB Page token DEAD: "
                        + str(d["error"].get("message", "?"))[:160])
    else:
        print(f"FB token alive (id {d.get('id')})")
except Exception as ex:
    problems.append(f"FB token check error: {ex}")

# 2. Facebook token expiry (needs app id/secret; skipped if unset).
app_id = os.getenv("FB_APP_ID", "").strip()
app_secret = os.getenv("FB_APP_SECRET", "").strip()
if page_token and app_id and app_secret and not any(
        p.startswith("FB Page token DEAD") for p in problems):
    try:
        r = requests.get(
            "https://graph.facebook.com/v26.0/debug_token",
            params={"input_token": page_token,
                    "access_token": f"{app_id}|{app_secret}"},
            timeout=20, headers=UA)
        data = (r.json().get("data") or {})
        if data.get("error"):
            problems.append("FB debug_token error: "
                            + str(data["error"].get("message", "?"))[:160])
        elif data.get("expires_at", 0):
            days = (int(data["expires_at"]) - int(time.time())) / 86400
            print(f"FB token expires in {days:.1f} days")
            if days < 14:
                problems.append(
                    f"FB Page token expires in {days:.1f} days — "
                    f"re-seed soon (README section 3)")
        else:
            print("FB token never expires (or no expiry returned)")
    except Exception as ex:
        problems.append(f"FB expiry check error: {ex}")
else:
    print("FB expiry check skipped (need FB_APP_ID/SECRET)")

# 3. Gemini keys: each must list models (cheap liveness probe).
raw = os.getenv("GEMINI_API_KEYS", "").strip()
single = os.getenv("GEMINI_API_KEY", "").strip()
keys = [k.strip() for k in (raw.split(",") if raw else []) if k.strip()]
if single and single not in keys:
    keys.append(single)
if not keys:
    problems.append("No Gemini keys configured at all")
dead = 0
for i, key in enumerate(keys):
    try:
        r = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": key, "pageSize": 1}, timeout=20, headers=UA)
        if r.status_code != 200:
            dead += 1
            problems.append(f"Gemini key #{i + 1} (…{key[-6:]}) HTTP "
                            f"{r.status_code}: {r.text[:120]}")
        else:
            print(f"Gemini key #{i + 1} (…{key[-6:]}) alive")
    except Exception as ex:
        dead += 1
        problems.append(f"Gemini key #{i + 1} check error: {ex}")
    time.sleep(1)
if keys and dead == len(keys):
    problems.append("ALL Gemini keys dead — bot cannot write posts")

if problems:
    send_telegram("🔑 Ethan Cole credential check FAILED:\n- "
                  + "\n- ".join(problems)
                  + "\nFix guide: repo README section 7.")
    print("PROBLEMS:", len(problems))
    sys.exit(1)
print("All credentials healthy.")
