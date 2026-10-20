#!/usr/bin/env python3
"""Alert gate: fire once when an outage starts, then once a day.

The old gate asked "did the previous run also fail?" and alerted on
EVERY following run: 212 consecutive failures produced 212 Telegram
messages per repo. Now we count the streak and only alert on the 2nd
consecutive failure (outage confirmed) plus a heartbeat every ALERT_EVERY
failures, so a long outage is reported once and then daily - never
spammed, never forgotten.

A gap of more than ALERT_GAP_HOURS between runs breaks the streak: the
bot was idle/asleep, so the next failure is a fresh outage.

Prints: "ALERT streak=N" or "QUIET streak=N" (safe to grep in bash).
"""
import json
import os
import sys
import time
import urllib.request

GATE_REPO = os.environ.get("GITHUB_REPOSITORY", "")
RUN_ID = os.environ.get("RUN_ID", "")
WORKFLOW = os.environ.get("ALERT_WORKFLOW", "fb-post.yml")
ALERT_EVERY = int(os.environ.get("ALERT_EVERY", "24"))
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
    raw = run.get("run_started_at") or ""
    try:
        return time.mktime(time.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")) \
            - time.timezone
    except Exception:
        return time.time()


def main() -> int:
    if not GATE_REPO or not TOKEN:
        print("QUIET streak=0")
        return 0
    d = api(f"/repos/{GATE_REPO}/actions/workflows/{WORKFLOW}/runs"
            f"?per_page=100")
    runs = [r for r in d.get("workflow_runs", [])
            if r.get("status") == "completed"
            and str(r.get("id")) != RUN_ID]
    streak = 0
    newer_ts = None
    for r in runs:
        t = _ts(r)
        if newer_ts is not None and (newer_ts - t) > GAP_HOURS * 3600:
            break
        if r.get("conclusion") != "failure":
            break
        streak += 1
        newer_ts = t
    # streak = consecutive failures BEFORE this run.
    alert = streak == 1 or (streak > 1 and streak % ALERT_EVERY == 0)
    print(("ALERT" if alert else "QUIET") + f" streak={streak}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
