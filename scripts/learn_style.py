#!/usr/bin/env python3
"""Learn house style from top-performing X accounts (Watcher Guru et al).

Fetches recent timelines via FxEmbed, measures format patterns (length,
openers, emoji, caps, numbers, hashtags, closers), and writes
style_profile.json (committed). A monthly workflow refreshes it and the
findings steer SYSTEM_PROMPT tuning here in chat. Read-only: no posting.
"""
import json
import os
import re
import statistics
import sys
from collections import Counter

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ACCOUNTS = os.getenv("STYLE_ACCOUNTS",
                     "WatcherGuru,KobeissiLetter,unusual_whales,"
                     "StockMKTNewz,DeItaone").split(",")
PER_ACCOUNT = int(os.getenv("STYLE_PER_ACCOUNT", "40"))
OUT_FILE = os.getenv("STYLE_OUT", "style_profile.json")
UA = {"User-Agent": "ethan-cole-fb-bot/1.0"}

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")


def fetch(handle: str) -> list:
    try:
        r = requests.get(
            f"https://api.fxtwitter.com/2/profile/{handle}/statuses",
            params={"limit": 20}, timeout=20, headers=UA)
        d = r.json()
        if d.get("code") != 200:
            print(f"style: @{handle} API code {d.get('code')}")
            return []
        out = []
        for p in (d.get("results") or [])[:PER_ACCOUNT]:
            text = re.sub(r"https?://\S+", "", p.get("text") or "").strip()
            text = re.sub(r"\s+", " ", text)
            if not text or text.startswith("RT @") or p.get("replying_to"):
                continue
            out.append(text)
        print(f"style: @{handle} {len(out)} posts")
        return out
    except Exception as ex:
        print(f"style: @{handle} error: {ex}")
        return []


def analyze(posts: list) -> dict:
    n = len(posts)
    if not n:
        return {"n": 0}
    lens = [len(p) for p in posts]
    first_lines = [(p.split("\n")[0] if "\n" in p else p[:80]) for p in posts]
    leaders = []
    for p in posts:
        m = re.match(r"^(JUST IN|BREAKING|NEW|WATCH|LOOK|REPORT)[:\s]*",
                     p, re.I)
        leaders.append(m.group(1).upper() if m else "")
    prof = {
        "n": n,
        "median_chars": int(statistics.median(lens)),
        "p90_chars": int(sorted(lens)[min(n - 1, int(n * 0.9))]),
        "opens_with_emoji": round(
            sum(1 for p in posts if EMOJI_RE.match(p.strip())) / n, 2),
        "has_emoji_anywhere": round(
            sum(1 for p in posts if EMOJI_RE.search(p)) / n, 2),
        "breaking_leader": round(
            sum(1 for l in leaders if l in ("JUST IN", "BREAKING")) / n, 2),
        "any_leader": round(sum(1 for l in leaders if l) / n, 2),
        "has_dollar_or_pct": round(
            sum(1 for p in posts if "$" in p or "%" in p) / n, 2),
        "has_number": round(sum(1 for p in posts if re.search(r"\d", p)) / n, 2),
        "ends_with_question": round(
            sum(1 for p in posts if p.rstrip().endswith("?")) / n, 2),
        "has_hashtag": round(sum(1 for p in posts if "#" in p) / n, 2),
        "median_hashtags": int(statistics.median(
            [len(re.findall(r"#\w+", p)) for p in posts])),
        "top_openers": Counter(
            l for l in leaders if l).most_common(5),
    }
    caps = []
    for fl in first_lines:
        letters = [c for c in fl if c.isalpha()]
        if letters:
            caps.append(sum(1 for c in letters if c.isupper()) / len(letters))
    prof["median_caps_ratio_firstline"] = round(
        statistics.median(caps), 2) if caps else 0
    return prof


def main() -> int:
    per_acct, combined = {}, []
    for h in [a.strip() for a in ACCOUNTS if a.strip()]:
        posts = fetch(h)
        per_acct[h] = analyze(posts)
        combined.extend(posts)
    profile = {"accounts": per_acct, "combined": analyze(combined)}
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
    print(json.dumps(profile["combined"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
