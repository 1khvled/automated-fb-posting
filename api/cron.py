"""Vercel Cron entrypoint: runs post_bot.main() on schedule.

Deploy: push this folder to GitHub, import into Vercel, add the same env
vars as GitHub Actions (FB_PAGE_ID, FB_PAGE_ACCESS_TOKEN, GEMINI_API_KEYS,
OPENROUTER_API_KEY, CRON_SECRET), Vercel handles the cron from vercel.json.

IMPORTANT: pick ONE runner — GitHub Actions (persistent dedup via git,
recommended) OR Vercel Cron — never both at once, or you will double-post.
On Vercel the state file lives in /tmp (ephemeral), so cross-run dedup is
best-effort; the cooldown + daily cap still apply within each run.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import post_bot  # noqa: E402


def _authorized(handler: BaseHTTPRequestHandler) -> bool:
    secret = os.getenv("CRON_SECRET", "").strip()
    if not secret:
        return True  # no secret configured -> allow (Vercel still gates cron)
    if handler.headers.get("Authorization", "") == f"Bearer {secret}":
        return True
    try:
        q = parse_qs(urlparse(handler.path).query)
        if q.get("key", [""])[0] == secret:
            return True
    except Exception:
        pass
    return False


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not _authorized(self):
            body = json.dumps({"ok": False, "error": "unauthorized"}).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        os.environ.setdefault("STATE_FILE", "/tmp/posted.json")
        try:
            rc = post_bot.main()
            body = json.dumps({"ok": rc == 0, "rc": rc}).encode()
            self.send_response(200)
        except Exception as ex:  # noqa: BLE001
            body = json.dumps({"ok": False, "error": str(ex)[:300]}).encode()
            self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.do_GET()
