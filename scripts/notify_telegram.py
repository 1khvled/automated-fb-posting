#!/usr/bin/env python3
"""Send a Telegram alert about bot failures. Reads TELEGRAM_BOT_TOKEN
and TELEGRAM_CHAT_ID from env, message from argv[1] (or stdin).
Never prints secrets. Exits 0 on sent, 1 on skipped/failed — callers
should append `|| true` so a dead notifier never masks the real error.
"""
import os
import sys

import requests


def send_telegram(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("telegram: skipped (TELEGRAM_BOT_TOKEN/CHAT_ID not set)")
        return False
    try:
        r = requests.post(
            "https://api.telegram.org/bot" + token + "/sendMessage",
            json={"chat_id": chat, "text": text[:4000],
                  "disable_web_page_preview": True},
            timeout=20)
        try:
            ok = r.status_code == 200 and bool(r.json().get("ok"))
        except Exception:
            ok = False
        if not ok:
            print(f"telegram: send failed (HTTP {r.status_code})")
        return ok
    except Exception as ex:
        print(f"telegram: send error: {ex}")
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        msg = sys.argv[1]
    else:
        msg = sys.stdin.read()
    sys.exit(0 if send_telegram(msg.strip()) else 1)
