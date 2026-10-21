#!/usr/bin/env python3
"""Product posts: the pages pitch what they actually sell.

The news pipeline is the top of the funnel; the product is the bottom. A page
that only posts news builds an audience it never monetises. A page that only
posts ads gets unfollowed. So the product posts are ROTATED IN with the news,
at a controlled rate, carrying the real product screenshots.

The content lives in content/product_posts.json so the copy is edited by
hand, not generated. This module only:
  - loads and validates it
  - picks the next post (least recently used first)
  - hands it back shaped like any other candidate
  - counts them, so the page cannot turn into an ad feed

Nothing here publishes. It only produces candidates.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTENT = HERE.parent / "content"
# the hand-written product posts, and the auto-generated daily signals
POST_FILES = [CONTENT / "product_posts.json", CONTENT / "signal_posts.json"]


def load_posts(path: Path | None = None) -> list:
    """All post configs. The signal posts are regenerated every morning by
    ops/make_signals.py + ops/signal_card.py, so they are always freshest."""
    files = [path] if path else POST_FILES
    out = []
    for p in files:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            data = data.get("posts", [])
        for e in data:
            if not isinstance(e, dict):
                continue
            if not e.get("title") or not e.get("body"):
                continue
            img = e.get("image", "")
            if img and not os.path.isabs(img):
                img = str((p.parent / img).resolve())
            if img and not os.path.exists(img):
                continue                  # never post a post whose image is missing
            e = dict(e)
            e["image"] = img
            e["_src"] = p.name
            out.append(e)
    return out


# ---------------------------------------------------------------- QC
FORBIDDEN = [
    r"\bsource\b\s*:", r"\bcointelegraph\b", r"\bcoindesk\b", r"\breuters\b",
    r"\bbloomberg\b", r"\bwatcherguru\b", r"\bfinancialjuice\b",
    r"https?://", r"\bwww\.",
]
LATIN_OK = re.compile(
    r"^[\s\W_]*(?:[A-Z]{2,5}\$?|[A-Z][A-Za-z]{2,}(?:\s+[A-Z][A-Za-z]{2,})*|"
    r"[A-Z][a-z]+|StockerAI|EdgeTrading|TradingView|AI|DCF|WACC|EMA|RSI|MACD|"
    r"ATR|COT|Pine|Python|Windows|Excel|API|DATA|HTML|CSV|PDF|URL|ID|"
    r"and|or|for|the|with|from|that|this|your|you|our|not|all|new|one|two|"
    r"three|four|five|free|pro|plus|beta|use|uses|using|get|gets|set|see|now|"
    r"how|why|what|when|where|which|who|yes|is|it|of|to|in|on|at|by|as|we|us|"
    r"i|a|an|be|do|does|did|so|if|up|out|off|on|per|via|its|it\u2019s)"
    r"[\s\W_]*$", re.I | re.U)


def check_post(e: dict) -> list:
    """Return a list of problems (empty = the post is publishable)."""
    problems = []
    text = (e.get("title", "") + "\n" + e.get("body", "") + "\n" +
            " ".join(e.get("hashtags", [])))
    for pat in FORBIDDEN:
        if re.search(pat, text, re.I):
            problems.append(f"forbidden pattern: {pat}")
    if e.get("lang") == "ar":
        for w in re.findall(r"[A-Za-z][A-Za-z0-9']+", text):
            if not LATIN_OK.match(w):
                problems.append(f"unlisted latin word: {w}")
    if not re.search(r"\d", e.get("title", "")):
        problems.append("the hook has no number")
    if not e.get("image") or not os.path.exists(e.get("image", "")):
        problems.append("the image is missing")
    tags = e.get("hashtags") or []
    if not (4 <= len(tags) <= 7):
        problems.append(f"hashtag count {len(tags)} (want 5-6)")
    return problems


# ---------------------------------------------------------------- rotation
def candidates(state: dict, path: Path | None = None) -> list:
    """Product posts as candidates, plus the daily counter for the state."""
    posts = load_posts(path)
    if not posts:
        return []
    used = state.get("product_posts_used") or []
    order = sorted(posts, key=lambda p: (used.index(p["id"]) if p.get("id") in used
                                         else -1))
    out = []
    for e in order:
        c = {
            "title": e["title"],
            "summary": e["body"],
            "link": "",
            "feed": "Product - EdgeTrading Pro",
            "keywords": e.get("hashtags", []),
            "photo_url": "",
            "local_photo": e.get("image", ""),
            "video_url": None,
            "score": 100.0,          # product posts are chosen on a schedule, not on news score
            "age_min": 0,
            "mode": "serious",
            "verified": True,
            "viral": False,
            "is_product": True,
            "product_id": e.get("id", ""),
            "cta": e.get("cta", ""),
        }
        out.append(c)
    return out


def daily_count(state: dict) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    return (state.get("product_posts_day") or {}).get(today, 0)


def mark_used(state: dict, product_id: str) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    used = state.setdefault("product_posts_used", [])
    if product_id in used:
        used.remove(product_id)
    used.append(product_id)
    state["product_posts_used"] = used[-30:]
    day = state.setdefault("product_posts_day", {})
    day[today] = day.get(today, 0) + 1
    for k in [k for k in day if k < today]:
        day.pop(k)
    state["product_posts_day"] = day


if __name__ == "__main__":
    posts = load_posts()
    print(f"{len(posts)} product posts in {POSTS_FILE}")
    bad = 0
    for e in posts:
        p = check_post(e)
        if p:
            bad += 1
            print(f"  FAIL {e.get('id')}: {p}")
    print(f"{len(posts) - bad} ok, {bad} failed")
