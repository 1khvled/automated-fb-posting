#!/usr/bin/env python3
"""Build the monthly growth-report issue body from metrics.jsonl.

Compares latest snapshot vs oldest: follower pace, 28-day reach trend,
and daily followers still needed to hit 10K by the 365-day goal
(goal date = first snapshot + 365 days). Prints markdown to stdout.
"""
import json
import os
import sys
from datetime import datetime, timezone

GOAL_FOLLOWERS = int(os.getenv("GOAL_FOLLOWERS", "10000"))
GOAL_DAYS = int(os.getenv("GOAL_DAYS", "365"))
PATH = os.getenv("METRICS_FILE", "metrics.jsonl")


def load(path: str) -> list:
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except FileNotFoundError:
        pass
    return rows


def num(x):
    return x if isinstance(x, (int, float)) else None


def main() -> int:
    rows = load(PATH)
    if not rows:
        print("No metrics snapshots yet.")
        return 0
    first, last = rows[0], rows[-1]
    t0 = datetime.fromisoformat(first["at"])
    t1 = datetime.fromisoformat(last["at"])
    days = max((t1 - t0).total_seconds() / 86400, 1 / 24)
    f0, f1 = num(first.get("followers")), num(last.get("followers"))
    print(f"# Monthly growth report — {t1.date().isoformat()}")
    print()
    if f0 is not None and f1 is not None:
        pace = (f1 - f0) / days
        goal_date = t0.date().isoformat() + f" + {GOAL_DAYS}d"
        remaining_days = GOAL_DAYS - (t1 - t0).days
        need = (GOAL_FOLLOWERS - f1) / max(remaining_days, 1)
        print(f"- Followers: **{f0} -> {f1}** "
              f"({pace:+.1f}/day over {days:.0f}d)")
        print(f"- Goal: {GOAL_FOLLOWERS} followers by {goal_date} "
              f"({remaining_days}d left)")
        print(f"- Pace needed from here: **{need:+.1f}/day**")
        if need <= 0:
            verdict = "GOAL HIT"
        elif pace >= need:
            verdict = "ON TRACK"
        else:
            verdict = "BEHIND - needs reach push"
        print(f"- Verdict: {verdict}")
    else:
        print(f"- Followers: latest={f1} (baseline missing)")
    for m in ("page_impressions_unique", "page_post_engagements",
              "page_video_views"):
        a, b = num(first.get(m)), num(last.get(m))
        if a is not None and b is not None:
            print(f"- {m}: {a} -> {b}")
        elif b is not None:
            print(f"- {m}: latest={b}")
    print()
    print(f"Snapshots: {len(rows)} | "
          f"Range: {t0.date().isoformat()} -> {t1.date().isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
