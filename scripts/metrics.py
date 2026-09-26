#!/usr/bin/env python3
"""Monthly growth snapshot for the 365-day monetization goal.

Pulls Page followers + 28-day reach/engagement via Graph API and appends
one JSON line to metrics.jsonl (committed back by the workflow), so the
trajectory toward invite-only Content Monetization can be reviewed here
in chat. Needs FB_PAGE_ID + FB_PAGE_ACCESS_TOKEN. Never prints secrets.
"""
import json
import os
import sys
from datetime import datetime, timezone

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

FB_API_VERSION = "v26.0"
OUT_FILE = os.getenv("METRICS_FILE", "metrics.jsonl")

PAGE_FIELDS = "name,followers_count,fan_count"
INSIGHT_METRICS = [
    "page_impressions_unique",
    "page_post_engagements",
    "page_video_views",
]


def main() -> int:
    page_id = os.getenv("FB_PAGE_ID", "").strip()
    token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    if not page_id or not token:
        print("metrics: FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not set")
        return 2
    snap = {"at": datetime.now(timezone.utc).isoformat()}
    try:
        r = requests.get(
            f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}",
            params={"fields": PAGE_FIELDS, "access_token": token},
            timeout=20)
        d = r.json()
        if r.status_code != 200 or "error" in d:
            print(f"metrics: page lookup failed: {str(d)[:150]}")
            return 3
        snap["followers"] = d.get("followers_count")
        snap["fans"] = d.get("fan_count")
    except Exception as ex:
        print(f"metrics: page lookup error: {ex}")
        return 3
    for m in INSIGHT_METRICS:
        try:
            r = requests.get(
                f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}/insights",
                params={"metric": m, "period": "days_28",
                        "access_token": token},
                timeout=20)
            d = r.json()
            vals = ((d.get("data") or [{}])[0].get("values") or [])
            snap[m] = vals[-1].get("value") if vals else None
        except Exception as ex:
            snap[m] = None
            print(f"metrics: {m} failed: {ex}")
    with open(OUT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(snap) + "\n")
    print("metrics: " + json.dumps({k: v for k, v in snap.items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
