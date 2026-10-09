#!/usr/bin/env python3
"""Rich failure alert for the Ethan Cole bot (English).

Runs ONLY on consecutive failures (the workflow gates single blips).
Reads the failed run's jobs + log via gh, extracts the real cause, and
sends ONE compact Telegram message with: streak count, cause, failed step,
last successful post, today's count, triage hint, log link.
Never crashes the step: any internal error falls back to a plain message.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from notify_telegram import send_telegram
except Exception:
    send_telegram = None

REPO = os.environ.get("GITHUB_REPOSITORY", "")
RUN_ID = os.environ.get("RUN_ID", "")
SERVER = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=120).stdout
    except Exception:
        return ""


def api(path):
    out = sh(["gh", "api", path])
    try:
        return json.loads(out) if out.strip() else {}
    except Exception:
        return {}


def main():
    link = f"{SERVER}/{REPO}/actions/runs/{RUN_ID}"
    try:
        return build(link)
    except Exception as ex:
        plain = (f"Ethan Cole bot run FAILED (run {RUN_ID}). "
                 f"Log parse failed ({ex}); triage from log: {link}")
        if send_telegram:
            send_telegram(plain)


def build(link):
    # 1. consecutive-failure streak (completed runs before this one)
    d = api("repos/" + REPO +
            "/actions/workflows/fb-post.yml/runs?per_page=10")
    streak = 0
    for r in d.get("workflow_runs", []):
        if str(r.get("id")) == str(RUN_ID):
            continue
        if r.get("status") != "completed":
            continue
        if r.get("conclusion") == "failure":
            streak += 1
        else:
            break
    streak += 1  # include this run

    # 2. failed steps
    jobs = api(f"repos/{REPO}/actions/runs/{RUN_ID}/jobs?per_page=5")
    bad_steps = []
    for j in (jobs.get("jobs") or []):
        for s in j.get("steps", []):
            if (s.get("conclusion") or "") == "failure":
                bad_steps.append(s.get("name", "?"))
    step = ", ".join(bad_steps) or "Run bot"

    # 3. log tail: the real cause
    log = sh(["gh", "run", "view", RUN_ID, "--log"])
    log = ANSI.sub("", log or "")
    cause, hint = classify(log)

    # 4. page health: posts today + minutes since last success
    posts_today, mins_ago = "?", "?"
    try:
        st = json.load(open("posted.json", encoding="utf-8"))
        today = datetime.now(timezone.utc).date().isoformat()
        posts_today = st.get("day_counts", {}).get(today, 0)
        at = (st.get("last_post") or {}).get("at", "")
        if at:
            dt = (datetime.now(timezone.utc)
                  - datetime.fromisoformat(at))
            mins_ago = int(dt.total_seconds() // 60)
    except Exception:
        pass

    msg = (f"Ethan Cole bot DOWN — failure #{streak} in a row\n"
           f"Cause: {cause}\n"
           f"Step: {step}\n"
           f"Last good post: {mins_ago}m ago | Today: {posts_today}\n"
           f"Do: {hint}\n"
           f"{link}")
    if send_telegram:
        send_telegram(msg)
    else:
        print(msg)


def classify(log):
    """(cause, triage-hint) from log signatures. Order matters."""
    if not log.strip():
        return ("log unavailable", "open the log link manually")
    fails = re.findall(r"All LLM providers failed: (.+)", log)
    if fails:
        tail = fails[-1][:600]
        bits = []
        if "429" in tail:
            n = len(re.findall(r"429", tail))
            bits.append(f"free-tier 429 storm (x{n})")
        m404 = re.findall(r"(\S+?): \S+ HTTP 404", tail)
        if m404:
            bits.append("retired models: " + ", ".join(
                m.split("/")[-1].split(":")[0] for m in m404[:2]))
        if "failed QC" in tail:
            q = re.findall(r"failed QC: \[(.*?)\]", tail)
            bits.append("QC reject: " + (q[-1][:120] if q else "?"))
        if "parse error" in tail or "no text" in tail or "empty" in tail:
            bits.append("model returned empty")
        detail = "; ".join(bits) or "all models down"
        if m404:
            return (detail, "update model slugs in post_bot.py")
        return (detail, "usually transient — if 3+ in a row, check logs")
    m = re.search(r"Quality check FAILED: (\[.*?\])", log)
    if m:
        return (f"QC reject: {m.group(1)[:150]}",
                "see reject reason; tune QC if it repeats")
    m = re.search(r"(Facebook error: .{0,150}|Publish failed: .{0,150})", log)
    if m:
        return (m.group(1)[:160], "FB message is in the log")
    if re.search(r"token.*(expir|invalid|190)|invalid.*token", log, re.I):
        return ("FB token dead", "re-seed per README section 3")
    m = re.search(r"Rewrite failed: (.{0,200})", log)
    if m:
        return (m.group(1), "details in log")
    return ("step failed (see log)", "details in log")


if __name__ == "__main__":
    main()
