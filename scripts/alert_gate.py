#!/usr/bin/env python3
"""Alert gate: fire once when the page actually goes dark.

History. The first gate asked "did the previous run also fail?" and alerted
on EVERY following run: 212 consecutive failures produced 212 Telegram
messages per repo. The second counted the streak and alerted on any single
failure (streak==1) - but when a bot fails every other run, every failure
is "streak==1", so Nov 2026 produced 20 identical Telegram messages in 3
days for a page that was still posting.

Now the gate asks the only question that matters: how long has it been
since this workflow last SUCCEEDED? A transient 429 or a timeout while the
page is still posting is not an outage and must not ping anyone. Dark for
ALERT_GAP_HOURS (default 6) is an outage. Two consecutive failures also
count, because that is a hard break, not a blip.

Repeat suppression is done by the workflow: it only sends the Telegram
message when it actually opens a new [bot-alert] issue, and the issue stays
open until a run succeeds. So one outage = one alert, no matter how many
runs fail inside it.

Prints: "ALERT streak=N dark=H.Hh" or "QUIET streak=N dark=H.Hh".
"""
import calendar
import json
import os
import sys
import time
import urllib.request

GATE_REPO = os.environ.get("GITHUB_REPOSITORY", "")
RUN_ID = os.environ.get("RUN_ID", "")
WORKFLOW = os.environ.get("ALERT_WORKFLOW", "fb-post.yml")
GAP_HOURS = float(os.environ.get("ALERT_GAP_HOURS", "6"))
TOKEN = os.environ.get("GH_TOKEN", "")


def api(path):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Accept": "application/vnd.github+json",
                 "Authorization": f"Bearer {TOKEN}",
                 "User-Agent": "alert-gate"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception:
        return {}


def _ts(run):
    raw = run.get("run_started_at") or run.get("created_at") or ""
    try:
        return calendar.timegm(time.strptime(raw, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return None


def main() -> int:
    if not GATE_REPO or not TOKEN:
        print("QUIET streak=0 dark=0.0h")
        return 0

    d = api(f"/repos/{GATE_REPO}/actions/workflows/{WORKFLOW}/runs"
            f"?per_page=100")
    runs = [r for r in d.get("workflow_runs", [])
            if r.get("status") == "completed"
            and str(r.get("id")) != RUN_ID]

    # runs come newest-first.
    streak = 0
    for r in runs:
        if r.get("conclusion") != "failure":
            break
        streak += 1

    last_ok = None
    for r in runs:
        if r.get("conclusion") == "success":
            last_ok = _ts(r)
            break
    dark_h = (time.time() - last_ok) / 3600.0 if last_ok else 9999.0

    alert = streak >= 2 or dark_h >= GAP_HOURS
    print(("ALERT" if alert else "QUIET")
          + f" streak={streak} dark={dark_h:.1f}h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
