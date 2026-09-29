#!/usr/bin/env python3
"""Daily stats digest (posts, followers, reach, engagement, video views).

Reads yesterday's post count from posted.json, pulls followers + daily
Page insights via Graph API, appends one JSON line to daily_stats.jsonl
(committed back by the workflow for deltas), and sends a Telegram digest.
Degrades gracefully: if insights fail, the digest still reports posts +
followers. Needs FB_PAGE_ID + FB_PAGE_ACCESS_TOKEN + Telegram secrets.
Never prints secrets.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

from notify_telegram import send_telegram  # noqa: E402

FB_API_VERSION = "v26.0"
OUT_FILE = os.getenv("DAILY_STATS_FILE", "daily_stats.jsonl")
STATE_FILE = os.getenv("STATE_FILE", "posted.json")
UA = {"User-Agent": "ethan-cole-fb-bot/1.0"}

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _fmt(n):
    return f"{n:,}" if isinstance(n, int) else "n/a"


def main() -> int:
    page_id = os.getenv("FB_PAGE_ID", "").strip()
    token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    if not page_id or not token:
        print("daily-stats: FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not set")
        return 2
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    snap = {"at": datetime.now(timezone.utc).isoformat(),
            "day": str(yesterday)}

    # 1. posts yesterday (bot's own dedup state)
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
        snap["posts"] = int((state.get("day_counts") or {}).get(
            str(yesterday), 0))
    except Exception as ex:
        print(f"daily-stats: state read failed: {ex}")
        snap["posts"] = None

    # 2. followers right now
    try:
        r = requests.get(
            f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}",
            params={"fields": "followers_count", "access_token": token},
            timeout=20, headers=UA)
        d = r.json()
        snap["followers"] = d.get("followers_count")
    except Exception as ex:
        print(f"daily-stats: followers failed: {ex}")
        snap["followers"] = None

    # 3. yesterday's reach / engagement / video views
    for m in ("page_impressions_unique", "page_post_engagements",
              "page_video_views"):
        try:
            r = requests.get(
                f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}"
                f"/insights",
                params={"metric": m, "period": "day",
                        "since": str(yesterday), "until": str(yesterday + timedelta(days=1)),
                        "access_token": token},
                timeout=20, headers=UA)
            d = r.json()
            vals = ((d.get("data") or [{}])[0].get("values") or [])
            snap[m] = vals[-1].get("value") if vals else None
        except Exception as ex:
            snap[m] = None
            print(f"daily-stats: {m} failed: {ex}")

    # 4. follower delta vs previous digest
    prev_followers = None
    try:
        if os.path.exists(OUT_FILE):
            with open(OUT_FILE, encoding="utf-8") as f:
                lines = [ln for ln in f if ln.strip()]
            if lines:
                prev_followers = json.loads(lines[-1]).get("followers")
    except Exception as ex:
        print(f"daily-stats: baseline read failed: {ex}")
    with open(OUT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(snap) + "\n")

    if isinstance(snap["followers"], int) and isinstance(prev_followers, int):
        delta = snap["followers"] - prev_followers
        fol = f"{_fmt(snap['followers'])} ({delta:+d})"
    else:
        fol = _fmt(snap["followers"])
    # 10K goal pace: followers still needed / days left = required +/day.
    goal_line = ""
    try:
        goal = int(os.getenv("GOAL_FOLLOWERS", "10000"))
        deadline = datetime.strptime(
            os.getenv("GOAL_DEADLINE", "2027-09-29"), "%Y-%m-%d").date()
        days_left = (deadline - yesterday).days
        if isinstance(snap["followers"], int) and days_left > 0:
            need = (goal - snap["followers"]) / days_left
            pct = 100.0 * snap["followers"] / goal
            goal_line = (f"\n🎯 Goal {goal:,} by {deadline}: {pct:.1f}% — "
                         f"need +{need:.0f}/day ({days_left}d left)")
    except Exception:
        pass
    msg = (f"📊 Ethan Cole daily — {yesterday}\n"
           f"Posts: {snap['posts'] if snap['posts'] is not None else 'n/a'}\n"
           f"Followers: {fol}\n"
           f"Reach: {_fmt(snap['page_impressions_unique'])}\n"
           f"Engagement: {_fmt(snap['page_post_engagements'])}\n"
           f"Video views: {_fmt(snap['page_video_views'])}"
           f"{goal_line}")
    print(msg.replace("\n", " | "))
    send_telegram(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
