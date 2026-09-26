#!/usr/bin/env python3
"""
Ethan Cole Finance + AI — Facebook auto-poster
Runs every 20 min via GitHub Actions. Fetches RSS, filters by criteria,
rewrites in Ethan Cole voice via LLM, posts to FB Page via Graph API.

Env secrets required:
  FB_PAGE_ID, FB_PAGE_ACCESS_TOKEN
  GEMINI_API_KEY (main writer) and/or OPENAI_API_KEY/OPENROUTER_API_KEY (backup).
  Bake-off winner: gemini-2.5-flash main, OpenRouter free backup.
  Optional model override: GEMINI_MODEL, OPENROUTER_MODEL.

Optional:
  DRY_RUN=1 — generate post but skip Facebook publish
  MAX_AGE_MINUTES=2880 — only consider news newer than this (default 2880 = 2d)
  STATE_FILE=posted.json — dedup store
  GEMINI_API_KEYS=k1,k2,.. — comma-separated key pool, rotated every run
  MIN_VIDEO_SCORE=4 — video pick bar (default 4)
  VIDEO_DEADLINE_HOUR=20 — after this UTC hour the bar drops so the day
    still gets its reel (default 20)
  VIDEO_DEADLINE_SCORE=1 — lowered end-of-day video bar (default 1)
"""

import difflib
import hashlib
import html
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()  # local .env; no-op in GitHub Actions (env already set)
except ImportError:
    pass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------- feeds
RSS_FEEDS = [
    # Finance / economy
    ("CNBC Top", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("CNBC Economy", "https://www.cnbc.com/id/10000113/device/rss/rss.html"),
    ("Fed Press", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("FinancialJuice Squawk", "https://www.financialjuice.com/feed.ashx?xy=rss"),
    ("CNBC Politics", "https://www.cnbc.com/id/10000115/device/rss/rss.html"),
    # Geopolitics with markets lens (power-lane gate keeps pure politics out)
    ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("AlJazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    # AI / tech
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("MIT Tech Review AI", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
]

# ---------------------------------------------------------------- criteria
# LEARNED WEIGHTS from 80 Ethan Cole posts (Sep 2026), ranked by engagement:
# crypto 5.0, gold/oil 3.2, stocks 3.0, AI 2.9, inflation 1.9, fed-process 1.5.
# Page data also proved: 5-6 hashtags avg 3.7 engagement vs 0.3 for 7+.
TOPIC_WEIGHTS = {
    "crypto": (["bitcoin", "btc", "crypto", "ethereum", "etf"], 4),
    "gold_oil": (["gold", "oil", "opec", "brent", "hormuz"], 3),
    "stocks": (["s&p", "nasdaq", "dow", "stock market", "wall street",
                "treasury", "bond yield", "ecb", "imf"], 3),
    "ai": (["openai", "anthropic", "nvidia", "gpu", "llm", "chatgpt", "claude",
            "gemini", "copilot", "artificial intelligence", "generative ai",
            "ai chip", "ai model", "ai funding", "ai startup",
            "semiconductor"], 3),
    "inflation": (["inflation", "cpi", "ppi", "jobs report", "payrolls",
                   "unemployment", "gdp", "recession"], 2),
    "fed": (["fed", "federal reserve", "interest rate", "rate cut",
             "rate hike"], 1),
    "power": (["trump", "maga", "white house", "tariff", "executive order",
               "supreme court", "congress", "senate", "election",
               "republican", "democrat", "liberal", "woke", "biden",
               "vance", "modi", "india", "putin", "xi jinping",
               "netanyahu", "zelensky"], 3),
}

# Format bonuses learned from the page's top-8 posts:
# model launches/demos (#1 post: Opus one-shotting a game), security
# breaches (#3: Gemini hack), hard numbers/specs, genuine breaking news.
FORMAT_BONUS = [
    (re.compile(r"launch|unveil|release|demo|one-shot|gpt-\d|opus|gro[kq]", re.I),
     3, "launch/demo"),
    (re.compile(r"hack|breach|leak", re.I), 2, "security"),
    (re.compile(r"\$\d|\d+%|\d+\.\d+%|billion|million|record|all-time high", re.I),
     2, "hard-numbers"),
    (re.compile(r"breaking|just in", re.I), 1, "breaking"),
]

EXCLUDE = [
    "horoscope", "celebrity breakup", "kardashian", "football transfer",
    "premier league", "cricket score", "lottery winner", "giveaway",
    "discount code", "coupon", "porn", "casino bonus",
]

# Engagement tuner: multipliers learned from OUR OWN posts' performance.
# tune_from_engagement() refreshes them at most once/day (cheap: <=8 calls).
_TUNER: dict = {}
KW_TO_TOPIC = {k: t for t, (kws, _w) in TOPIC_WEIGHTS.items() for k in kws}


def _post_engagement(fb_id: str):
    page_token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    r = requests.get(
        f"https://graph.facebook.com/{FB_API_VERSION}/{fb_id}",
        params={"fields": "likes.summary(true),comments.summary(true),shares",
                "access_token": page_token},
        timeout=15)
    d = r.json()
    if r.status_code != 200 or "error" in d:
        raise RuntimeError(f"engagement lookup failed: {str(d)[:150]}")
    likes = ((d.get("likes") or {}).get("summary") or {}).get("total_count", 0)
    comments = ((d.get("comments") or {}).get("summary") or {}).get(
        "total_count", 0)
    shares = (d.get("shares") or {}).get("count", 0)
    return likes + 3 * comments + 5 * shares  # same weights as training


def tune_from_engagement(state: dict) -> dict:
    """Pull engagement on our posts from the last 7 days, update multipliers.
    mult = smoothed (per-topic avg / global avg), clamped 0.5-2.0, needs n>=2."""
    tuner = state.setdefault("tuner", {"topics": {}, "mult": {}})
    today = datetime.now(timezone.utc).date().isoformat()
    if tuner.get("updated") == today:
        return tuner.get("mult", {})
    if not os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip():
        return tuner.get("mult", {})
    cutoff = datetime.now(timezone.utc).timestamp() - 7 * 86400
    items = []
    for h in state.get("history", [])[-8:]:
        if not h.get("fb_id"):
            continue
        try:
            ts = datetime.fromisoformat(h.get("at", "")).timestamp()
        except Exception:
            continue
        if ts >= cutoff:
            items.append(h)
    if not items:
        tuner["updated"] = today
        return tuner.get("mult", {})
    agg: dict = {}
    for h in items:
        try:
            e = _post_engagement(h["fb_id"])
        except Exception as ex:
            log(f"tuner: skip {h['fb_id']}: {ex}")
            continue
        for t in h.get("topics", []) or ["unknown"]:
            a = agg.setdefault(t, {"n": 0, "e": 0})
            a["n"] += 1
            a["e"] += e
    total_n = sum(a["n"] for a in agg.values())
    total_e = sum(a["e"] for a in agg.values())
    if total_n and total_e:
        glob = total_e / total_n
        mult = dict(tuner.get("mult", {}))
        for t, a in agg.items():
            if a["n"] >= 2 and t != "unknown":
                obs = max(0.5, min(2.0, (a["e"] / a["n"]) / glob))
                mult[t] = round(0.7 * mult.get(t, 1.0) + 0.3 * obs, 2)
        tuner["topics"] = {t: a for t, a in agg.items()}
        tuner["mult"] = mult
        log(f"tuner: n={total_n} avg={glob:.1f} mult={mult}")
    tuner["updated"] = today
    return tuner.get("mult", {})

MAX_HASHTAGS = 6
FB_API_VERSION = "v26.0"


def log(msg: str):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


# ---------------------------------------------------------------- X via FxEmbed
# Free X timelines, no key (1000 req/min/IP). Tested live Sep 2026:
# real-time posts + likes/reposts/replies. Add finance/AI handles here.
X_HANDLES = [
    # Finance squawk — fastest headlines on X (verified live, Sep 2026)
    "financialjuice",   # trader squawk wire
    "DeItaone",         # Walter Bloomberg, 1.9M — fastest headlines
    "KobeissiLetter",   # 2.6M — breaking + context threads
    "FirstSquawk",      # 567K — macro/geopolitics squawk
    "WatcherGuru",      # 4.9M — JUST IN crypto+macro machine
    "Megatron_ron",      # 3M+ — raw breaking wire, strict min_score gate
    "NFT_Chen",         # Chinese AI scoops, high noise -> strict gate
    "bridgemindai",     # 59K live model tests -> video-only rule
    "clashreport",      # 896K geopolitics wire -> market-moving only
    # AI labs, official (releases drop here first, days before blogs)
    "OpenAI",           # 5.4M
    "AnthropicAI",      # 1.8M
    "GoogleDeepMind",   # 1.5M — papers, benchmarks
    "AIatMeta",         # 855K — Llama/open-source side
]

# Per-account rules: high-volume or off-format accounts get their own gate.
# boost: trusted GOATs rank higher. min_score: noisy accounts need a high bar.
# video_only + test_words: bridgemindai live model-test videos only.
# geo_only: clashreport market-moving geopolitics only (oil/war/trade, not takes).
GEO_MARKET_MOVERS = [
    "oil", "gas", "hormuz", "strait", "strike", "missile", "drone",
    "sanction", "tariff", "blockade", "war", "ceasefire", "nuclear",
    "refinery", "pipeline", "nato", "taiwan", "invasion", "coup",
    "embargo", "opec", "tanker", "airspace", "mobiliz", "evacuat",
    "explosion", "attack",
]
X_SOURCE_RULES = {
    "DeItaone": {"boost": 2},
    "WatcherGuru": {"boost": 1},
    "NFT_Chen": {"min_score": 6},
    "Megatron_ron": {"min_score": 6},  # huge breaking feed, strict gate
    "bridgemindai": {"video_only": True,
                      "test_words": ["live test", "testing", "test", "benchmark",
                                     "hands-on", "first look", "made this video",
                                     "vs ", "comparison", "torture test"]},
    "clashreport": {"geo_only": True},
}


def fetch_x_candidates(max_age_minutes: int):
    out = []
    for handle in X_HANDLES:
        try:
            r = requests.get(
                f"https://api.fxtwitter.com/2/profile/{handle}/statuses",
                params={"limit": 20}, timeout=15,
                headers={"User-Agent": "ethan-cole-fb-bot/1.0"})
            d = r.json()
            if d.get("code") != 200:
                log(f"X @{handle}: API code {d.get('code')}")
                continue
            for p in (d.get("results") or [])[:20]:
                text = re.sub(r"https?://\S+", "", p.get("text") or "").strip()
                text = re.sub(r"\s+", " ", text)
                if not text or text.startswith("RT @"):
                    continue
                if p.get("replying_to"):  # context-less replies
                    continue
                ts = p.get("created_timestamp")
                try:
                    age = (time.time() - int(ts)) / 60 if ts else None
                except Exception:
                    age = None
                if age is not None and age > max_age_minutes:
                    continue
                link = (p.get("url")
                        or f"https://x.com/{handle}/status/{p.get('id')}")
                photo_url = None
                video_url = None
                try:
                    for ph in ((p.get("media") or {}).get("photos") or []):
                        u = ph.get("url") or ph.get("src")
                        if u:
                            photo_url = u
                            break
                    for vd in ((p.get("media") or {}).get("videos") or []):
                        u = vd.get("url") or vd.get("src")
                        if u:
                            video_url = u
                            break
                except Exception:
                    photo_url = None
                title = text if len(text) <= 200 else text[:197] + "..."
                s, hits = score_entry(title, text)
                vb = viral_bonus(text, likes=p.get("likes", 0) or 0,
                                 reposts=p.get("reposts", 0) or 0,
                                 replies=p.get("replies", 0) or 0)
                s += vb
                mode = "viral" if vb >= 3 else "serious"
                rule = X_SOURCE_RULES.get(handle, {})
                if rule.get("video_only"):
                    media = p.get("media") or {}
                    if not media.get("videos"):
                        continue
                    tw = rule.get("test_words", [])
                    if tw and not any(w in text.lower() for w in tw):
                        continue
                if rule.get("geo_only"):
                    if not any(k in text.lower() for k in GEO_MARKET_MOVERS):
                        continue
                s += rule.get("boost", 0)
                s = decay(s, age, mode)
                if s < rule.get("min_score", 1):
                    continue
                out.append({
                    "feed": f"X @{handle}",
                    "photo_url": photo_url, "video_url": video_url,
                    "mode": mode, "viral": vb,
                    "title": title,
                    "summary": text[:400],
                    "link": link,
                    "age_min": round(age) if age is not None else None,
                    "score": s,
                    "keywords": hits[:5],
                    "verified": True,  # exists by definition of API return
                })
        except Exception as ex:
            log(f"X @{handle} error: {ex}")
    out.sort(key=lambda c: c["score"], reverse=True)
    return out


# ---------------------------------------------------------------- Telegram
# Public channel previews (t.me/s/...) need no login. ClashReport TG is
# fresher than its X mirror; remarks exists ONLY on Telegram (its X
# namesake is a dead parody account).
TG_CHANNELS = {
    "ClashReport": {"geo_only": True},
    "FinancialJuice": {},
    "remarks": {},
}


def _tg_views(raw: str) -> int:
    m = re.search(r'tgme_widget_message_views">([^<]+)<', raw)
    if not m:
        return 0
    v = m.group(1).strip().upper().replace(",", "")
    try:
        if v.endswith("K"):
            return int(float(v[:-1]) * 1000)
        if v.endswith("M"):
            return int(float(v[:-1]) * 1000000)
        return int(float(v))
    except Exception:
        return 0


def fetch_tg_candidates(max_age_minutes: int):
    out = []
    for ch, rule in TG_CHANNELS.items():
        try:
            r = requests.get(
                f"https://t.me/s/{ch}", timeout=20,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            if r.status_code != 200:
                log(f"TG {ch}: HTTP {r.status_code}")
                continue
            blocks = re.split(r'<div class="tgme_widget_message_wrap', r.text)[1:]
            for b in blocks[-25:]:
                m_post = re.search(r'data-post="([^"]+)"', b)
                m_time = re.search(r'<time datetime="([^"]+)"', b)
                m_text = re.search(r'js-message_text" dir="auto">(.*?)</div>',
                                   b, re.S)
                if not (m_post and m_time and m_text):
                    continue  # media-only post, no text
                try:
                    dt = datetime.fromisoformat(m_time.group(1))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - dt).total_seconds() / 60
                except Exception:
                    age = None
                if age is not None and (age < -5 or age > max_age_minutes):
                    continue
                text = html.unescape(re.sub(r"<[^>]+>", " ", m_text.group(1)))
                text = re.sub(r"\s+", " ", text).strip()
                if len(text) < 15:
                    continue
                if rule.get("geo_only"):
                    if not any(k in text.lower() for k in GEO_MARKET_MOVERS):
                        continue
                link = f"https://t.me/{m_post.group(1)}"
                m_photo = re.search(
                    r"tgme_widget_message_photo_wrap[^>]*"
                    r"background-image:url\('([^']+)'", b)
                photo_url = (html.unescape(m_photo.group(1))
                             if m_photo else None)
                m_video = re.search(r'<video src="([^"]+\.mp4[^"]*)"', b)
                video_url = (html.unescape(m_video.group(1))
                             if m_video else None)
                title = text if len(text) <= 200 else text[:197] + "..."
                s, hits = score_entry(title, text)
                vb = viral_bonus(text, views=_tg_views(b))
                s += vb
                mode = "viral" if vb >= 3 else "serious"
                s = decay(s, age, mode)
                if s < 1:
                    continue
                out.append({
                    "feed": f"TG {ch}",
                    "photo_url": photo_url, "video_url": video_url,
                    "mode": mode, "viral": vb,
                    "title": title,
                    "summary": text[:400],
                    "link": link,
                    "age_min": round(age) if age is not None else None,
                    "score": s,
                    "keywords": hits[:5],
                    "verified": True,
                })
        except Exception as ex:
            log(f"TG {ch} error: {ex}")
    out.sort(key=lambda c: c["score"], reverse=True)
    return out


# Recency decay: fresh news wins. -1 point per 30 min of age, so a 6h-old
# story loses 12 and can never clear the publish bar. Unknown age: no decay.
def decay(score: float, age, mode: str = "serious") -> float:
    if age is None:
        return round(score, 1)
    # serious news rots fast (-1/30min); viral takes live for days (-1/4h)
    step = 240.0 if mode == "viral" else 30.0
    return round(score - age / step, 1)


def entry_age_minutes(entry) -> float | None:
    for key in ("published_parsed", "updated_parsed"):
        ts = entry.get(key)
        if ts:
            try:
                dt = datetime(*ts[:6], tzinfo=timezone.utc)
                return (datetime.now(timezone.utc) - dt).total_seconds() / 60
            except Exception:
                pass
    for key in ("published", "updated"):
        val = entry.get(key)
        if val:
            try:
                dt = parsedate_to_datetime(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return (datetime.now(timezone.utc) - dt).total_seconds() / 60
            except Exception:
                pass
    return None


def score_entry(title: str, summary: str) -> tuple[int, list[str]]:
    text = f"{title} {summary}".lower()
    if any(x in text for x in EXCLUDE):
        return -100, []
    hits: list[str] = []
    score = 0.0
    for topic, (kws, w) in TOPIC_WEIGHTS.items():
        matched = [k for k in kws if k in text]
        if matched:
            # topic weight x engagement-learned multiplier + depth, capped
            score += w * _TUNER.get(topic, 1.0) + min(len(matched) - 1, 2)
            hits.extend(matched[:3])
    if score == 0:
        return 0, []
    for pat, bonus, label in FORMAT_BONUS:
        if pat.search(text):
            score += bonus
            hits.append(f"+{label}")
    # learned: generic fed-process stories with no market angle flop (avg 1.5)
    if any(h in ("fed", "federal reserve", "interest rate") for h in hits) and not \
            re.search(r"market|stock|s&p|nasdaq|bitcoin|mortgage|yield|dollar", text):
        score -= 2
    # power-lane gate: politics/geopolitics MUST move markets or it flops
    # (and risks policy flags). Tariff/trade/oil stories pass; pure rally
    # speeches, gaffes and street crime do not.
    if "power" in {KW_TO_TOPIC.get(k, "") for k in hits} and not \
            re.search(r"market|stock|s&p|nasdaq|bitcoin|crypto|oil|gold|dollar|"
                      r"tariff|trade|jobs|gdp|inflation|fed|yield|mortgage|"
                      r"wall street|sanction|embargo", text):
        score -= 3
    if len(title.strip()) < 25:
        score -= 1
    return score, hits[:6]


def fetch_candidates(max_age_minutes: int):
    candidates = []
    for name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            log(f"Feed {name}: {len(feed.entries)} entries")
            for e in feed.entries[:40]:  # 40: squawk wires (FJ: 100 items)
                # publish ~15/hr; 20-min cron needs depth, filter does the culling
                title = re.sub(r"^FinancialJuice:\s*", "",
                                 (e.get("title") or "").strip())
                summary = (e.get("summary") or e.get("description") or "")[:500]
                link = (e.get("link") or "").strip()
                if not title or not link:
                    continue
                age = entry_age_minutes(e)
                if age is not None and age > max_age_minutes:
                    continue
                s, hits = score_entry(title, summary)
                vb = viral_bonus(title + " " + summary)
                s += vb
                mode = "viral" if vb >= 3 else "serious"
                if s < 1:
                    continue
                # basic verify: article URL reachable
                verified = verify_url(link)
                candidates.append({
                    "feed": name,
                    "mode": mode, "viral": vb,
                    "title": title,
                    "summary": html.unescape(re.sub(r"<[^>]+>", "", summary))[:400],
                    "link": link,
                    "age_min": round(age) if age is not None else None,
                    "score": decay(s + (1 if verified else -1), age, mode),
                    "keywords": hits[:5],
                    "verified": verified,
                })
        except Exception as ex:
            log(f"Feed {name} error: {ex}")
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def verify_url(url: str) -> bool:
    try:
        r = requests.head(url, timeout=10, allow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code < 400:
            return True
        r = requests.get(url, timeout=12, allow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        return r.status_code < 400
    except Exception:
        return False


# ---------------------------------------------------------------- state (dedup)
def load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"posted_hashes": []}


def save_state(path: str, state: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def item_hash(link: str, title: str) -> str:
    return hashlib.sha256(f"{link}|{title}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------- rewrite (Ethan Cole voice)
SYSTEM_PROMPT = """You write Facebook posts for the page 'Ethan Cole Finance + AI'.
House style mined from the page's own 80 posts (top performers weighted):
- Hook line first: emoji (🚨 for genuine news) + CAPS claim. Then 1-2 short context lines.
- Body ~10-14 short lines with blank-line breaks: 1-2 context lines, then a numbers/specs block with emoji bullets when specs exist.
- Open with an emoji (75% of page posts do; alert emoji for fresh news in 65%). Almost never open with a question.
- One 'why it matters' line with the market implication.
- Length 400-750 characters. NEVER under 150.
- Hashtags: ALWAYS include #ethancole first, then 4-5 topic tags from the house set when relevant: #ai #artificialintelligence #technews #finance #stockmarket #investing #breakingnews #marketnews #federalreserve #crypto #bitcoin #openai #nvidia #economy. Exactly 5-6 total. Page data proves 7+ tags collapse engagement.
- Rewrite originally, never copy the headline. NO URLs in the copy.
- Do NOT write any source/credit line — the publisher appends source
  attribution automatically at the end of every post.
- 'BREAKING'/'JUST IN' only for genuinely fresh news; 'reportedly' if unconfirmed.
- NEVER use markdown or special formatting: NO asterisks (*) anywhere,
  NO **bold**, NO _underscores_, NO # headers, NO > quotes, NO backticks.
  Facebook renders them literally as ugly characters. For emphasis use CAPS.
Output plain copy-paste text only, no commentary."""

USER_TEMPLATE = """Source: {feed}
Headline: {title}
Summary: {summary}
Article URL (for your context only, do NOT include in post): {link}
Verified reachable: {verified}
Keywords: {keywords}

Write the Facebook post as plain copy-paste text only, no commentary."""


# ---------------------------------------------------------------- rewrite (Ethan Cole voice)
# Bake-off winner (Sep 2026, 80-post training + live generation test):
#   MAIN   = Gemini gemini-2.5-flash (only model that passed QC first try)
#   BACKUP = OpenRouter free (default qwen3.8-27b; nemotron-lightning leaks
#            reasoning, inkling:free is API-blocked by OpenRouter, free-tier
#            models 429 under load — hence backup position with QC gate)
def _gemini_keys() -> list:
    keys = []
    multi = os.getenv("GEMINI_API_KEYS", "")
    if multi:
        keys += [k.strip() for k in multi.split(",") if k.strip()]
    single = os.getenv("GEMINI_API_KEY", "").strip()
    if single:
        keys.append(single)
    return list(dict.fromkeys(keys))  # dedup, keep order


def gen_gemini(model: str, system: str, user: str) -> str:
    import json as _json
    keys = _gemini_keys()
    if not keys:
        raise RuntimeError("No Gemini key set")
    # Spread load across ALL keys, every day: each 20-min cron slot starts
    # on a different key, and any 429/quota failure falls through to the
    # next key in the same call. 72 runs/day / 5 keys ~= 14 leads per key.
    now = datetime.now(timezone.utc)
    slot = now.timetuple().tm_yday * 72 + now.hour * 3 + now.minute // 20
    start = slot % len(keys)
    ordered = keys[start:] + keys[:start]
    last_err = "no keys tried"
    for key in ordered:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
                f":generateContent?key={key}",
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": system + "\n\n" + user}]}],
                      "generationConfig": {"maxOutputTokens": 1000,
                                           "temperature": 0.5,
                                           "thinkingConfig": {"thinkingBudget": 0}}},
                timeout=90)
            d = r.json()
            if d.get("error"):
                raise RuntimeError(f"API error: {str(d['error'])[:120]}")
            return d["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as ex:
            last_err = f"key …{key[-6:]}: {ex}"[:160]
            continue
    raise RuntimeError(f"Gemini {model} failed on all {len(keys)} keys: {last_err}")


def gen_openrouter(model: str, system: str, user: str) -> str:
    import json as _json
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    for _attempt in (1, 2):
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "HTTP-Referer": "https://github.com/ethan-cole-fb-bot",
                     "X-Title": "ethan-cole-fb-bot",
                     "Content-Type": "application/json"},
            json={"model": model, "max_tokens": 500, "temperature": 0.5,
                  "reasoning": {"exclude": True},
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=90)
        d = r.json()
        if r.status_code != 429:
            break
        log("OpenRouter 429 rate-limited, waiting 45s and retrying once…")
        time.sleep(45)
    if r.status_code != 200:
        raise RuntimeError(f"OpenRouter {model} HTTP {r.status_code}: "
                           f"{_json.dumps(d)[:200]}")
    try:
        return d["choices"][0]["message"]["content"].strip()
    except Exception as ex:
        raise RuntimeError(f"OpenRouter {model} parse error: {ex}")


def sanitize(post: str) -> str:
    """Facebook renders no markdown: **bold** -> UPPERCASE, strip # headers,
    > quotes and ALL stray asterisks/backticks (bullets preserved as -).
    Never returns text containing * or ` ."""
    post = re.sub(r"\*\*(.+?)\*\*", lambda m: m.group(1).upper(), post)
    post = re.sub(r"__(.+?)__", lambda m: m.group(1).upper(), post)
    # markdown links [text](url) -> text
    post = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", post)
    post = re.sub(r"(?m)^#{1,6}(?=\s)", "", post)
    post = re.sub(r"(?m)^>\s?", "", post)
    post = re.sub(r"(?m)^(\s*[-•])\s*\*\s*", r"\1 ", post)
    # single-* emphasis *word* -> WORD (after ** already handled)
    post = re.sub(r"\*([^*]+)\*", lambda m: m.group(1).upper(), post)
    post = re.sub(r"_([^_]+)_", lambda m: m.group(1).upper(), post)
    # belt and suspenders: no asterisk or backtick may reach Facebook
    post = post.replace("*", "").replace("`", "")
    return post


def repair_post(post: str) -> str:
    """Auto-fix near-miss drafts: strip markdown, trim tags to 6 (brand
    first), cap length. Returns the repaired text; caller re-runs
    quality_check on it."""
    post = sanitize(post)
    # strip any LLM-written attribution lines (publisher owns attribution)
    post = re.sub(r"(?im)(?<![\w-])sources?\s*:[^#\n]*", "", post)
    post = re.sub(r"(?m)^[^\n]*[🔗📸][^\n]*$", "", post)
    # strip bare domains the URL ban missed (www.x, x.com/...)
    post = re.sub(r"(?i)\S*(www\.|[a-z0-9-]+\.(com|org|net|io))\S*", "", post)
    post = re.sub(r"[ \t]+", " ", post)
    post = re.sub(r"\n{3,}", "\n\n", post)
    tags = re.findall(r"#\w+", post)
    seen, kept = set(), []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            kept.append(t)
    brand = [t for t in kept if t.lower() == "#ethancole"]
    rest = [t for t in kept if t.lower() != "#ethancole"]
    kept = (brand[:1] + rest)[:6]
    if not kept:
        return post
    body = re.sub(r"#\w+", "", post)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    tag_block = " ".join(kept)
    if len(body) + len(tag_block) + 2 > 1000:
        budget = 1000 - len(tag_block) - 3
        cut = body[:budget]
        for sep in ("\n\n", ". ", "! ", "? "):
            i = cut.rfind(sep)
            if i > budget * 0.6:
                cut = cut[:i].rstrip()
                break
        body = cut
    return body + "\n\n" + tag_block


# Virality engine: 60% rage-bait, 40% serious. Rage is detected
# from proven traction (X likes/reposts, TG views) + conflict language.
# Content alone can contribute max 2 (never flips mode solo); engagement
# decides. Viral-mode posts decay slower (hot takes live for days) and get
# a spicier rewrite prompt. Facts stay exact — only the framing gets hot.
# The 60/40 ratio is enforced by apply_rage_mix (3 viral per 5 posts).
RAGE_WORDS = [
    "slams", "blasts", "destroys", "humiliates", "exposes", "warns",
    "threatens", "leaked", "leak", "scandal", "outrage", "roasts",
    "eviscerates", "crushes", "calls out", "fumes", "erupts", "fraud",
    "meltdown", "bloodbath", "unhinged", "terrifying", "disaster",
    "crash", "collapse", "plunge", "plummet", "tanks", "tumbles",
    "nosedive", "slump", "rout", "wipeout", "panic", "chaos", "turmoil",
    "backlash", "feud", "clash", "showdown", "ultimatum",
    "sues", "lawsuit", "probe", "resigns", "layoffs", "fired",
    "banned", "ban", "bubble", "ponzi", "dumps",
    "indictment", "indicted", "crackdown", "raid", "impeach", "veto",
    "ruling", "sentenced", "arrest", "coup", "invasion",
]


def apply_rage_mix(fresh: list, modes: list) -> str | None:
    """Enforce ~60% rage-bait mix: target RAGE_TARGET viral posts out of
    every 5 (default 3). Below target the best viral candidate gets
    +RAGE_BOOST (default 3, usually wins); above target the best serious
    candidate gets +2 to hold the serious floor. Returns log line or None."""
    viral_n = modes.count("viral")
    target = int(os.getenv("RAGE_TARGET", "3"))
    if viral_n < target:
        need, boost = "viral", int(os.getenv("RAGE_BOOST", "3"))
    elif viral_n >= target + 1:
        need, boost = "serious", 2
    else:
        return None
    for c in fresh:
        if c.get("mode", "serious") == need:
            c["score"] = round(c["score"] + boost, 1)
            fresh.sort(key=lambda c: c["score"], reverse=True)
            return (f"rage mix {viral_n}/5 viral: +{boost} to "
                    f"[{c['feed']}] {need} pick")
    return None


def viral_bonus(text: str, likes: int = 0, reposts: int = 0,
                replies: int = 0, views: int = 0) -> int:
    t = text.lower()
    b = min(2, sum(1 for w in RAGE_WORDS if w in t))
    b += min(3, (likes + 2 * reposts + 2 * replies) // 500)
    if views >= 20000:
        b += 2
    elif views >= 5000:
        b += 1
    return min(5, b)


SYSTEM_PROMPT_VIRAL = SYSTEM_PROMPT + """
VIRAL MODE (this story already has traction — squeeze it):
- Open with your hardest punch: caps, conflict, stakes. Name the winner and the loser.
- One sharp, opinionated closer line — raised eyebrow, not essay.
- End the body with a debate-sparking question OR a mic-drop line (viral mode only).
- Facts stay exact: spice the framing, never the facts. No invented quotes or numbers.
- Never explicitly ask for likes, shares, comments or follows — engagement
  bait violates monetization policy and can kill page eligibility."""


def rewrite_with_llm(candidate: dict) -> str:
    user_msg = USER_TEMPLATE.format(**candidate)
    system = (SYSTEM_PROMPT_VIRAL if candidate.get("mode") == "viral"
              else SYSTEM_PROMPT)
    chain: list[tuple[str, str]] = []
    if _gemini_keys():
        chain.append(("gemini",
                      os.getenv("GEMINI_MODEL", "gemini-2.5-flash")))
    if os.getenv("OPENROUTER_API_KEY", "").strip():
        chain.append(("openrouter",
                      os.getenv("OPENROUTER_MODEL",
                                "qwen/qwen3.8-27b:free")))
    if not chain:
        raise RuntimeError("No LLM key set (GEMINI_API_KEY or OPENROUTER_API_KEY)")
    errors = []
    for kind, model in chain:
        try:
            text = (gen_gemini(model, system, user_msg)
                    if kind == "gemini"
                    else gen_openrouter(model, system, user_msg))
            text = sanitize(text)  # strip markdown BEFORE QC so ** never passes
        except Exception as ex:
            errors.append(f"{model}: {ex}")
            continue
        if quality_check(text, candidate["title"]):
            first_fail = quality_check(text, candidate["title"])
            fixed = repair_post(text)
            if not quality_check(fixed, candidate["title"]):
                log(f"Rewrite OK via {model} (auto-repaired: {first_fail})")
                return fixed
            errors.append(f"{model} failed QC: {first_fail}")
            continue
        log(f"Rewrite OK via {model}")
        return text
    raise RuntimeError("All LLM providers failed: " + " | ".join(errors))


# Engagement bait: asking for likes/shares/comments violates Partner
# Monetization Policies and can permanently kill monetization eligibility.
# Debate-sparking questions are fine; explicit solicitation is rejected.
ENGAGEMENT_BAIT = [
    "comment below", "share this", "share if", "tag a friend",
    "like and share", "like if", "follow for more", "comment yes",
    "drop a comment", "type yes",
]


def quality_check(post: str, source_title: str) -> list[str]:
    problems = []
    if len(post) > 1000:
        problems.append("too long (>1000 chars)")
    if len(post) < 150:
        problems.append("too short (<150 chars, page data: shorts flop)")
    tags = re.findall(r"#\w+", post)
    if len(tags) == 0:
        problems.append("no hashtags")
    if len(tags) > MAX_HASHTAGS:
        problems.append(f"too many hashtags ({len(tags)})")
    if "http" in post:
        problems.append("contains URL (not allowed unless requested)")
    if re.search(r"(?i)\bwww\.|\.(com|org|net|io)\b", post):
        problems.append("contains bare domain (no URLs of any form)")
    if "*" in post or "`" in post:
        problems.append("contains markdown asterisk/backtick (FB shows it literally)")
    if any(p in post.lower() for p in ENGAGEMENT_BAIT):
        problems.append("engagement bait (kills monetization eligibility)")
    if re.search(r"(?i)(?<![\w-])sources?\s*:|🔗|📸", post):
        problems.append("contains attribution line (publisher appends it)")
    if re.search(r"(?m)^#{1,6}\s", post):
        problems.append("contains markdown header")
    # originality: post must not contain the full headline verbatim
    if source_title.strip() and len(source_title.strip()) >= 20 \
            and source_title.strip().lower() in post.lower():
        problems.append("copies headline verbatim")
    if re.search(r"\b\[.*\]|\(insert|TODO", post, re.I):
        problems.append("contains placeholder text")
    return problems


# ---------------------------------------------------------------- photos
# Every post goes out WITH a photo. Chain: source photo (X/TG) ->
# article og:image -> Wikimedia Commons fallback (keyless, editorial).
# (Google Images has no free API; this chain covers ~everything.)
# Upload is download-then-multipart so it never depends on FB fetching URLs.
def _download_image(url: str, timeout: int = 20, min_bytes: int = 5000):
    try:
        r = requests.get(url, timeout=timeout, stream=True,
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        ct = r.headers.get("Content-Type", "")
        if r.status_code != 200 or "image" not in ct:
            return None, None
        data = r.content
        if len(data) > 12000000 or len(data) < min_bytes:
            return None, None
        ext = ct.split("/")[-1].split(";")[0].strip() or "jpg"
        return data, ext
    except Exception:
        return None, None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def _cached_download(key: str, url: str, min_bytes: int = 5000):
    """Download once, reuse from .photo_cache forever after."""
    data = _photo_cache_get(key)
    if data is not None:
        return data, "jpeg"
    data, _ext = _download_image(url, min_bytes=min_bytes)
    if data:
        _photo_cache_put(key, data)
    return data, _ext


def _wikimedia_photo(query: str, cache_key: str = None):
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={"action": "query", "format": "json",
                    "generator": "search",
                    "gsrsearch": f"filetype:bitmap {query}",
                    "gsrnamespace": "6", "gsrlimit": "5",
                    "prop": "imageinfo", "iiprop": "url|size",
                    "iiurlwidth": "1200"},
            timeout=20, headers={"User-Agent": "ethan-cole-fb-bot/1.0"})
        pages = (r.json().get("query") or {}).get("pages") or {}
        for pg in pages.values():
            info = (pg.get("imageinfo") or [{}])[0]
            u = info.get("thumburl") or info.get("url")
            if u and not u.lower().endswith(".svg"):
                if cache_key:
                    ckey = cache_key
                    data = _photo_cache_get(ckey)
                    if data is None:
                        data, ext = _download_image(u)
                        if data:
                            _photo_cache_put(ckey, data)
                else:
                    data, ext = _download_image(u)
                if data:
                    return data, ext
    except Exception:
        pass
    return None, None


# Entity -> logo card. Exact Commons files verified live (Sep 2026);
# runtime search covers the rest. Logo cards are composited onto Ethan Cole
# branding so a text-only story (e.g. OpenAI news, no photo) still posts
# WITH a proper image — the page's own house pattern.
ENTITY_LOGOS = [
    (["openai", "chatgpt", "gpt-", "sora"],
     ["File:OpenAI Logo.png"], []),
    (["anthropic", "claude"],
     ["File:Anthropic Logo 2.webp"], []),
    (["nvidia", "nvda", "huang"],
     ["File:Logo-nvidia-transparent-PNG.png"], []),
    (["bitcoin", "btc"],
     ["File:Bitcoin logo.webp"], []),
    (["ethereum", "vitalik"],
     ["File:Ethereum Logo.png"], []),
    (["federal reserve", "fed", "powell", "warsh", "fomc", "eccles"],
     ["File:Eccles Building (26088200676).jpg"],
     ["Eccles Federal Reserve Building", "Federal Reserve headquarters"]),
    (["google", "gemini", "deepmind", "pichai"],
     [], ["Google G logo", "Google headquarters"]),
    (["meta ", "zuckerberg", "llama"],
     [], ["Meta Platforms logo", "Meta headquarters"]),
    (["tesla", "spacex"],
     ["File:Tesla logo.png"],
     ["Tesla logo", "SpaceX headquarters"]),
]

FEED_CREDIT = {
    "CNBC Top": "CNBC", "CNBC Economy": "CNBC", "Fed Press": "Federal Reserve",
    "CoinDesk": "CoinDesk", "FinancialJuice Squawk": "FinancialJuice",
    "TechCrunch AI": "TechCrunch", "The Verge AI": "The Verge",
    "MIT Tech Review AI": "MIT Tech Review",
}


def _font(size: int):
    from PIL import ImageFont
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "C:\\Windows\\Fonts\\arialbd.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _crop_bars(im):
    """Crop uniform top/bottom branding bars (letterbox/watermark strips)."""
    g = im.convert("L")
    W, H = g.size
    px = g.load()
    barreled = lambda y: (max(px[min(W - 1, int(W * (0.2 + i * 0.15))), y]
                              for i in range(5))
                          - min(px[min(W - 1, int(W * (0.2 + i * 0.15))), y]
                                for i in range(5))) < 10
    top = 0
    while top < H * 0.12 and barreled(top):
        top += 1
    bot = H - 1
    while bot > H * 0.88 and barreled(bot):
        bot -= 1
    if top > 4 or bot < H - 5:
        return im.crop((0, top, W, bot + 1))
    return im


def _footer(im, h: int = None):
    from PIL import ImageDraw
    W, H = im.size
    fh = h or max(46, H // 12)
    d = ImageDraw.Draw(im)
    d.rectangle([0, H - fh, W, H], fill=(0, 0, 0))
    d.text((18, H - fh + max(8, (fh - 26) // 2)),
           "ETHAN COLE  //  FINANCE + AI",
           font=_font(max(18, fh // 3)), fill=(255, 255, 255))
    return im


def _brand_image(data: bytes):
    """Debrand (crop uniform bars) + Ethan Cole footer. Returns JPEG bytes."""
    from PIL import Image
    buf = io.BytesIO()
    _footer(_crop_bars(Image.open(io.BytesIO(data)).convert("RGB"))) \
        .save(buf, "JPEG", quality=88)
    return buf.getvalue(), "jpeg"


def _logo_card(data: bytes):
    """Entity logo composited onto Ethan Cole card (1200x630)."""
    from PIL import Image
    try:
        logo = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None
    logo.thumbnail((760, 380))
    card = Image.new("RGB", (1200, 630), (11, 18, 32))
    card.paste(logo, ((1200 - logo.size[0]) // 2, (540 - logo.size[1]) // 2),
               logo)
    buf = io.BytesIO()
    _footer(card, 90).save(buf, "JPEG", quality=88)
    return buf.getvalue(), "jpeg"


def _commons_api(params: dict):
    last = None
    for attempt in range(3):  # Commons throttles shared cloud IPs hard
        try:
            r = requests.get("https://commons.wikimedia.org/w/api.php",
                             params={"action": "query", "format": "json",
                                     **params},
                             timeout=20,
                             headers={"User-Agent": "ethan-cole-fb-bot/1.0"})
            try:
                return r.json()
            except Exception:
                raise RuntimeError(f"Commons HTTP {r.status_code}: "
                                   f"{r.text[:120]}")
        except Exception as ex:
            last = ex
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Commons failed 3x: {last}")


def _commons_fetch(pages, prefer=()):
    pages = [p for p in pages
             if not (p.get("title") or "").lower().endswith((".svg", ".tif"))]
    if prefer:
        for p in pages:
            if any(w in (p.get("title") or "").lower() for w in prefer):
                pages = [p]
                break
    if not pages:
        return None, None
    info = (pages[0].get("imageinfo") or [{}])[0]
    return _download_image(info.get("thumburl") or info.get("url"),
                           min_bytes=500)  # logos are legitimately tiny


PHOTO_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               ".photo_cache")
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "assets")


def _photo_cache_get(key: str):
    try:
        p = os.path.join(PHOTO_CACHE_DIR, f"{key}.jpg")
        if os.path.exists(p) and os.path.getsize(p) > 1000:
            with open(p, "rb") as f:
                return f.read()
    except Exception:
        pass
    return None


def _photo_cache_put(key: str, data: bytes):
    try:
        os.makedirs(PHOTO_CACHE_DIR, exist_ok=True)
        with open(os.path.join(PHOTO_CACHE_DIR, f"{key}.jpg"), "wb") as f:
            f.write(data)
    except Exception:
        pass


# People -> face photo. Wikipedia portrait first (one cheap call each),
# Commons search fallback. Checked before company logos so a Powell story
# gets Powell's face, not a building.
PEOPLE_PHOTOS = [
    (["warsh", "kevin warsh"], "Kevin Warsh", ["Kevin Warsh Federal Reserve"]),
    (["trump", "donald trump"], "Donald Trump", ["Donald Trump official portrait"]),
    (["modi", "narendra modi"], "Narendra Modi", ["Narendra Modi portrait"]),
    (["bessent", "scott bessent"], "Scott Bessent", ["Scott Bessent Treasury"]),
    (["powell", "jerome powell"], "Jerome Powell", ["Jerome Powell Federal Reserve"]),
    (["hammack", "beth hammack"], "Beth Hammack", ["Beth Hammack Cleveland Fed"]),
    (["greer", "jamieson greer"], "Jamieson Greer", ["Jamieson Greer USTR"]),
    (["lutnick", "howard lutnick"], "Howard Lutnick", ["Howard Lutnick Commerce"]),
    (["xi jinping", "president xi"], "Xi Jinping", ["Xi Jinping portrait"]),
    (["lagarde", "christine lagarde"], "Christine Lagarde", ["Christine Lagarde ECB"]),
    (["vujcic"], "Boris Vujcic", ["Boris Vujcic central bank"]),
    (["putin", "vladimir putin"], "Vladimir Putin", ["Vladimir Putin portrait"]),    (["araghchi", "abbas araghchi"], "Abbas Araghchi", ["Abbas Araghchi foreign minister"]),
    (["pezeshkian"], "Masoud Pezeshkian", ["Masoud Pezeshkian president"]),
    (["netanyahu"], "Benjamin Netanyahu", ["Benjamin Netanyahu portrait"]),
    (["huang", "jensen huang"], "Jensen Huang", ["Jensen Huang Nvidia"]),
    (["altman", "sam altman"], "Sam Altman", ["Sam Altman OpenAI"]),
    (["amodei", "dario amodei"], "Dario Amodei", ["Dario Amodei Anthropic"]),
    (["musk", "elon musk"], "Elon Musk", ["Elon Musk portrait"]),
    (["reeves", "rachel reeves"], "Rachel Reeves", ["Rachel Reeves chancellor"]),
    (["merz", "friedrich merz"], "Friedrich Merz", ["Friedrich Merz chancellor"]),
    (["mohammed bin salman", "bin salman", "mbs"], "Mohammed bin Salman", ["Mohammed bin Salman portrait"]),
    (["zelensky", "zelenskyy"], "Volodymyr Zelenskyy", ["Volodymyr Zelenskyy portrait"]),
]


def _wiki_portrait(name: str):
    from urllib.parse import quote
    try:
        r = requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/"
            + quote(name.replace(" ", "_")),
            timeout=20, headers={"User-Agent": "ethan-cole-fb-bot/1.0"})
        d = r.json()
    except Exception:
        return None
    for k in ("originalimage", "thumbnail"):
        u = (d.get(k) or {}).get("source")
        if u:
            data, _ext = _download_image(u, min_bytes=500)
            if data:
                return data
    return None


def people_photo(candidate: dict):
    """(jpeg_bytes, ext) face card for a named person, else (None, None)."""
    text = f"{candidate.get('title', '')} {candidate.get('summary', '')}".lower()
    for keys, wiki, queries in PEOPLE_PHOTOS:
        if not any(k in text for k in keys):
            continue
        ckey = "face-" + (_slug(keys[0]) or "person")
        hit = _photo_cache_get(ckey)
        if hit:
            return hit, "jpeg"
        data = _wiki_portrait(wiki)
        if not data:
            for q in queries:
                time.sleep(2)
                try:
                    j = _commons_api({"generator": "search",
                                      "gsrsearch": f"filetype:bitmap {q}",
                                      "gsrnamespace": "6", "gsrlimit": "5",
                                      "prop": "imageinfo", "iiprop": "url|size",
                                      "iiurlwidth": "1200"})
                    pages = list(((j.get("query") or {}).get("pages") or {})
                                 .values())
                    data, _ext = _commons_fetch(
                        pages, prefer=("portrait", wiki.split()[0].lower()))
                    if data:
                        break
                except Exception as ex:
                    log(f"Commons portrait {q[:40]} failed: {ex}")
        if data:
            try:
                branded = _brand_image(data)
                _photo_cache_put(ckey, branded[0])
                return branded
            except Exception:
                pass
    return None, None


def entity_logo(candidate: dict):
    """(jpeg_bytes, ext) logo card for the story's main entity, else (None, None)."""
    text = f"{candidate.get('title', '')} {candidate.get('summary', '')}".lower()
    for keys, files, queries in ENTITY_LOGOS:
        if not any(k in text for k in keys):
            continue
        ckey = _slug(keys[0]) or "entity"
        hit = _photo_cache_get(ckey)
        if hit:
            return hit, "jpeg"
        # Bundled logos (assets/logos/): verified real files, zero network,
        # immune to Commons throttling on cloud IPs.
        bundled = os.path.join(ASSETS_DIR, "logos", f"{ckey}.png")
        if os.path.exists(bundled):
            try:
                with open(bundled, "rb") as f:
                    card = _logo_card(f.read())
                if card:
                    _photo_cache_put(ckey, card[0])
                    return card
            except Exception:
                pass
        attempts = ([("file", f) for f in files]
                    + [("search", q) for q in queries])
        for i, (kind, target) in enumerate(attempts):
            if i:
                time.sleep(2)  # Commons throttles aggressively; stay polite
            try:
                if kind == "file":
                    j = _commons_api({"titles": target, "prop": "imageinfo",
                                      "iiprop": "url|size", "iiurlwidth": "1200"})
                    pages = list(((j.get("query") or {}).get("pages") or {})
                                 .values())
                    data, _ext = _commons_fetch(pages)
                else:
                    j = _commons_api({"generator": "search",
                                      "gsrsearch": f"filetype:bitmap {target}",
                                      "gsrnamespace": "6", "gsrlimit": "8",
                                      "prop": "imageinfo", "iiprop": "url|size",
                                      "iiurlwidth": "1200"})
                    pages = list(((j.get("query") or {}).get("pages") or {})
                                 .values())
                    data, _ext = _commons_fetch(
                        pages,
                        prefer=("logo", "icon", "headquarters", "building"))
                if not data:
                    continue
                if kind == "file":
                    card = _logo_card(data)
                    if card:
                        _photo_cache_put(ckey, card[0])
                        return card
                else:
                    try:
                        branded = _brand_image(data)
                        _photo_cache_put(ckey, branded[0])
                        return branded
                    except Exception:
                        pass
            except Exception as ex:
                log(f"Commons {kind} {target[:40]} failed: {ex}")
                continue
    return None, None


def credit_for(feed: str, src: str) -> str:
    if src == "face":
        return "Wikipedia"
    if (src or "").startswith("wikimedia") or src == "entity-logo" \
            or (src or "").startswith("topic:"):
        return "Wikimedia Commons"
    if feed.startswith("X @"):
        return "@" + feed[3:]
    if feed.startswith("TG "):
        return feed[3:]
    return FEED_CREDIT.get(feed, feed)


def outlet_for(feed: str) -> str:
    """News outlet name for the end-of-post Source line."""
    if feed.startswith("X @"):
        return "@" + feed[3:] + " on X"
    if feed.startswith("TG "):
        return feed[3:] + " on Telegram"
    return FEED_CREDIT.get(feed, feed)


def add_credit(post: str, credit: str) -> str:
    """Credit the image source in the caption (never baked into the image)."""
    if not credit:
        return post
    line = chr(0x1F4F8) + ": " + credit  # camera emoji + source
    m = re.search(r"((?:#\w+\s*)+)\s*$", post)
    if m:
        return post[:m.start()].rstrip() + "\n" + line + "\n\n" + m.group(1).strip()
    return post.rstrip() + "\n\n" + line


def add_source(post: str, outlet: str) -> str:
    """Append the news-source line at the end (before hashtags). The LLM
    must never write its own source line — the publisher owns attribution."""
    if not outlet:
        return post
    line = chr(0x1F517) + " Source: " + outlet  # link emoji + outlet, no URL
    m = re.search(r"((?:#\w+\s*)+)\s*$", post)
    if m:
        return post[:m.start()].rstrip() + "\n" + line + "\n\n" + m.group(1).strip()
    return post.rstrip() + "\n\n" + line


# Curated topic photos (assets/topics/): hand-picked, visually verified.
# Safety net between entity logos and blind Wikimedia search — a CPI story
# gets Wall Street, an oil story gets pumpjacks, never a random image.
# File rotation per story link spreads variety across posts.
TOPIC_PHOTOS = [
    (["s&p", "nasdaq", "dow", "stock market", "nyse"],
     ["stocks-nyse.jpg", "market-hall.jpg", "wallstreet.jpg"]),
    (["wall street", "treasury", "bond yield", "ecb"],
     ["wallstreet.jpg", "stocks-nyse.jpg"]),
    (["mortgage", "rates", "yield", "bonds", "dollar"],
     ["wallstreet.jpg", "stocks-nyse.jpg"]),
    (["fed", "powell", "warsh", "fomc", "interest rate", "rate cut",
      "rate hike"],
     ["fed.jpg"]),
    (["bitcoin", "btc"], ["bitcoin.jpg"]),
    (["crypto", "ethereum", "defi", "hack", "exchange", "wallet"],
     ["bitcoin.jpg"]),
    (["gold"], ["gold.jpg"]),
    (["oil", "opec", "brent", "hormuz", "gas"], ["oil.jpg"]),
    (["gpu", "semiconductor", "ai chip", "artificial intelligence",
      "generative ai"],
     ["chips.jpg"]),
    (["inflation", "cpi", "jobs report", "gdp", "recession"],
     ["wallstreet.jpg", "market-hall.jpg"]),
]


def topic_photo(candidate: dict):
    """(bytes, ext, src) branded topic photo, else (None, None, None)."""
    text = f"{candidate.get('title', '')} {candidate.get('summary', '')}".lower()
    for keys, files in TOPIC_PHOTOS:
        if not any(k in text for k in keys):
            continue
        start = int(hashlib.sha256(
            candidate.get("link", "").encode()).hexdigest(), 16) % len(files)
        for off in range(len(files)):
            fn = files[(start + off) % len(files)]
            p = os.path.join(ASSETS_DIR, "topics", fn)
            if not os.path.exists(p):
                continue
            try:
                with open(p, "rb") as f:
                    branded, ext = _brand_image(f.read())
                return branded, ext, f"topic:{fn}"
            except Exception:
                continue
    return None, None, None


def _big_enough(data: bytes) -> bool:
    """Reject tiny thumbnails from source/og photos (min 250k px)."""
    try:
        from PIL import Image
        w, h = Image.open(io.BytesIO(data)).size
        return w * h >= int(os.getenv("MIN_PHOTO_PX", "250000"))
    except Exception:
        return False


def find_photo(candidate: dict):
    """(bytes, ext, src). Every image gets debranded + Ethan Cole footer;
    logo card when the story names an entity but has no photo."""
    raw = None  # (data, src)
    if candidate.get("photo_url"):
        key = "src-" + hashlib.sha256(
            candidate["photo_url"].encode()).hexdigest()[:16]
        data, _ext = _cached_download(key, candidate["photo_url"])
        if data:
            raw = (data, "source")
    link = candidate.get("link", "")
    if not raw and link.startswith("http") and "x.com" not in link \
            and "t.me" not in link:
        try:
            r = requests.get(link, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            if r.status_code == 200:
                m = re.search(
                    r'<meta[^>]+property=["\']og:image["\'][^>]+'
                    r'content=["\']([^"\']+)', r.text)
                if not m:
                    m = re.search(
                        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+'
                        r'property=["\']og:image["\']', r.text)
                if m:
                    u = html.unescape(m.group(1))
                    key = "og-" + hashlib.sha256(u.encode()).hexdigest()[:16]
                    data, _ext = _cached_download(key, u)
                    if data:
                        raw = (data, "og:image")
        except Exception:
            pass
    if raw and not _big_enough(raw[0]):
        log("Source/og photo too small, falling through to curated photos")
        raw = None
    if not raw:
        face = people_photo(candidate)
        if face[0]:
            return face[0], face[1], "face"
    if not raw:
        card = entity_logo(candidate)
        if card[0]:
            return card[0], card[1], "entity-logo"
    if not raw:
        timg, text_, tsrc = topic_photo(candidate)
        if timg:
            return timg, text_, tsrc
    if not raw:
        queries = [k for k in (candidate.get("keywords") or [])
                   if not k.startswith("+")][:3]
        if not queries:
            queries = ["stock market", "artificial intelligence"]
        for q in queries:
            data, _ext = _wikimedia_photo(q, cache_key=f"wiki-{_slug(q)}")
            if data:
                raw = (data, f"wikimedia:{q}")
                break
    if not raw:
        return None, None, None
    try:
        branded, ext = _brand_image(raw[0])
        return branded, ext, raw[1]
    except Exception:
        return raw[0], "jpeg", raw[1]


# ---------------------------------------------------------------- facebook publish
# ---------------------------------------------------------------- video posts
# DAILY VIDEO RULE: at least one reel/video post per day. Prefers
# bridgemindai live model tests, else any scored video (X mp4 / TG mp4).
def _download_video(url: str):
    try:
        r = requests.get(url, timeout=180, stream=True,
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        if r.status_code != 200:
            return None
        data = r.content
        if len(data) > 250000000 or len(data) < 50000:
            log(f"Video size out of range: {len(data)} bytes")
            return None
        if not _looks_like_video(data):
            log("Video bytes are not mp4/webm (likely an error page), rejecting")
            return None
        return data
    except Exception as ex:
        log(f"Video download failed: {ex}")
        return None


def _looks_like_video(data: bytes) -> bool:
    """Magic-bytes gate: mp4 (ftyp at offset 4) or webm (EBML header)."""
    if not data or len(data) < 12:
        return False
    return data[4:8] == b"ftyp" or data[:4] == b"\x1aE\xdf\xa3"


def publish_video_to_facebook(video_bytes: bytes, description: str) -> str:
    page_id = os.getenv("FB_PAGE_ID", "").strip()
    token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    if not page_id or not token:
        raise RuntimeError("FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not set")
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}/videos"
    files = {"file": ("video.mp4", video_bytes, "video/mp4")}
    data = {"description": description, "access_token": token}
    r = requests.post(url, files=files, data=data, timeout=300)
    try:
        resp = r.json()
    except Exception:
        raise RuntimeError(f"Facebook non-JSON response {r.status_code}: "
                           f"{r.text[:300]}")
    if r.status_code != 200 or "error" in resp:
        raise RuntimeError(f"Facebook error: {json.dumps(resp)[:500]}")
    return resp.get("post_id") or resp.get("id", "")


def publish_photo_to_facebook(image_bytes: bytes, ext: str,
                                caption: str) -> str:
    page_id = os.getenv("FB_PAGE_ID", "").strip()
    token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    if not page_id or not token:
        raise RuntimeError("FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not set")
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}/photos"
    files = {"source": (f"photo.{ext}", image_bytes, f"image/{ext}")}
    data = {"caption": caption, "access_token": token}
    r = requests.post(url, files=files, data=data, timeout=60)
    try:
        resp = r.json()
    except Exception:
        raise RuntimeError(f"Facebook non-JSON response {r.status_code}: "
                           f"{r.text[:300]}")
    if r.status_code != 200 or "error" in resp:
        raise RuntimeError(f"Facebook error: {json.dumps(resp)[:500]}")
    return resp.get("post_id") or resp.get("id", "")


def publish_to_facebook(message: str) -> str:
    page_id = os.getenv("FB_PAGE_ID", "").strip()
    token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    if not page_id or not token:
        raise RuntimeError("FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not set")
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}/feed"
    r = requests.post(url, json={"message": message, "access_token": token}, timeout=20)
    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f"Facebook non-JSON response {r.status_code}: {r.text[:300]}")
    if r.status_code != 200 or "error" in data:
        raise RuntimeError(f"Facebook error: {json.dumps(data)[:500]}")
    return data.get("id", "")


def corroboration_boost(candidates: list) -> int:
    """Cross-source verification: a story appearing in 2+ independent feeds
    gets +2 (independent confirmation beats single-source claims). Returns
    the number of corroborated stories. Social-only single-source items keep
    their score — the rewrite prompt forces 'reportedly' framing for those."""
    groups: dict = {}
    for c in candidates:
        key = re.sub(r"[^a-z0-9 ]", "",
                     (c.get("title") or "").lower()).split()[:10]
        key = " ".join(key)
        if len(key) >= 20:
            groups.setdefault(key, {"feeds": set(), "items": []})
            groups[key]["feeds"].add(c.get("feed", ""))
            groups[key]["items"].append(c)
    n = 0
    for g in groups.values():
        if len(g["feeds"]) >= 2:
            n += 1
            for c in g["items"]:
                c["score"] = round(c["score"] + 2, 1)
                if "+corroborated" not in (c.get("keywords") or []):
                    (c.setdefault("keywords", [])).append("+corroborated")
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return n


# Comment review: read engagement + comments on OUR posts to steer the algo.
# Cheap (<=8 posts x 50 comments, at most once/day). Tracks questions the
# audience asks, praise, anger (rage working?) and fake-claims (credibility
# problem -> tighten verification). Stored in state["comment_review"].
PRAISE_WORDS = [
    "thanks", "thank", "great", "love", "awesome", "informative",
    "helpful", "insightful", "brilliant", "fire",
]
FAKE_WORDS = [
    "fake", "false", "lie", "lies", "lying", "misinformation",
    "disinformation", "propaganda", "wrong", "cap",
]


def review_comments(state: dict) -> dict:
    rev = state.setdefault("comment_review", {})
    today = datetime.now(timezone.utc).date().isoformat()
    if rev.get("updated") == today:
        return rev
    token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    if not token:
        return rev
    items = [h for h in state.get("history", [])[-8:] if h.get("fb_id")]
    agg = {"posts": 0, "comments": 0, "likes": 0, "questions": 0,
           "praise": 0, "anger": 0, "fake_claims": 0, "by_topic": {},
           "sample_questions": []}
    for h in items:
        try:
            r = requests.get(
                f"https://graph.facebook.com/{FB_API_VERSION}/{h['fb_id']}"
                f"/comments",
                params={"fields": "message,like_count",
                        "limit": 50, "access_token": token},
                timeout=15)
            d = r.json()
            if r.status_code != 200 or "error" in d:
                continue
            comments = d.get("data", [])
            agg["posts"] += 1
            for cm in comments:
                msg = (cm.get("message") or "")
                t = msg.lower()
                if not t.strip():
                    continue
                agg["comments"] += 1
                agg["likes"] += cm.get("like_count", 0) or 0
                if "?" in msg:
                    agg["questions"] += 1
                    if len(agg["sample_questions"]) < 3 and len(msg) < 200:
                        agg["sample_questions"].append(msg.strip())
                if any(w in t for w in PRAISE_WORDS):
                    agg["praise"] += 1
                if any(w in t for w in RAGE_WORDS):
                    agg["anger"] += 1
                if any(w in t for w in FAKE_WORDS):
                    agg["fake_claims"] += 1
                    for tp in h.get("topics", []) or ["unknown"]:
                        agg["by_topic"][tp] = agg["by_topic"].get(tp, 0) + 1
        except Exception as ex:
            log(f"comment review: skip {h.get('fb_id')}: {ex}")
            continue
    agg["updated"] = today
    state["comment_review"] = agg
    log(f"comment review: {agg['posts']} posts, {agg['comments']} comments, "
        f"Q={agg['questions']} praise={agg['praise']} anger={agg['anger']} "
        f"fake={agg['fake_claims']}")
    if agg["fake_claims"] >= 3:
        log("WARNING: audience crying fake — tighten verification, "
            "check corroboration + reportedly framing")
    return agg


def floor_plan(posts_today: int, hour: int):
    """Daily post floor (MIN_POSTS_PER_DAY, default 4).

    Returns (score_discount, catchup). Behind pace -> discount lowers the
    publish bar toward FLOOR_MIN_SCORE (default 2); after
    FLOOR_DEADLINE_HOUR UTC (default 21) with the floor unmet, catchup
    mode shrinks the cooldown so the day still hits its minimum."""
    floor = int(os.getenv("MIN_POSTS_PER_DAY", "4"))
    if posts_today >= floor:
        return 0, False
    expected = (hour * floor) // 24
    discount = 0
    if posts_today < expected:
        discount = min(4, 2 * (expected - posts_today))
    catchup = hour >= int(os.getenv("FLOOR_DEADLINE_HOUR", "21"))
    if catchup:
        discount = max(
            discount,
            int(os.getenv("MIN_PUBLISH_SCORE", "6"))
            - int(os.getenv("FLOOR_MIN_SCORE", "2")))
    return discount, catchup


def fb_token_ok() -> bool:
    """Fail fast if the Page token is dead (saves LLM quota and log spam)."""
    page_id = os.getenv("FB_PAGE_ID", "").strip()
    token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    if not page_id or not token:
        return False
    try:
        r = requests.get(
            f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}",
            params={"fields": "id", "access_token": token}, timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def main() -> int:
    max_age = int(os.getenv("MAX_AGE_MINUTES", "2880"))  # 2 days max
    state_file = os.getenv("STATE_FILE", "posted.json")
    dry_run = os.getenv("DRY_RUN", "") == "1"

    state = load_state(state_file)
    posted = set(state.get("posted_hashes", []))
    now = datetime.now(timezone.utc)

    # Fail fast on a dead FB token (they expire ~60 days): no point burning
    # news-fetch + LLM quota when publishing is impossible. Dry runs proceed.
    if not dry_run and not fb_token_ok():
        log("FB token invalid/expired — do the one-time undying setup "
            "(README section 3) and update the FB_PAGE_ACCESS_TOKEN "
            "secret. Skipping this run.")
        return 5

    # Self-improvement: refresh engagement multipliers (max once/day),
    # then score this run with them. The algo gets smarter every day.
    # Seed history once from the pre-tuner diesel post.
    if not state.get("history") and (state.get("last_post") or {}).get("fb_id"):
        lp = state["last_post"]
        _s, _hits = score_entry(lp.get("title", ""), "")
        state["history"] = [{
            "fb_id": lp["fb_id"],
            "topics": sorted({KW_TO_TOPIC[k] for k in _hits
                              if k in KW_TO_TOPIC}),
            "at": lp.get("at", now.isoformat()),
        }]
    _TUNER.update(tune_from_engagement(state))
    review_comments(state)
    save_state(state_file, state)

    # DAILY FLOOR: at least MIN_POSTS_PER_DAY (default 4) every day, always.
    # Behind pace -> publish bar drops; late-day + unmet -> catchup burst.
    today = now.date().isoformat()
    day_counts = state.get("day_counts", {})
    posts_today = day_counts.get(today, 0)
    floor = int(os.getenv("MIN_POSTS_PER_DAY", "4"))
    discount, catchup = floor_plan(posts_today, now.hour)
    eff_gap = 20 if catchup else int(os.getenv("MIN_POST_GAP_MINUTES", "90"))
    eff_bar = max(int(os.getenv("FLOOR_MIN_SCORE", "2")),
                  int(os.getenv("MIN_PUBLISH_SCORE", "6")) - discount)
    log(f"floor: {posts_today}/{floor} posts today, bar={eff_bar}, "
        f"gap={eff_gap}{' CATCHUP' if catchup else ''}")

    # Cooldown: never post more often than the effective gap (anti-spam:
    # cron runs every 20 min but the page posts ~11/day, not 72).
    # FORCE_POST=1 (manual "post now" runs) skips the cooldown.
    if os.getenv("FORCE_POST", "") == "1":
        log("FORCE_POST=1, cooldown skipped (manual run)")
    last = state.get("last_post") if isinstance(state.get("last_post"), dict) else None
    if last and last.get("at") and os.getenv("FORCE_POST", "") != "1":
        try:
            gap = (now - datetime.fromisoformat(last["at"])).total_seconds() / 60
            if gap < eff_gap:
                log(f"Cooldown: last post {gap:.0f} min ago. Skipping.")
                return 0
        except Exception:
            pass

    # Daily cap, matching the page's real cadence (~11/day).
    if posts_today >= int(os.getenv("MAX_POSTS_PER_DAY", "11")):
        log("Daily cap reached. Skipping.")
        return 0

    candidates = (fetch_candidates(max_age) + fetch_x_candidates(max_age)
                  + fetch_tg_candidates(max_age))
    candidates.sort(key=lambda c: c["score"], reverse=True)
    log(f"{len(candidates)} candidates passed filter")
    n_corr = corroboration_boost(candidates)
    if n_corr:
        log(f"Corroborated: {n_corr} stories confirmed by 2+ feeds (+2)")
    fresh = [c for c in candidates if item_hash(c["link"], c["title"]) not in posted]
    # Cluster guard: squawk wires repeat one story 20+ ways (e.g. 20 Hammack
    # headlines). Skip anything near-identical to a recently posted title.
    recent = state.get("recent_titles", [])

    def _too_similar(t: str) -> bool:
        tl = t.lower()
        return any(difflib.SequenceMatcher(None, tl, r.lower()).ratio() > 0.75
                   for r in recent)

    fresh = [c for c in fresh if not _too_similar(c["title"])]
    # Within-run dedup: same story twice in one sweep (reposts) -> keep best.
    seen: list[str] = []
    deduped = []
    for c in fresh:
        if not any(difflib.SequenceMatcher(None, c["title"].lower(), s.lower()
                                           ).ratio() > 0.85 for s in seen):
            deduped.append(c)
            seen.append(c["title"])
    fresh = deduped
    # VERIFIED-ONLY RULE: never publish an item whose link failed the
    # reachability check (X/TG items are verified by platform existence).
    dropped = sum(1 for c in fresh if not c.get("verified"))
    if dropped:
        log(f"Dropping {dropped} unverified candidates.")
        fresh = [c for c in fresh if c.get("verified")]
    log(f"{len(fresh)} fresh (not yet posted)")

    if not fresh:
        log("Nothing new that fits criteria. Skipping.")
        return 0

    # Sweep report: top candidates across every source, then max 1 post.
    for i, c in enumerate(fresh[:5]):
        log(f"sweep #{i + 1} [{c['feed']}] score={c['score']} "
            f"age={c['age_min']}m: {c['title'][:100]}")
    # max 1 post per run to avoid spamming the Page, and only if it
    # clears the learned quality bar (weak stories stay drafts)
    # DAILY VIDEO RULE: at least one reel/video post per day. If none posted
    # today and a video candidate clears the bar, it becomes this run's post
    # (prefers bridgemindai live model tests).
    if state.get("last_video_post") != today:
        vids = [c for c in fresh if c.get("video_url")]
        vids.sort(key=lambda c: (0 if "bridgemindai" in c.get("feed", "")
                                 else 1, -c["score"]))
        # DAILY VIDEO GUARANTEE: normal bar is MIN_VIDEO_SCORE (default 4),
        # but after VIDEO_DEADLINE_HOUR UTC (default 20) the bar drops to
        # VIDEO_DEADLINE_SCORE (default 1) so the day still gets its reel.
        min_video_score = int(os.getenv("MIN_VIDEO_SCORE", "4"))
        if now.hour >= int(os.getenv("VIDEO_DEADLINE_HOUR", "20")):
            min_video_score = min(
                min_video_score, int(os.getenv("VIDEO_DEADLINE_SCORE", "1")))
            log(f"Video deadline hour reached, bar lowered to {min_video_score}")
        if vids and vids[0]["score"] >= min_video_score:
            vpick = vids[0]
            log(f"VIDEO pick [{vpick['feed']}] score={vpick['score']}: "
                f"{vpick['title'][:100]}")
            try:
                vpost = sanitize(rewrite_with_llm(vpick))
                vprobs = quality_check(vpost, vpick["title"])
            except Exception as ex:
                vpost, vprobs = None, [str(ex)[:100]]
            if vpost and not vprobs:
                vpost = add_credit(vpost, credit_for(vpick["feed"], "video"))
                vpost = add_source(vpost, outlet_for(vpick["feed"]))
                print("--- VIDEO POST ---\n" + vpost + "\n------------")
                vh = item_hash(vpick["link"], vpick["title"])
                vid = _download_video(vpick["video_url"])
                if dry_run:
                    log(f"DRY_RUN=1, video not publishing. "
                        f"({len(vid or b'')} bytes)")
                    return 0
                if not vid:
                    log("Video download failed, falling through to normal pick")
                else:
                    try:
                        post_id = publish_video_to_facebook(vid, vpost)
                        log(f"Published VIDEO! FB id={post_id}")
                    except Exception as ex:
                        log(f"Video publish failed: {ex}")
                        return 4
                    posted.add(vh)
                    state["posted_hashes"] = sorted(posted)[-500:]
                    day_counts[today] = day_counts.get(today, 0) + 1
                    state["day_counts"] = {k: v for k, v in day_counts.items()
                                           if k >= today}
                    recent = state.get("recent_titles", [])
                    recent.append(vpick["title"])
                    state["recent_titles"] = recent[-15:]
                    state["last_post"] = {
                        "hash": vh, "fb_id": post_id,
                        "title": vpick["title"], "link": vpick["link"],
                        "mode": vpick.get("mode", "serious"), "kind": "video",
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
                    hist = state.get("history", [])
                    hist.append({
                        "fb_id": post_id,
                        "topics": sorted({KW_TO_TOPIC[k]
                                          for k in vpick["keywords"]
                                          if k in KW_TO_TOPIC}),
                        "mode": vpick.get("mode", "serious"),
                        "at": state["last_post"]["at"],
                    })
                    state["history"] = hist[-50:]
                    state["last_video_post"] = today
                    save_state(state_file, state)
                    return 0
            else:
                log(f"Video draft failed QC: {vprobs}")
        else:
            log("No video candidate clears the bar today (yet).")
    # 60% RAGE MIX: target 3 viral posts out of every 5 (see apply_rage_mix).
    modes = [h.get("mode", "serious") for h in state.get("history", [])[-5:]]
    mix_log = apply_rage_mix(fresh, modes)
    if mix_log:
        log(mix_log)
    pick = fresh[0]
    min_score = eff_bar  # daily floor may have lowered the bar
    if pick["score"] < min_score:
        log(f"Top pick score={pick['score']} < {min_score}. Too weak, skipping.")
        return 0
    log(f"Picked [{pick['feed']}] score={pick['score']}: {pick['title'][:120]}")

    try:
        post = rewrite_with_llm(pick)
    except Exception as ex:
        log(f"Rewrite failed: {ex}")
        return 2

    post = sanitize(post)  # FB has no markdown: **bold** -> CAPS etc.
    problems = quality_check(post, pick["title"])
    if problems:
        log(f"Quality check FAILED: {problems}")
        print("--- DRAFT (rejected) ---\n" + post)
        return 3
    print("--- POST (pre-credit) ---\n" + post + "\n------------")

    h = item_hash(pick["link"], pick["title"])
    img, ext, src = find_photo(pick)
    post = add_credit(post, credit_for(pick["feed"], src))
    post = add_source(post, outlet_for(pick["feed"]))
    log(f"Photo: {src or 'none'} | credit added")
    if dry_run:
        log("DRY_RUN=1, not publishing.")
        return 0
    try:
        if img:
            post_id = publish_photo_to_facebook(img, ext, post)
            log(f"Published WITH PHOTO ({src})! FB id={post_id}")
        else:
            log("WARNING: no photo found anywhere, posting text-only.")
            post_id = publish_to_facebook(post)
            log(f"Published (text-only)! FB post id={post_id}")
    except Exception as ex:
        log(f"Publish failed: {ex}")
        return 4

    posted.add(h)
    state["posted_hashes"] = sorted(posted)[-500:]
    day_counts[today] = day_counts.get(today, 0) + 1
    state["day_counts"] = {k: v for k, v in day_counts.items() if k >= today}
    recent = state.get("recent_titles", [])
    recent.append(pick["title"])
    state["recent_titles"] = recent[-15:]
    state["last_post"] = {
        "hash": h, "fb_id": post_id,
        "title": pick["title"], "link": pick["link"],
        "mode": pick.get("mode", "serious"),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    hist = state.get("history", [])
    hist.append({
        "fb_id": post_id,
        "topics": sorted({KW_TO_TOPIC[k] for k in pick["keywords"]
                          if k in KW_TO_TOPIC}),
        "mode": pick.get("mode", "serious"),
        "at": state["last_post"]["at"],
    })
    state["history"] = hist[-50:]
    save_state(state_file, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
