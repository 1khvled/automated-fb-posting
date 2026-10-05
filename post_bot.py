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
  MAX_AGE_MINUTES=1440 — only consider news newer than this (default 1440 = 24h)
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
from datetime import datetime, timedelta, timezone
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
                "treasury", "bond yield", "ecb", "imf", "price target",
                "analyst", "buy rating", "overweight", "underweight",
                "initiated coverage", "initiates coverage", "13f",
                "insider", "form 4", "section 16"], 3),
    "ai": (["openai", "anthropic", "nvidia", "gpu", "llm", "chatgpt", "claude",
            "gemini", "copilot", "artificial intelligence", "generative ai",
            "ai chip", "ai model", "ai funding", "ai startup",
            "semiconductor", "deepseek", "mistral", "grok", "llama"], 3),
    "inflation": (["inflation", "cpi", "ppi", "jobs report", "payrolls",
                   "unemployment", "gdp", "recession"], 2),
    "fed": (["fed", "federal reserve", "interest rate", "rate cut",
             "rate hike"], 1),
    "power": (["trump", "maga", "white house", "tariff", "executive order",
               "supreme court", "congress", "senate", "election",
               "republican", "democrat", "liberal", "woke", "biden",
               "vance", "modi", "india", "putin", "xi jinping",
                               "netanyahu", "zelensky", "pelosi", "schumer", "mcconnell",
                "mike johnson", "jeffries", "aoc", "ocasio", "cruz",
                "rubio", "bernie", "elizabeth warren", "newsom",
                "abbott"], 3),
}

# Famous large-cap stocks (roughly $50B+ market cap). Analyst-rating posts
# only pass the gate when they name one of these (ticker or company).
# Short tickers use (T)/$T forms so "V" doesn't match every sentence.
FAMOUS_STOCKS = [
    ["aapl", "apple"], ["msft", "microsoft"], ["nvda", "nvidia"],
    ["googl", "goog", "google", "alphabet"], ["amzn", "amazon"],
    ["meta", "facebook"], ["tsla", "tesla"],
    ["brk", "berkshire"], ["avgo", "broadcom"], ["jpm", "jpmorgan"],
    ["xom", "exxon"], ["eli lilly", "w:lly"], ["(v)", "$v", "visa"],
    ["mastercard"], ["orcl", "oracle"], ["nflx", "netflix"],
    ["costco"], ["wmt", "walmart"], ["amd"],
    ["jnj", "johnson"], ["bank of america", "w:bac"],
    ["gs", "goldman"], ["(ms)", "$ms", "morgan stanley"],
    ["(c)", "$c", "citi", "citigroup"], ["wfc", "wells fargo"],
    ["axp", "american express"], ["blk", "blackrock"], ["schw", "schwab"],
    ["unh", "unitedhealth"], ["mrk", "merck"], ["abbv", "abbvie"],
    ["pfe", "pfizer"], ["tmo", "thermo fisher"], ["abt", "abbott"],
    ["dhr", "danaher"], ["amgn", "amgen"], ["gild", "gilead"],
    ["vrtx", "vertex"], ["zts", "zoetis"], ["(ci)", "$ci", "cigna"],
    ["home depot", "w:hd"], ["mcd", "mcdonald"], ["sbux", "starbucks"],
    ["lowe"], ["tjx", "tj maxx"], ["booking"],
    ["marriott"], ["cvx", "chevron"], ["conocophillips", "w:cop"],
    ["pg", "procter"], ["coca-cola", "coca cola", "w:ko"], ["pepsi"],
    ["philip morris"], ["(mo)", "$mo", "altria"],
    ["(t)", "$t", "at&t"], ["vz", "verizon"], ["tmus", "t-mobile"],
    ["cmcsa", "comcast"], ["crm", "salesforce"], ["adbe", "adobe"],
    ["servicenow"], ["intc", "intel"], ["qcom", "qualcomm"],
    ["txn", "texas instruments"], ["amat", "applied materials"],
    ["lrcx", "lam research"], ["micron", "w:mu"], ["klac", "kla"],
    ["mrvl", "marvell"], ["arm holdings", "w:arm"], ["snps", "synopsys"],
    ["cdns", "cadence"], ["pltr", "palantir"], ["coin", "coinbase"],
    ["shopify", "w:shop"], ["uber"], ["abnb", "airbnb"], ["disney", "w:dis"],
    ["nke", "nike"], ["tsm", "taiwan semi"], ["asml"],
    ["baba", "alibaba"], ["spotify", "w:spot"], ["block", "w:sq"],
    ["pypl", "paypal"], ["ibm"], ["csco", "cisco"], ["acn", "accenture"],
    ["ge aerospace", "w:ge"], ["honeywell"], ["caterpillar", "w:cat"],
    ["deere", "john deere"], ["lmt", "lockheed"], ["rtx"],
    ["united parcel", "(ups)", "$ups", "ups earnings", "ups stock",
     "ups cuts", "ups results", "ups guides"], ["fdx", "fedex"], ["toyota", "w:tm"], ["gm", "general motors"],
    ["panw", "palo alto"], ["crwd", "crowdstrike"], ["snow", "snowflake"],
    ["cloudflare"], ["dell"], ["hood", "robinhood"],
    ["nxpi", "nxp"],
    ["w:ubs", "ubs group"],
]

# Famous 13F filers: only their filings pass the gate (quarterly waves
# are 90% unknown funds).
FAMOUS_FILERS = [
    "berkshire", "buffett", "weschler", "combs", "bridgewater", "dalio",
    "duquesne", "druckenmiller", "pershing", "ackman", "elliott",
    "singer", "citadel", "griffin", "baupost", "klarman", "third point",
    "loeb", "greenlight", "einhorn", "icahn", "soros", "renaissance",
    "simons", "two sigma", "shaw", "apollo", "blackstone", "schwarzman",
    "kkr", "kravis", "carlyle", "brookfield", "viking", "halvorsen",
    "lone pine", "mandel", "tiger global", "coleman", "coatue", "laffont",
    "scion", "burry", "starboard", "trian", "peltz", "altimeter",
    "gerstner",
]

# $500B+ mega-caps (first keywords of FAMOUS_STOCKS entries). Insider
# trades only post on these names.
MEGA_TICKERS = {"aapl", "msft", "nvda", "amzn", "googl", "meta", "tsla",
                "brk", "avgo", "lly", "tsm", "(v)", "mastercard", "xom",
                "orcl", "nflx", "cost", "wmt", "jpm"}


def _mega_stock(text: str) -> bool:
    return any(k in text for e in FAMOUS_STOCKS if e[0] in MEGA_TICKERS
               for k in e)


# Source trust tiers: original reporting and primary sources outrank
# secondhand squawk. Small (+1) but decisive at the bar.
FEED_TRUST = {
    "CNBC Top": 1, "CNBC Economy": 1, "CNBC Politics": 1,
    "Fed Press": 1, "BBC World": 1, "AlJazeera": 1, "CoinDesk": 1,
    "TechCrunch AI": 1, "The Verge AI": 1, "MIT Tech Review AI": 1,
    "X @OpenAI": 1, "X @AnthropicAI": 1, "X @GoogleDeepMind": 1,
    "X @AIatMeta": 1,
}


def feed_trust_bonus(feed: str) -> int:
    return FEED_TRUST.get(feed, 0)


# Format bonuses learned from the page's top-8 posts:
# model launches/demos (#1 post: Opus one-shotting a game), security
# breaches (#3: Gemini hack), hard numbers/specs, genuine breaking news.
# Shared analyst-action detector: bank ratings on stocks. Used for the
# format bonus AND the famous-stock gate below.
ANALYST_PAT = re.compile(r"price target|upgrade[ds]?|downgrade[ds]?|"
                         r"initiat\w*( coverage)?|overweight|underweight|"
                         r"buy rating|raises .* target", re.I)

# 13F filings + insider trades detectors (gated to famous names below).
F13_PAT = re.compile(r"13\s?f[\s\-]?(hr)?\b|13f filing|files? 13f", re.I)
INSIDER_PAT = re.compile(
    r"insider (buy|bought|buying|purchase|sell|sold|selling)|"
    r"(ceo|cfo|chairman|founder|director) (buys|bought|purchases|sells|sold)|"
    r"(buys|bought|purchases|sells|sold|unloads|offloads|dumps) (shares|stock)|"
    r"shares? worth \$|cluster buy|form 4\b|section 16", re.I)

FORMAT_BONUS = [
    (re.compile(r"launch|unveil|release|demo|one-shot|gpt-\d|opus|gro[kq]", re.I),
     3, "launch/demo"),
    (re.compile(r"hack|breach|leak", re.I), 2, "security"),
    (re.compile(r"\$\d|\d+%|\d+\.\d+%|billion|million|record|all-time high", re.I),
     2, "hard-numbers"),
    (re.compile(r"breaking|just in", re.I), 1, "breaking"),
    (ANALYST_PAT, 2, "analyst-call"),
    (F13_PAT, 2, "13f-filing"),
    (INSIDER_PAT, 2, "insider-trade"),
]

EXCLUDE = [
    "horoscope", "celebrity breakup", "kardashian", "football transfer",
    "premier league", "cricket score", "lottery winner", "giveaway",
    "discount code", "coupon", "porn", "casino bonus",
]
CONFLICT_PAT = re.compile(
    r"hamas|hezbollah|houthi|hostage|gaza|\bidf\b|airstrike|ceasefire|"
    r"genocide|war crime", re.I)
MARKET_ANGLE_PAT = re.compile(
    r"market|stock|s&p|nasdaq|bitcoin|crypto|oil|gold|dollar|"
    r"tariff|trade|jobs|gdp|inflation|fed|yield|mortgage|"
    r"wall street|sanction|embargo|hormuz|opec|brent|crude|"
    r"calls|puts|options|buys|bought|purchase|disclosure|13f|insider|"
    r"price target|filing|shares", re.I)

# Engagement tuner: multipliers learned from OUR OWN posts' performance.
# tune_from_engagement() refreshes them at most once/day (cheap: <=20 calls).
_TUNER: dict = {}
KW_TO_TOPIC = {k: t for t, (kws, _w) in TOPIC_WEIGHTS.items() for k in kws}


def _post_engagement(fb_id: str):
    page_token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{fb_id}"
    r = requests.get(
        url,
        params={"fields": "likes.summary(true),comments.summary(true),shares",
                "access_token": page_token},
        timeout=15)
    d = r.json()
    if (r.status_code != 200 or "error" in d) \
            and "share" in json.dumps(d)[:300].lower():
        # reels/videos reject the shares field outright — retry without it
        # instead of skipping the post (a blind tuner never learns).
        r = requests.get(
            url,
            params={"fields": "likes.summary(true),comments.summary(true)",
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
    """Pull engagement on our posts from the last 14 days, update multipliers.
    mult = smoothed (per-topic avg / global avg), clamped 0.5-2.0, needs n>=2."""
    tuner = state.setdefault("tuner", {"topics": {}, "mult": {}})
    today = datetime.now(timezone.utc).date().isoformat()
    if tuner.get("updated") == today:
        return tuner.get("mult", {})
    if not os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip():
        return tuner.get("mult", {})
    cutoff = datetime.now(timezone.utc).timestamp() - 14 * 86400
    items = []
    for h in state.get("history", [])[-20:]:
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
    # AI model leakers (unreleased LLMs — writer frames as RUMOR)
    "shengtang135754",  # Gemini/GPT leaks (CN/EN), often first
    "testingcatalog",   # unreleased AI models/features tracker
    "ChatGPTapp",       # ChatGPT updates + rollouts watcher
    "Priyannkaaaa",     # Priya — DeepSeek/AI leaks, often first
    # Famous investors (faces + posts; Burry rarely tweets himself)
    "BurryTracker",     # Michael Burry tracker (13F, quotes, deletes)
    "saylor",           # Michael Saylor — daily Bitcoin, strict-ish gate
    "jimcramer",        # Jim Cramer — very noisy, strict gate
    "BillAckman",       # Bill Ackman — longform letters/threads
    "RayDalio",         # Ray Dalio — principles + macro
    "CathieDWood",      # Cathie Wood / ARK — innovation calls
    # Politician trade trackers (visual: politician + stock they bought)
    "PelosiTracker_",   # Nancy Pelosi stock tracker — rare gold, boosted
    "congresstrading",  # congressional trades across both parties
    # Bank analyst actions (price targets, upgrades — Stockstoearn style)
    "StockMKTNewz",     # analyst PT changes all day
    "unusual_whales",   # flow + analyst ratings, noisy -> strict gate
    # Faster crypto breaking than WatcherGuru (all verified live Oct 2026:
    # real handles, follower counts + bios checked via FxEmbed author block)
    "Cointelegraph",    # 2.9M — fastest detailed crypto breaking
    "BitcoinMagazine",  # 4.5M — trusted BTC voice
    "DegenerateNews",   # 426K — raw degen wire, strict min_score gate
    "Newsquawk",        # 138K — pro squawk desk
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
    "BurryTracker": {"boost": 2},   # rare Burry signal, rank it up
    "PelosiTracker_": {"boost": 2},  # rare Pelosi trade, rank it up
    "jimcramer": {"min_score": 6},   # showy daily takes, strict gate
    "saylor": {"min_score": 5},      # daily perma-bull drumbeat, firm gate
    "unusual_whales": {"min_score": 6},  # options-flow firehose, strict gate
    "DegenerateNews": {"min_score": 6},  # fast but meme-y by its own bio
}


def fetch_x_candidates(max_age_minutes: int):
    out = []
    for handle in X_HANDLES:
        # FxEmbed flaps per-handle (working handles 404 for stretches, then
        # recover) — one retry after 5s saves most of those runs.
        d = None
        for _x_try in (1, 2):
            try:
                r = requests.get(
                    f"https://api.fxtwitter.com/2/profile/{handle}/statuses",
                    params={"limit": 20}, timeout=15,
                    headers={"User-Agent": "ethan-cole-fb-bot/1.0"})
                d = r.json()
            except Exception as ex:
                d = {"code": f"fetch-error {type(ex).__name__}"}
            if (d or {}).get("code") == 200:
                break
            if _x_try == 1:
                time.sleep(5)
        if (d or {}).get("code") != 200:
            log(f"X @{handle}: API code {(d or {}).get('code')} (after retry)")
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
            if age is None or age > max_age_minutes:
                continue
            link = (p.get("url")
                    or f"https://x.com/{handle}/status/{p.get('id')}")
            photo_url = None
            video_url = None
            try:
                def _pick(items):
                    best, best_a, first = None, -1, None
                    for m in items or []:
                        u = m.get("url") or m.get("src")
                        if not u:
                            continue
                        if first is None:
                            first = u
                        try:
                            a = int(m.get("width") or 0) * int(m.get("height") or 0)
                        except Exception:
                            a = 0
                        if a > best_a:
                            best, best_a = u, a
                    return best or first
                media = p.get("media") or {}
                # Main post media ONLY: quote-tweet and reply media
                # caused wrong-image posts (e.g. pricing screenshots).
                # A post quoting anything keeps its TEXT but never its
                # attachments: the API mixes quoted media in, so quoted
                # posts resolve to subject visuals (logo/face) instead.
                quoted = p.get("quote") or {}
                if quoted.get("id") or quoted.get("text"):
                    photos, videos = [], []
                else:
                    photos = list(media.get("photos") or [])
                    videos = list(media.get("videos") or [])
                photo_url = _pick(photos)
                video_url = _pick(videos)
            except Exception:
                photo_url = None
            title = text if len(text) <= 200 else text[:197] + "..."
            s, hits = score_entry(title, text)
            vb = viral_bonus(text, likes=p.get("likes", 0) or 0,
                             reposts=p.get("reposts", 0) or 0,
                             replies=p.get("replies", 0) or 0)
            s += vb
            tb = feed_trust_bonus(f"X @{handle}")
            if tb:
                s += tb
                hits.append("+trusted")
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
                if age is None or age < -5 or age > max_age_minutes:
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
                tb = feed_trust_bonus(f"TG {ch}")
                if tb:
                    s += tb
                    hits.append("+trusted")
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
    # war/conflict with no market angle is off-brand for Finance+AI
    # (oil-route wars keep their market words and pass).
    if CONFLICT_PAT.search(text) and not MARKET_ANGLE_PAT.search(text):
        return -100, []
    # Famous-stock gate: bank-rating posts only count when they name a
    # $50B+ famous stock. Random small-cap ratings never post.
    if ANALYST_PAT.search(text) and not _match_table(
            text, [(e, None, None) for e in FAMOUS_STOCKS]):
        return -100, []
    # 13F gate: only famous filers' filings post (quarterly waves are
    # 90% unknown funds).
    if F13_PAT.search(text) and not any(f in text for f in FAMOUS_FILERS):
        return -100, []
    # Insider gate: only $500B+ mega-cap names post.
    if INSIDER_PAT.search(text) and not _mega_stock(text):
        return -100, []
    hits: list[str] = []
    score = 0.0
    for topic, (kws, w) in TOPIC_WEIGHTS.items():
        # short tokens match on word boundaries only ("dow" must not fire
        # inside "double down", "oil" not inside "boiling").
        matched = [k for k in kws
                   if (re.search(r"\b" + re.escape(k) + r"\b", text)
                       if len(k) <= 4 else k in text)]
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
    # blue-chip base: famous $50B+ stocks are core page content (+1 when
    # anything else already scored, so politician trades clear the bar).
    if _match_table(text, [(e, None, None) for e in FAMOUS_STOCKS]):
        score += 1
        hits.append("+blue-chip")
    # learned: generic fed-process stories with no market angle flop (avg 1.5)
    if any(h in ("fed", "federal reserve", "interest rate") for h in hits) and not \
            re.search(r"market|stock|s&p|nasdaq|bitcoin|mortgage|yield|dollar", text):
        score -= 2
    # power-lane gate: politics/geopolitics MUST move markets. Tariff/trade/
    # oil stories pass; pure rally speeches, gaffes, war talk and street
    # crime are excluded outright — they flop on a Finance+AI page and cost
    # followers (proven by off-brand posts).
    if "power" in {KW_TO_TOPIC.get(k, "") for k in hits} and not \
            MARKET_ANGLE_PAT.search(text):
        return -100, []
    if len(title.strip()) < 25:
        score -= 1
    # shout tax: ALL-CAPS headlines skew tabloid (quality outlets don't
    # shout). Small -1: squawk wires survive it, calm originals gain ground.
    letters = [ch for ch in title if ch.isalpha()]
    if letters and sum(1 for ch in letters if ch.isupper()) / len(letters) > 0.6:
        score -= 1
    return score, hits[:6]


def diversity_penalty(pick_topics: list, history: list) -> int:
    """Reader-fatigue guard: -2 when the pick's topics ALL appeared in EACH
    of the last 2 posts (third same-topic post in a row)."""
    if not pick_topics:
        return 0
    last2 = [set(h.get("topics", []) or []) for h in history[-2:]]
    if len(last2) < 2:
        return 0
    if all(set(pick_topics) <= h for h in last2):
        return 2
    return 0


# SEC 13F-HR filings (atom). SEC blocks generic scrapers, so this uses
# requests with a descriptive UA, then feedparser on the bytes. Only
# famous filers survive (see FAMOUS_FILERS gate in score_entry).
SEC_13F_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?"
               "action=getcurrent&type=13F-HR&company=&dateb=&owner=include"
               "&start=0&count=40&output=atom")
SEC_UA = {"User-Agent": "EthanColeBot/1.0 (automated finance news monitor)"}


def fetch_sec_13f(max_age_minutes: int):
    out = []
    try:
        r = requests.get(SEC_13F_URL, timeout=25, headers=SEC_UA)
        if r.status_code != 200 or not r.content:
            log(f"SEC 13F: HTTP {r.status_code}")
            return out
        feed = feedparser.parse(r.content)
        log(f"SEC 13F: {len(feed.entries)} filings")
        for e in feed.entries[:40]:
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            if not title or not link:
                continue
            age = entry_age_minutes(e)
            if age is not None and age > max_age_minutes:
                continue
            summary = (e.get("summary") or "")[:300]
            s, hits = score_entry(title, summary)
            if s < 1:
                continue
            verified = verify_url(link)
            out.append({
                "feed": "SEC 13F", "mode": "serious", "viral": 0,
                "title": re.sub(r"\s+", " ", html.unescape(title))[:200],
                "summary": html.unescape(re.sub(r"<[^>]+>", "", summary))[:400],
                "link": link,
                "age_min": round(age) if age is not None else None,
                "score": decay(s + (1 if verified else -1), age, "serious"),
                "keywords": hits[:5],
                "verified": verified,
            })
    except Exception as ex:
        log(f"SEC 13F error: {ex}")
    out.sort(key=lambda c: c["score"], reverse=True)
    return out


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
                tb = feed_trust_bonus(name)
                if tb:
                    s += tb
                    hits.append("+trusted")
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
- Hook line first, Watcher Guru style: `JUST IN:` or `BREAKING:` + flag/stake emoji + the bombshell in ONE line. CAPS on the money word (TARIFFS, CRASH, BANNED). Never throat-clearing, never background first.
- Then 1-2 short context lines, Polymarket/Kalshi energy: dry, sharp, meme-aware. Frame uncertainty like a market when it fits ("odds of X just spiked"). Almost never open with a question; earn attention with the claim, then explain.
- Body ~3-5 short lines with blank-line breaks: 1-2 context lines, then a numbers/specs block with emoji bullets when specs exist.
- Open with an emoji about half the time (never forced; the best accounts barely use them). Alert emoji for genuine fresh news. Almost never open with a question.
- One 'why it matters' line with the market implication.
- Every post must contain at least one concrete number ($, %, multiple, date). No naked claims.
- CAPS on 1-3 money words max (TARIFFS, CRASH, BANNED) — never whole sentences shouting.
- Length 180-350 characters (short posts only, never long).
  NEVER under 150.
- Hashtags: ALWAYS include #ethancole first, then 4-5 topic tags from the house set when relevant: #ai #artificialintelligence #technews #finance #stockmarket #investing #breakingnews #marketnews #federalreserve #crypto #bitcoin #openai #nvidia #economy. Exactly 5-6 total. Page data proves 7+ tags collapse engagement.
- Rewrite originally, never copy the headline. NO URLs in the copy.
- SOURCE-ONLY: use ONLY the facts, names, numbers, and titles stated in the provided headline/summary below. NEVER fill gaps from your training data — if the source doesn't say it, don't add it. In particular, never infer job titles or 'former/current' status from memory; copy titles exactly as the source states them.
- IDENTIFICATION: first mention of any company is its full name + ($TICKER) when listed — 'Strategy ($MSTR)', 'Coinbase ($COIN)', 'Strive, Inc.'. A bare single-word name ('Strive', 'Metaplanet') with no identifier leaves readers lost; never ship that. Never hedge a real company name in scare quotes ('Strategy').
- NEVER write any source/credit/attribution line: no 'Source:', no outlet names,
  no camera/link emoji lines. Posts go out with zero attribution.
- 'BREAKING'/'JUST IN' only for genuinely fresh news; 'reportedly' if unconfirmed.
- CURRENT FACTS (override your training data): Donald Trump IS the sitting U.S. President — NEVER write 'former President Trump'. Kevin Warsh IS Fed Chair (not Powell). John Ternus IS Apple CEO; Tim Cook is Executive Chairman. Never contradict these.
- Leaks/rumors about unreleased models: always frame as RUMOR or 'reportedly' — NEVER present a leak as a confirmed launch.
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
    # Fail fast to the next model in the list: no sleeping inside a call.
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
    if r.status_code != 200:
        raise RuntimeError(f"OpenRouter {model} HTTP {r.status_code}: "
                           f"{_json.dumps(d)[:200]}")
    try:
        return d["choices"][0]["message"]["content"].strip()
    except Exception as ex:
        raise RuntimeError(f"OpenRouter {model} parse error: {ex}")


# Bare tickers confuse readers the same way in English ("$COIN" alone next to
# crypto news reads as a token). Expand to English name + ticker. Verified
# tickers only (SPCX confirmed = Space Exploration Technologies Corp. Nasdaq
# vehicle, ASST/SATA = Strive Inc. common/preferred — Nasdaq API, Oct 2026).
# Case-sensitive, whole-word, paren-guarded (no double-expansion).
KNOWN_STOCK = {
    "COIN": "Coinbase ($COIN)",
    "MSTR": "Strategy ($MSTR)",
    "NVDA": "Nvidia ($NVDA)",
    "TSLA": "Tesla ($TSLA)",
    "AAPL": "Apple ($AAPL)",
    "MSFT": "Microsoft ($MSFT)",
    "GOOGL": "Google ($GOOGL)",
    "AMZN": "Amazon ($AMZN)",
    "META": "Meta ($META)",
    "VST": "Vistra ($VST)",
    "STRC": "Strategy ($STRC)",
    "STRF": "Strategy ($STRF)",
    "SATA": "Strive ($SATA)",
}

# Obscure-but-real names get their identifier ("who the fuck is Strive" —
# bare single-word company names ship readers lost). Verified identities
# only; unknown names stay exactly as the source wrote them. Case-sensitive:
# lowercase "strive" is a verb.
KNOWN_ENTITY = {
    "Strive": "Strive, Inc.",
    "Metaplanet": "Metaplanet Inc.",
    "'Strategy'": "Strategy",
    "'Strive'": "Strive, Inc.",
}


def _fix_names(post: str) -> str:
    for name, full in KNOWN_ENTITY.items():
        if name[:1] in ("'", '"'):
            # quoted variant: \b never matches beside a quote, use guards
            post = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)",
                          full, post)
        else:
            # identify once: a possessive after identification stays bare
            # ("Strive, Inc. ... Strive's total" — not "Strive, Inc.'s")
            post = re.sub(r"\b" + re.escape(name) + r"\b(?![’']s\b)",
                          full, post)
    for ticker, full in KNOWN_STOCK.items():
        post = re.sub(r"\b" + ticker + r"\b(?![^(]*\))", full, post)
    return post


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
    post = post.replace("\r", "")
    # strip CI workflow-command sequences (::group::, ::notice::, ##[..])
    # so LLM output can never swallow log sections or break rendering
    post = re.sub(r"::(?i:group|endgroup|notice|warning|error|debug|add-mask|set-output|set-env|save-state|echo|command)\b", ":", post)
    post = post.replace("##[", "#[")
    # strip control chars (keep \n, \t): a single NUL/vertical-tab from
    # LLM output breaks the CI log stream and swallows all later lines
    post = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", post)
    post = post.replace("*", "").replace("`", "")
    # deterministic identification: bare tickers -> Name ($TICKER),
    # obscure firms -> full legal name (a bare "Strive" ships readers lost)
    post = _fix_names(post)
    return post


def repair_post(post: str) -> str:
    """Auto-fix near-miss drafts: strip markdown, trim tags to 6 (brand
    first), cap length. Returns the repaired text; caller re-runs
    quality_check on it."""
    post = sanitize(post)
    # stale-leader repair: sitting officeholders mislabeled 'former'
    post = re.sub(r"(?i)\bformer president trump\b", "President Trump", post)
    post = re.sub(r"(?i)\bex-president trump\b", "President Trump", post)
    post = re.sub(r"(?i)\bformer fed chair (kevin )?warsh\b",
                  "Fed Chair Warsh", post)
    # strip any LLM-written attribution lines (no attribution allowed)
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
    if len(body) + len(tag_block) + 2 > 350:
        budget = 350 - len(tag_block) - 3
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
    "burry", "saylor", "cramer",
]


def apply_rage_mix(fresh: list, modes: list) -> str | None:
    """Enforce ~60% rage-bait mix: target RAGE_TARGET viral posts out of
    every 5 (default 3). Below target the best viral candidate gets
    +RAGE_BOOST (default 3, usually wins); at/above target the best serious
    candidate gets +3 to hold the serious floor (the funnel skews viral by
    construction, so neutrality at target drifts to ~75% viral). Returns
    log line or None."""
    viral_n = modes.count("viral")
    target = int(os.getenv("RAGE_TARGET", "3"))
    if viral_n < target:
        need, boost = "viral", int(os.getenv("RAGE_BOOST", "3"))
    else:
        need, boost = "serious", 3
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
- Open with your hardest punch: JUST IN / BREAKING + caps conflict + stakes. Name the winner and the loser. Make a scroller feel they LOSE by skipping.
- One sharp, opinionated closer line — raised eyebrow, not essay.
- End the body with a debate-sparking question OR a mic-drop line (viral mode only). Give readers a reason to follow for the next update: end on an open loop (what happens next, what to watch).
- Facts stay exact: spice the framing, never the facts. No invented quotes or numbers.
- Never explicitly ask for likes, shares, comments or follows — engagement
  bait violates monetization policy and can kill page eligibility."""


# Free-tier model slugs ROTATE without warning (Oct 2026: OpenRouter pulled
# qwen3.8-27b:free mid-day). The backup chain tries a LIST, not one slug.
# Pinnable via OPENROUTER_MODELS (comma-separated); default tracks live.
OPENROUTER_MODELS_DEFAULT = ("google/gemma-4-31b-it:free,"
                             "google/gemma-4-26b-a4b-it:free,"
                             "nvidia/nemotron-3-super-120b-a12b:free")
NVIDIA_MODELS_DEFAULT = ("openai/gpt-oss-20b,"
                         "nvidia/nemotron-3-super-120b-a12b")


def gen_nvidia(model: str, system: str, user: str) -> str:
    """NVIDIA Build API (OpenAI-compatible). Verified live Oct 2026:
    super-120b writes clean copy but thinks ~6k tokens first, so it gets
    max_tokens 4096 and a long timeout. Content only — empty content is a
    failure, never a post."""
    import json as _json
    key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("No NVIDIA_API_KEY set")
    r = requests.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        json={"model": model, "max_tokens": 4096, "temperature": 0.5,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]},
        timeout=180)
    try:
        d = r.json()
    except Exception:
        raise RuntimeError(f"NVIDIA {model} HTTP {r.status_code}: "
                           f"non-JSON body")
    if r.status_code != 200:
        raise RuntimeError(f"NVIDIA {model} HTTP {r.status_code}: "
                           f"{_json.dumps(d)[:200]}")
    try:
        text = (d["choices"][0]["message"].get("content") or "").strip()
        if not text:
            raise RuntimeError(
                f"NVIDIA {model} returned no content "
                f"(finish_reason={d['choices'][0].get('finish_reason')})")
        return text
    except Exception as ex:
        raise RuntimeError(f"NVIDIA {model} parse error: {ex}")


def _openrouter_models() -> list:
    multi = os.getenv("OPENROUTER_MODELS", "").strip()
    if multi:
        return [m.strip() for m in multi.split(",") if m.strip()]
    one = os.getenv("OPENROUTER_MODEL", "").strip()
    if one:
        return [one]
    return [m.strip() for m in OPENROUTER_MODELS_DEFAULT.split(",")
            if m.strip()]


def rewrite_with_llm(candidate: dict) -> str:
    user_msg = USER_TEMPLATE.format(**candidate)
    system = (SYSTEM_PROMPT_VIRAL if candidate.get("mode") == "viral"
              else SYSTEM_PROMPT)
    chain: list[tuple[str, str]] = []
    if _gemini_keys():
        chain.append(("gemini",
                      os.getenv("GEMINI_MODEL", "gemini-2.5-flash")))
    if os.getenv("NVIDIA_API_KEY", "").strip():
        multi = os.getenv("NVIDIA_MODELS", "").strip()
        nmodels = ([m.strip() for m in multi.split(",") if m.strip()]
                   if multi else [m.strip() for m in
                                   NVIDIA_MODELS_DEFAULT.split(",")
                                   if m.strip()])
        chain += [("nvidia", m) for m in nmodels]
    if os.getenv("OPENROUTER_API_KEY", "").strip():
        chain += [("openrouter", m) for m in _openrouter_models()]
    if not chain:
        raise RuntimeError("No LLM key set (GEMINI_API_KEY or OPENROUTER_API_KEY)")
    errors = []
    for kind, model in chain:
        try:
            text = (gen_gemini(model, system, user_msg)
                    if kind == "gemini"
                    else gen_nvidia(model, system, user_msg)
                    if kind == "nvidia"
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
    if len(post) > 350:
        problems.append("too long (>350 chars, short posts only)")
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
    if re.search(r"(?i)former president trump|ex-president trump", post):
        problems.append("calls sitting president 'former' (stale leadership)")
    if any(p in post.lower() for p in ENGAGEMENT_BAIT):
        problems.append("engagement bait (kills monetization eligibility)")
    if re.search(r"(?i)(?<![\w-])sources?\s*:|🔗|📸", post):
        problems.append("contains attribution line (no attribution allowed)")
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
    (["apple", "iphone", "ipad", "ternus", "tim cook"],
     [], ["Apple logo", "Apple Store"]),
    (["microsoft", "copilot", "nadella", "azure"],
     [], ["Microsoft logo", "Microsoft headquarters"]),
    (["amd", "ryzen", "lisa su"],
     [], ["AMD logo"]),
    (["samsung"],
     [], ["Samsung logo"]),
    (["xai", "grok"],
     [], ["xAI logo", "Grok xAI"]),
    (["ftx", "alameda"],
     [], ["FTX logo"]),
    (["deepseek"],
     [], ["DeepSeek logo"]),
    (["mistral"],
     [], ["Mistral AI logo"]),
    (["jpmorgan", "jpmorgan chase", "dimon"],
     [], ["JPMorgan Chase headquarters"]),
    (["blackrock", "fink"],
     [], ["BlackRock headquarters"]),
    (["goldman sachs", "goldman"],
     [], ["Goldman Sachs headquarters"]),
    (["bank of america", "bofa"],
     [], ["Bank of America logo"]),
    (["morgan stanley"],
     [], ["Morgan Stanley logo"]),
    (["citi", "citigroup"],
     [], ["Citigroup logo"]),
    (["wells fargo"],
     [], ["Wells Fargo logo"]),
    (["ubs"],
     [], ["UBS logo"]),
    (["bernstein"],
     [], ["Bernstein logo"]),
    (["wedbush", "ives"],
     [], ["Wedbush logo"]),
    (["evercore"],
     [], ["Evercore logo"]),
    (["keybanc"],
     [], ["KeyBanc logo"]),
    # Institutions (files empty -> runtime Commons search -> branded photo,
    # not a logo card). Used by institution_photo() and as tail fallback.
    (["white house"],
     [], ["White House Washington DC"]),
    (["u.s. capitol", "us capitol", "capitol hill", "congress"],
     [], ["United States Capitol building"]),
    (["european central bank", "ecb"],
     [], ["European Central Bank Frankfurt"]),
    (["nato"],
     [], ["NATO headquarters Brussels"]),
    (["united nations", "un general assembly", "un security council"],
     [], ["United Nations headquarters New York"]),
    (["european commission", "berlaymont"],
     [], ["Berlaymont Brussels"]),
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
        .save(buf, "JPEG", quality=95)
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
    card.paste(logo, ((1200 - logo.size[0]) // 2, (578 - logo.size[1]) // 2),
               logo)
    buf = io.BytesIO()
    _footer(card).save(buf, "JPEG", quality=95)
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
    (["warsh", "kevin warsh", "fed chair", "fed chairman", "fomc chair",
      "federal reserve chair"], "Kevin Warsh", ["Kevin Warsh Federal Reserve"]),
    (["trump", "donald trump"], "Donald Trump", ["Donald Trump official portrait"]),
    (["modi", "narendra modi"], "Narendra Modi", ["Narendra Modi portrait"]),
    (["bessent", "scott bessent"], "Scott Bessent", ["Scott Bessent Treasury"]),
    (["powell", "jerome powell"], "Jerome Powell", ["Jerome Powell Federal Reserve"]),
    (["hammack", "beth hammack"], "Beth Hammack", ["Beth Hammack Cleveland Fed"]),
    (["greer", "jamieson greer"], "Jamieson Greer", ["Jamieson Greer USTR"]),
    (["lutnick", "howard lutnick"], "Howard Lutnick", ["Howard Lutnick Commerce"]),
    (["xi jinping", "president xi", "w:xi"], "Xi Jinping", ["Xi Jinping portrait"]),
    (["lagarde", "christine lagarde"], "Christine Lagarde", ["Christine Lagarde ECB"]),
    (["vujcic"], "Boris Vujcic", ["Boris Vujcic central bank"]),
    (["putin", "vladimir putin"], "Vladimir Putin", ["Vladimir Putin portrait"]),    (["araghchi", "abbas araghchi"], "Abbas Araghchi", ["Abbas Araghchi foreign minister"]),
    (["pezeshkian"], "Masoud Pezeshkian", ["Masoud Pezeshkian president"]),
    (["netanyahu"], "Benjamin Netanyahu", ["Benjamin Netanyahu portrait"]),
    (["huang", "jensen huang"], "Jensen Huang", ["Jensen Huang Nvidia"]),
    (["altman", "sam altman"], "Sam Altman", ["Sam Altman OpenAI"]),
    (["amodei", "dario amodei"], "Dario Amodei", ["Dario Amodei Anthropic"]),
    (["musk", "elon musk"], "Elon Musk", ["Elon Musk portrait"]),
    (["sam bankman-fried", "bankman-fried", "w:sbf"], "Sam Bankman-Fried",
     ["Sam Bankman-Fried portrait"]),
    (["reeves", "rachel reeves"], "Rachel Reeves", ["Rachel Reeves chancellor"]),
    (["merz", "friedrich merz"], "Friedrich Merz", ["Friedrich Merz chancellor"]),
    (["mohammed bin salman", "bin salman", "mbs"], "Mohammed bin Salman", ["Mohammed bin Salman portrait"]),
    (["zelensky", "zelenskyy"], "Volodymyr Zelenskyy", ["Volodymyr Zelenskyy portrait"]),
    (["vance", "jd vance"], "JD Vance", ["JD Vance portrait"]),
    (["macron", "emmanuel macron"], "Emmanuel Macron", ["Emmanuel Macron portrait"]),
    (["starmer", "keir starmer"], "Keir Starmer", ["Keir Starmer portrait"]),
    (["erdogan", "erdoğan", "recep tayyip erdogan"], "Recep Tayyip Erdoğan", ["Recep Tayyip Erdogan portrait"]),
    (["lee jae-myung", "lee jae myung"], "Lee Jae-myung", ["Lee Jae-myung portrait"]),
    (["lai ching-te", "william lai"], "Lai Ching-te", ["Lai Ching-te portrait"]),
    (["takaichi", "sanae takaichi"], "Sanae Takaichi", ["Sanae Takaichi portrait"]),
    (["mohamed bin zayed", "bin zayed"], "Mohamed bin Zayed", ["Mohamed bin Zayed portrait"]),
    (["greg abbott", "governor abbott"], "Greg Abbott", ["Greg Abbott Texas governor"]),
    (["gavin newsom", "governor newsom"], "Gavin Newsom", ["Gavin Newsom portrait"]),
    (["zuckerberg", "mark zuckerberg"], "Mark Zuckerberg", ["Mark Zuckerberg portrait"]),
    (["nadella", "satya nadella"], "Satya Nadella", ["Satya Nadella portrait"]),
    (["pichai", "sundar pichai"], "Sundar Pichai", ["Sundar Pichai portrait"]),
    (["john ternus", "ternus"], "John Ternus", ["John Ternus Apple"]),
    (["tim cook"], "Tim Cook", ["Tim Cook Apple"]),
    (["michelle bowman", "governor bowman"], "Michelle Bowman", ["Michelle Bowman Federal Reserve"]),
    (["christopher waller", "governor waller"], "Christopher Waller", ["Christopher Waller Federal Reserve"]),
    (["philip jefferson", "governor jefferson"], "Philip Jefferson", ["Philip Jefferson Federal Reserve"]),
    (["lisa cook", "governor cook"], "Lisa Cook", ["Lisa Cook Federal Reserve"]),
    (["michael barr"], "Michael Barr", ["Michael Barr Federal Reserve"]),
    (["michael burry", "burry"], "Michael Burry", ["Michael Burry portrait"]),
    (["michael saylor", "saylor"], "Michael Saylor", ["Michael Saylor portrait"]),
    # w:strive (word-boundary): bare "strive" is the company in practice —
    # verb collisions measured at zero in page history, and a face beats a
    # clip-art coin for a treasury-company story every time.
    (["vivek ramaswamy", "ramaswamy", "w:strive"], "Vivek Ramaswamy", ["Vivek Ramaswamy portrait"]),
    (["jim cramer", "cramer"], "Jim Cramer", ["Jim Cramer portrait"]),
    (["warren buffett", "buffett"], "Warren Buffett", ["Warren Buffett portrait"]),
    (["bill ackman", "ackman"], "Bill Ackman", ["Bill Ackman portrait"]),
    (["ray dalio", "dalio"], "Ray Dalio", ["Ray Dalio portrait"]),
    (["cathie wood", "cathie"], "Cathie Wood", ["Cathie Wood portrait"]),
    (["jamie dimon", "dimon"], "Jamie Dimon", ["Jamie Dimon portrait"]),
    (["larry fink", "fink"], "Larry Fink", ["Larry Fink portrait"]),
    (["druckenmiller", "stanley druckenmiller"], "Stanley Druckenmiller", ["Stanley Druckenmiller portrait"]),
    (["vivek arya", "arya"], "Vivek Arya", ["Vivek Arya Bank of America"]),
    (["dan ives", "ives"], "Dan Ives", ["Dan Ives Wedbush"]),
    (["gene munster", "munster"], "Gene Munster", ["Gene Munster Deepwater"]),
    (["pelosi", "nancy pelosi"], "Nancy Pelosi", ["Nancy Pelosi portrait"]),
    (["biden", "joe biden"], "Joe Biden", ["Joe Biden portrait"]),
    (["obama", "barack obama"], "Barack Obama", ["Barack Obama portrait"]),
    (["schumer", "chuck schumer"], "Chuck Schumer", ["Chuck Schumer portrait"]),
    (["mcconnell", "mitch mcconnell"], "Mitch McConnell", ["Mitch McConnell portrait"]),
    (["mike johnson", "speaker johnson"], "Mike Johnson", ["Mike Johnson speaker portrait"]),
    (["jeffries", "hakeem jeffries"], "Hakeem Jeffries", ["Hakeem Jeffries portrait"]),
    (["aoc", "ocasio-cortez", "ocasio cortez", "alexandria ocasio"], "Alexandria Ocasio-Cortez", ["Alexandria Ocasio-Cortez portrait"]),
    (["elizabeth warren", "senator warren"], "Elizabeth Warren", ["Elizabeth Warren portrait"]),
    (["bernie sanders", "bernie"], "Bernie Sanders", ["Bernie Sanders portrait"]),
    (["cruz", "ted cruz"], "Ted Cruz", ["Ted Cruz portrait"]),
    (["rubio", "marco rubio"], "Marco Rubio", ["Marco Rubio portrait"]),
    (["hillary clinton", "hillary"], "Hillary Clinton", ["Hillary Clinton portrait"]),
    (["bezos", "jeff bezos"], "Jeff Bezos", ["Jeff Bezos portrait"]),
    (["jassy", "andy jassy"], "Andy Jassy", ["Andy Jassy portrait"]),
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


def _bundled_face_for(wiki: str) -> bytes | None:
    """Bundled assets/faces/<slug>.(png|jpg) bytes, else None. Owner-supplied
    portraits beat Wikipedia (e.g. SBF)."""
    stem = _slug(wiki) or "person"
    for ext in (".png", ".jpg", ".jpeg"):
        lp = os.path.join(ASSETS_DIR, "faces", f"{stem}{ext}")
        if not os.path.exists(lp):
            continue
        try:
            with open(lp, "rb") as fh:
                return fh.read()
        except Exception:
            continue
    return None


def _fetch_face_raw(wiki: str, queries: list):
    """Raw (unbranded) face bytes, for face cards and split composites.
    Owner-bundled portrait first, then Wikipedia official portraits —
    open-web face search produced memes and edited junk, never again."""
    bundled = _bundled_face_for(wiki)
    if bundled:
        return bundled
    try:
        ov, _, _ = _openverse_photo(f"{wiki} portrait")
        if False and ov and _big_enough(ov):  # open-web faces disabled: meme risk
            return ov
    except Exception:
        pass
    data = _wiki_portrait(wiki)
    if data:
        return data
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
                return data
        except Exception as ex:
            log(f"Commons portrait {q[:40]} failed: {ex}")
    return None


def _cover(im, w, h, top_bias=False):
    """Resize-and-crop to exactly w×h. Faces use top bias, scenes center."""
    scale = max(w / im.size[0], h / im.size[1])
    im = im.resize((int(im.size[0] * scale) + 1, int(im.size[1] * scale) + 1))
    x = (im.size[0] - w) // 2
    y = (im.size[1] - h) // (3 if top_bias else 2)
    y = max(y, 0)
    return im.crop((x, y, x + w, y + h))


def _split_pair(left: bytes, right: bytes, left_logo=False,
                right_face=False, left_face=False, right_logo=False):
    """1200x630 two-panel composite. Logos sit contained on dark;
    photos cover-crop (faces top-biased). Always ends with house footer."""
    from PIL import Image, ImageDraw
    try:
        left_im = Image.open(io.BytesIO(left))
        right_im = Image.open(io.BytesIO(right))
    except Exception:
        return None
    card = Image.new("RGB", (1200, 630), (11, 18, 32))
    body_h = 630 - max(46, 630 // 12)  # 578: panels meet the footer exactly
    if left_logo:
        left_im = left_im.convert("RGBA")
        left_im.thumbnail((520, 380))
        card.paste(left_im, ((600 - left_im.size[0]) // 2,
                             (body_h - left_im.size[1]) // 2), left_im)
    elif left_face:
        card.paste(_cover(left_im.convert("RGB"), 600, body_h,
                           top_bias=True), (0, 0))
    else:
        card.paste(_cover(left_im.convert("RGB"), 600, body_h), (0, 0))
    if right_logo:
        right_im = right_im.convert("RGBA")
        right_im.thumbnail((520, 380))
        card.paste(right_im, (600 + (600 - right_im.size[0]) // 2,
                              (body_h - right_im.size[1]) // 2), right_im)
    elif right_face:
        card.paste(_cover(right_im.convert("RGB"), 600, body_h,
                           top_bias=True), (600, 0))
    else:
        card.paste(_cover(right_im.convert("RGB"), 600, body_h), (600, 0))
    d = ImageDraw.Draw(card)
    d.line([600, 0, 600, body_h], fill=(255, 255, 255), width=3)
    buf = io.BytesIO()
    _footer(card).save(buf, "JPEG", quality=95)
    return buf.getvalue(), "jpeg"


def _split_image(face: bytes, logo: bytes):
    """Legacy wrapper: logo left, face right."""
    return _split_pair(logo, face, left_logo=True, right_face=True)


NEUTRAL_TOPICS = ["stocks-nyse.jpg", "market-hall.jpg", "wallstreet.jpg"]


def _topic_raw_files(title: str, text: str, link: str,
                     n: int = 2) -> list:
    """Up to n unbranded topic filenames for text (ordered, distinct).
    Walks rows by subject relevance so a bitcoin story mentioning gold still
    yields bitcoin scenes first."""
    picked: list = []
    for keys, files in _score_topic_rows(title, text):
        start = int(hashlib.sha256(link.encode()).hexdigest(), 16)
        for i in range(len(files)):
            fn = files[(start + i) % len(files)]
            if fn not in picked:
                picked.append(fn)
            if len(picked) >= n:
                return picked
    start = int(hashlib.sha256((link + "neutral").encode()).hexdigest(), 16)
    for i in range(len(NEUTRAL_TOPICS)):
        fn = NEUTRAL_TOPICS[(start + i) % len(NEUTRAL_TOPICS)]
        if fn not in picked:
            picked.append(fn)
        if len(picked) >= n:
            break
    return picked


def _live_scene(query: str):
    """Fresh web photo for split scenes: Google first, Openverse next.
    Returns bytes or None. Never raises."""
    try:
        gdata, _ = _google_photo(query)
        if gdata and _big_enough(gdata):
            return gdata
    except Exception:
        pass
    try:
        odata, _, _ = _openverse_photo(query)
        if odata and _big_enough(odata):
            return odata
    except Exception:
        pass
    return None


def _flag_photo(code):
    """Deterministic flag PNG from flagcdn. Returns bytes or None."""
    if not code:
        return None
    try:
        data, _ext = _download_image(
            "https://flagcdn.com/w640/" + code + ".png", min_bytes=3000)
        if data and _big_enough(data):
            return data
    except Exception:
        pass
    return None


COUNTRY_PHOTOS = [
    # (keywords, flagcdn code, leader wiki name or None, leader always?)
    # ORDER MATTERS, top wins:
    # - US states come BEFORE countries: "Indiana" contains "india",
    #   "New Mexico" contains "mexico" — states must win those collisions.
    # - West Virginia sits BEFORE Virginia ("virginia" is a substring).
    # - USA sits LAST as the national fallback.
    (["alabama", "birmingham", "montgomery", "huntsville"], "us-al", None, False),
    (["alaska", "anchorage", "juneau"], "us-ak", None, False),
    (["arizona", "phoenix", "tucson", "mesa"], "us-az", None, False),
    (["arkansas", "little rock", "fayetteville"], "us-ar", None, False),
    (["california", "los angeles", "san francisco", "san diego",
      "san jose", "sacramento", "silicon valley"], "us-ca", None, False),
    (["colorado", "denver", "boulder", "colorado springs"], "us-co", None, False),
    (["connecticut", "hartford", "new haven", "stamford"], "us-ct", None, False),
    (["delaware", "dover", "wilmington"], "us-de", None, False),
    (["florida", "miami", "orlando", "tampa", "tallahassee",
      "jacksonville"], "us-fl", None, False),
    (["georgia", "atlanta", "savannah", "augusta"], "us-ga", None, False),
    (["hawaii", "honolulu", "maui"], "us-hi", None, False),
    (["iowa", "des moines", "cedar rapids"], "us-ia", None, False),
    (["idaho", "boise"], "us-id", None, False),
    (["illinois", "chicago", "springfield"], "us-il", None, False),
    (["indiana", "indianapolis", "fort wayne"], "us-in", None, False),
    (["kansas", "wichita", "topeka", "overland park"], "us-ks", None, False),
    (["kentucky", "louisville", "lexington"], "us-ky", None, False),
    (["louisiana", "new orleans", "baton rouge"], "us-la", None, False),
    (["massachusetts", "boston", "cambridge", "worcester"], "us-ma", None, False),
    (["maryland", "baltimore", "annapolis"], "us-md", None, False),
    (["maine", "bangor", "augusta"], "us-me", None, False),
    (["michigan", "detroit", "grand rapids"], "us-mi", None, False),
    (["minnesota", "minneapolis", "st. paul", "saint paul"], "us-mn", None, False),
    (["missouri", "st. louis", "saint louis", "kansas city"], "us-mo", None, False),
    (["mississippi", "biloxi", "gulfport"], "us-ms", None, False),
    (["montana", "billings", "missoula"], "us-mt", None, False),
    (["north carolina", "charlotte", "raleigh", "durham"], "us-nc", None, False),
    (["north dakota", "fargo", "bismarck"], "us-nd", None, False),
    (["nebraska", "omaha"], "us-ne", None, False),
    (["new hampshire", "concord", "manchester", "nashua"], "us-nh", None, False),
    (["new jersey", "trenton", "newark", "princeton"], "us-nj", None, False),
    (["new mexico", "albuquerque", "santa fe"], "us-nm", None, False),
    (["nevada", "las vegas", "reno", "carson city"], "us-nv", None, False),
    (["new york", "nyc", "manhattan", "albany", "buffalo",
      "rochester", "syracuse"], "us-ny", None, False),
    (["ohio", "columbus", "cleveland", "cincinnati"], "us-oh", None, False),
    (["oklahoma", "oklahoma city", "tulsa", "norman"], "us-ok", None, False),
    (["oregon", "portland", "eugene", "salem"], "us-or", None, False),
    (["pennsylvania", "philadelphia", "pittsburgh", "harrisburg"], "us-pa", None, False),
    (["rhode island", "providence", "newport"], "us-ri", None, False),
    (["south carolina", "charleston", "columbia", "greenville"], "us-sc", None, False),
    (["south dakota", "sioux falls", "rapid city"], "us-sd", None, False),
    (["tennessee", "nashville", "memphis", "knoxville"], "us-tn", None, False),
    (["texas", "austin", "houston", "dallas", "san antonio",
      "fort worth", "el paso"], "us-tx", None, False),
    (["utah", "salt lake city", "provo"], "us-ut", None, False),
    (["vermont", "burlington", "montpelier"], "us-vt", None, False),
    (["west virginia", "huntington", "morgantown"], "us-wv", None, False),
    (["virginia", "richmond", "virginia beach", "norfolk"], "us-va", None, False),
    (["washington state", "seattle", "spokane", "tacoma", "olympia",
      "bellevue"], "us-wa", None, False),
    (["wisconsin", "milwaukee", "green bay"], "us-wi", None, False),
    (["wyoming", "cheyenne", "casper"], "us-wy", None, False),
    # Countries: China news -> China flag + Xi face (2-panel split).
    (["china", "chinese", "beijing", "shanghai", "shenzhen",
      "hong kong", "xi jinping", "president xi",
      "chairman xi"], "cn", "Xi Jinping", True),
    (["india", "indian", "new delhi", "mumbai", "modi"], "in",
     "Narendra Modi", True),
    (["russia", "russian", "moscow", "kremlin", "putin"], "ru",
     "Vladimir Putin", True),
    (["ukraine", "ukrainian", "kyiv", "kiev", "zelensky"], "ua",
     "Volodymyr Zelenskyy", True),
    (["iran", "iranian", "tehran", "pezeshkian"], "ir",
     "Masoud Pezeshkian", True),
    (["israel", "israeli", "tel aviv", "gaza", "netanyahu"], "il",
     "Benjamin Netanyahu", True),
    (["european union", "eurozone", "ecb", "lagarde", "brussels"], "eu",
     "Christine Lagarde", True),
    (["britain", "london", "starmer", "bank of england"], "gb", None, False),
    (["canada", "ottawa", "toronto"], "ca", None, False),
    (["mexico", "mexican"], "mx", None, False),
    (["japan", "japanese", "tokyo"], "jp", None, False),
    (["germany", "german", "berlin", "merz"], "de", "Friedrich Merz", True),
    (["france", "french", "paris", "macron"], "fr", None, False),
    # USA last: national fallback. Trump news -> US flag + Trump face;
    # any named person in the text gets flag + their face via fallback.
    (["u.s.", "usa", "w:us", "united states", "america", "washington",
      "white house", "congress", "senate", "pentagon", "capitol"], "us",
     "Donald Trump", False),
]


# Leadership verification (spec sections 27-28): never trust a permanent
# leader table. OFFICES maps a key -> (Wikipedia page, last-known holder,
# infobox field). The name is only a search hint: before any INFERRED face
# is used, office_verified() confirms the hint against a FRESH Wikipedia
# infobox (incumbent / key_people). People NAMED in the article skip
# verification entirely (the article itself is the current source).
OFFICES = {
    # key -> (Wikipedia page, last-known holder, infobox field to check).
    # The name is only a search hint, always confirmed fresh before use.
    "cn": ("President of China", "Xi Jinping", "incumbent"),
    "in": ("Prime Minister of India", "Narendra Modi", "incumbent"),
    "ru": ("President of Russia", "Vladimir Putin", "incumbent"),
    "ua": ("President of Ukraine", "Volodymyr Zelenskyy", "incumbent"),
    "ir": ("President of Iran", "Masoud Pezeshkian", "incumbent"),
    "il": ("Prime Minister of Israel", "Benjamin Netanyahu", "incumbent"),
    "eu": ("President of the European Central Bank", "Christine Lagarde",
           "incumbent"),
    "de": ("Chancellor of Germany", "Friedrich Merz", "incumbent"),
    "fed": ("Chair of the Federal Reserve", "Kevin Warsh", "incumbent"),
    "apple": ("Apple Inc.", "John Ternus", "key_people"),
}

LEADERSHIP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "leadership.json")


def _leadership_cache():
    try:
        with open(LEADERSHIP_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _leadership_save(cache):
    try:
        with open(LEADERSHIP_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
    except Exception as ex:
        log(f"leadership cache save failed: {ex}")


def _infobox_block(wt: str, field: str) -> str:
    """Raw text of an infobox field (handles multiline template values).
    Returns '' when the field is absent."""
    buf, cap = [], False
    for ln in wt.splitlines():
        if not cap:
            m = re.match(r"\s*\|\s*" + re.escape(field) + r"\s*=(.*)$",
                         ln, re.I)
            if m:
                buf.append(m.group(1))
                cap = True
        else:
            if re.match(r"\s*\|[a-zA-Z_ ]+=", ln):
                break
            buf.append(ln)
    return "\n".join(buf)


def _office_wikitext(page: str) -> str:
    for attempt in range(3):
        try:
            r = requests.get("https://en.wikipedia.org/w/api.php",
                             params={"action": "parse", "page": page,
                                     "prop": "wikitext", "format": "json"},
                             timeout=25,
                             headers={"User-Agent": "ethan-cole-fb-bot/1.0"})
            d = r.json()
            wt = ((d.get("parse") or {}).get("wikitext") or {}).get("*", "")
            if wt:
                return wt
        except Exception:
            pass
        time.sleep(4 * (attempt + 1))
    return ""
def office_verified(key: str) -> bool:
    """True if OFFICES[key]'s hinted officeholder is confirmed by a fresh
    Wikipedia infobox check (cached LEADERSHIP_MAX_AGE_DAYS, default 7).
    A mismatch returns False: leadership may have changed, so the caller
    must fall back to institution/flag visuals, never guess a face.
    Network failure with a prior OK returns True with a warning. Never
    raises."""
    if key not in OFFICES:
        return False
    page, hint, field = OFFICES[key]
    try:
        max_age = int(os.getenv("LEADERSHIP_MAX_AGE_DAYS", "7")) * 86400
    except Exception:
        max_age = 7 * 86400
    cache = _leadership_cache()
    ent = cache.get(key) or {}
    if ent.get("ok") and ent.get("name") == hint:
        try:
            if time.time() - float(ent.get("checked_at", 0)) < max_age:
                return True
        except Exception:
            pass
    try:
        wt = _office_wikitext(page)
        if not wt:
            raise RuntimeError("empty wikitext response")
        raw = _infobox_block(wt, field)
        clean = re.sub(r"[\[\]]", "", raw)
        if field == "key_people":
            # Holder must appear WITH the top role (e.g. Ternus as CEO,
            # not merely mentioned on the page).
            ok = hint.split()[-1].lower() in clean.lower() \
                and "ceo" in clean.lower()
            actual = clean.strip().replace("\n", " ")[:120]
        else:
            m = re.search(r"\[\[([^|\]]+)", raw)
            actual = (m.group(1) if m
                      else clean.strip().split("<")[0].strip())[:80]
            ok = hint.split()[-1].lower() in clean.lower()
        cache[key] = {"name": hint, "checked_at": int(time.time()),
                      "ok": ok, "actual": actual,
                      "source": "en.wikipedia.org/wiki/"
                      + page.replace(" ", "_")}
        _leadership_save(cache)
        if not ok:
            log(f"LEADERSHIP MISMATCH for {key}: expected '{hint}', "
                f"page shows '{actual}' — no inferred face")
        return ok
    except Exception as ex:
        if ent.get("ok") and ent.get("name") == hint:
            log(f"leadership check offline for {key}, using last verified "
                f"({hint}): {ex}")
            return True
        log(f"leadership check failed for {key}: {ex}")
        return False


# Words signalling the office-holder is the story's subject (used with
# fresh office verification; never alone as proof of identity).
LEADER_TITLE_WORDS = ["president", "chairman", "chairwoman", "chair",
                      "ceo", "chief executive", "premier", "prime minister",
                      "chancellor", "governor", "crown prince", " king ",
                      " queen ", " emir "]


def country_photo(candidate):
    """Deterministic flag rule, simple version:
    China news -> China flag + Xi face. USA news -> US flag (+ Trump face
    if Trump named). State news -> that state's flag. Any other named
    person in the text -> flag + their face; else fullscreen flag.
    Anthropic/Claude without a named person gets logo + CEO Dario Amodei.
    Returns (bytes, ext, src) or (None, None, None)."""
    text = candidate.get("title", "") + " " + candidate.get("summary", "")
    text = text.lower()
    title_l = candidate.get("title", "").lower()
    for keys, code, leader, always in _match_table(text, COUNTRY_PHOTOS):
        flag = _flag_photo(code)
        if not flag:
            continue
        face = None
        named = bool(leader) and (leader.lower() in text
                                  or leader.split()[-1].lower() in text)
        # Inferred leaders need BOTH a leadership title in the headline
        # ("president announces...") AND fresh office verification; a bare
        # country story never forces a face (spec sections 6, 22, 28).
        titled = any(w in title_l for w in LEADER_TITLE_WORDS)
        if leader and (named or (always and titled
                                 and office_verified(code))):
            try:
                face = _fetch_face_raw(leader, [leader])
            except Exception:
                face = None
        if not face:
            for keys2, wiki, queries in _match_table(text, PEOPLE_PHOTOS):
                try:
                    face = _fetch_face_raw(wiki, queries)
                except Exception:
                    face = None
                break
        if face:
            try:
                out = _split_pair(flag, face, right_face=True)
            except Exception:
                out = None
            if out:
                return out[0], out[1], "split:flag+face"
        try:
            branded, ext = _brand_image(flag)
            return branded, ext, "flag:" + code
        except Exception:
            continue
    # Anthropic/Claude: product/company story -> branding only; Dario's
    # face only joins when HE is named (spec sections 7, 15, 22).
    if any(k in text for k in ("anthropic", "claude", "amodei",
                                "dario")):
        ldata = None
        lp = os.path.join(ASSETS_DIR, "logos", "anthropic.png")
        if os.path.exists(lp):
            try:
                with open(lp, "rb") as fh:
                    ldata = fh.read()
            except Exception:
                ldata = None
        if ldata and ("amodei" in text or "dario" in text):
            face = None
            try:
                face = _fetch_face_raw("Dario Amodei", ["Dario Amodei"])
            except Exception:
                face = None
            if face:
                try:
                    out = _split_pair(ldata, face, left_logo=True,
                                      right_face=True)
                except Exception:
                    out = None
                if out:
                    return out[0], out[1], "split:face+logo"
        if ldata:
            try:
                card = _logo_card(ldata)
                if card:
                    return card[0], card[1], "entity-logo"
            except Exception:
                pass
    return None, None, None


def split_card(candidate: dict):
    """(bytes, ext, src) two-panel composite for EVERY post: logo+face when
    the story names both, otherwise paired with a curated topic photo
    (face+scene, logo+scene, or scene+scene). Never random, never single."""
    text = f"{candidate.get('title', '')} {candidate.get('summary', '')}".lower()
    link = candidate.get("link", "")
    person = next(iter(_by_position(
        text, _match_table(text, PEOPLE_PHOTOS))), None)
    entity = next(iter(_by_position(
        text, _match_table(text, ENTITY_LOGOS))), None)
    face = None
    if person:
        try:
            face = _fetch_face_raw(person[1], person[2])
        except Exception:
            face = None
    logo = None
    if entity:
        lp = os.path.join(ASSETS_DIR, "logos",
                           f"{_slug(entity[0][0]) or 'entity'}.png")
        if os.path.exists(lp):
            try:
                with open(lp, "rb") as fh:
                    logo = fh.read()
            except Exception:
                logo = None
    scenes: list = []
    live = None
    # Live web scenes stay OFF by default: unvetted web images produced
    # meme garbage. Curated pile only. Enable per-run via LIVE_SCENES=1.
    if os.getenv("LIVE_SCENES", "0") == "1":
        live = _live_scene(" ".join(
            [k for k in (candidate.get("keywords") or []) if not k.startswith("+")][:3])
            or text[:80])
        if live:
            scenes.append(live)
            log("split scene: live web photo")
    for fn in _topic_raw_files(candidate.get("title", ""), text, link, 2):
        p = os.path.join(ASSETS_DIR, "topics", fn)
        if os.path.exists(p):
            try:
                with open(p, "rb") as fh:
                    scenes.append(fh.read())
            except Exception:
                pass
    try:
        if face and logo:
            out = _split_pair(logo, face, left_logo=True, right_face=True)
            kind = "split:face+logo"
        elif face and scenes:
            out = _split_pair(scenes[0], face, right_face=True)
            kind = "split:face"
        elif logo and scenes:
            out = _split_pair(logo, scenes[0], left_logo=True)
            kind = "split:logo"
        elif len(scenes) >= 2:
            out = _split_pair(scenes[0], scenes[1])
            kind = "split:scene"
        elif scenes:
            out = _split_pair(scenes[0], scenes[0])
            kind = "split:scene"
        else:
            return None, None, None
        if out:
            if live:
                kind += "+live"
            return out[0], out[1], kind
    except Exception:
        pass
    return None, None, None


def people_photo(candidate: dict):
    """(jpeg_bytes, ext) face card for a named person, else (None, None)."""
    text = f"{candidate.get('title', '')} {candidate.get('summary', '')}".lower()
    for keys, wiki, queries in _match_table(text, PEOPLE_PHOTOS):
        ckey = "face-" + (_slug(keys[0]) or "person")
        hit = _photo_cache_get(ckey)
        if hit:
            return hit, "jpeg"
        data = _fetch_face_raw(wiki, queries)
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
    for keys, files, queries in _match_table(text, ENTITY_LOGOS):
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
    if not src or src == "text-only":
        return ""
    if src == "face":
        return "Wikipedia"
    if (src or "").startswith("split:"):
        return "Wikipedia / Wikimedia Commons"
    if (src or "").startswith("wikimedia") or src == "entity-logo" \
            or (src or "").startswith("topic:"):
        return "Wikimedia Commons"
    if src == "google":
        return "Google Images"
    if (src or "").startswith("flag:"):
        return "flagcdn"
    if (src or "").startswith("inst:"):
        return "Wikimedia Commons"
    if (src or "").startswith("openverse:"):
        who = src.split(":", 1)[1].strip() or "Openverse"
        return f"{who} via Openverse"
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
    """Disabled per owner request: posts go out with no image attribution."""
    return post


def add_source(post: str, outlet: str) -> str:
    """Disabled per owner request: posts go out with no source line."""
    return post


# Curated topic photos (assets/topics/): hand-picked, visually verified.
# Safety net between entity logos and blind Wikimedia search — a CPI story
# gets Wall Street, an oil story gets pumpjacks, never a random image.
# File rotation per story link spreads variety across posts.
TOPIC_PHOTOS = [
    (["s&p", "nasdaq", "dow", "stock market", "nyse"],
     ["chart-screen.jpg", "stocks-nyse.jpg", "market-hall.jpg",
      "wallstreet.jpg"]),
    (["wall street", "treasury", "bond yield", "ecb"],
     ["wallstreet.jpg", "stocks-nyse.jpg"]),
    (["mortgage", "rates", "yield", "bonds", "dollar"],
     ["cash-dollars.jpg", "wallstreet.jpg", "stocks-nyse.jpg"]),
    (["white house", "trump", "biden", "vance", "congress", "senate",
      "election", "supreme court", "tariff", "trade", "modi", "maga"],
     ["whitehouse.jpg"]),
    (["fed", "powell", "warsh", "fomc", "interest rate", "rate cut",
      "rate hike"],
     ["fed.jpg"]),
    (["bitcoin", "btc"], ["bitcoin-trade.jpg", "bitcoin.jpg"]),
    (["crypto", "ethereum", "defi", "hack", "exchange", "wallet"],
     ["ethereum.jpg", "bitcoin-trade.jpg", "bitcoin.jpg"]),
    (["gold"], ["gold.jpg"]),
    (["silver", "xag"], ["silver.jpg", "silver-bar.jpg"]),
    (["oil", "opec", "brent", "hormuz"], ["oil.jpg"]),
    # NOTE: no bare "gas" here — it matches "gas fees" in DeFi text and used
    # to route crypto stories to the oil photo.
    (["gpu", "semiconductor", "ai chip", "artificial intelligence",
      "generative ai"],
     ["chips.jpg"]),
    (["inflation", "cpi", "jobs report", "gdp", "recession"],
     ["wallstreet.jpg", "market-hall.jpg"]),
]


def _beat_scores(title: str, text: str, rows: list) -> list:
    """Rows ordered by subject relevance. The hook defines the subject, so
    title hits weigh 3x (a bitcoin ETF story that mentions gold/silver in the
    body must resolve bitcoin, not gold). Ties break by table order."""
    tl = (title or "").lower()
    scored = []
    for i, (keys, files) in enumerate(rows):
        s = (sum(3 for k in keys if k in tl)
             + sum(1 for k in keys if k in text))
        if s:
            scored.append((-s, i, keys, files))
    scored.sort()
    return [(keys, files) for _, _, keys, files in scored]


def _score_topic_rows(title: str, text: str) -> list:
    """TOPIC_PHOTOS rows ordered by subject relevance (see _beat_scores)."""
    return _beat_scores(title, text, TOPIC_PHOTOS)


def topic_photo(candidate: dict):
    """(bytes, ext, src) branded topic photo, else (None, None, None)."""
    text = f"{candidate.get('title', '')} {candidate.get('summary', '')}".lower()
    for keys, files in _score_topic_rows(candidate.get("title", ""), text):
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


def _google_photo(query: str):
    """Google Custom Search image lookup (needs GOOGLE_CSE_KEY + CX).
    Real editorial photos instead of stock randomness. Silent skip if
    unconfigured. Returns (bytes, ext) or (None, None)."""
    key = os.getenv("GOOGLE_CSE_KEY", "").strip()
    cx = os.getenv("GOOGLE_CSE_CX", "").strip()
    if not (key and cx):
        return None, None
    try:
        r = requests.get("https://www.googleapis.com/customsearch/v1",
                         params={"key": key, "cx": cx, "q": query,
                                 "searchType": "image", "num": 4,
                                 "imgSize": "large", "safe": "active"},
                         timeout=20)
        for it in r.json().get("items", []):
            u = it.get("link") or ""
            if not u.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                continue
            data, ext = _download_image(u, min_bytes=20000)
            if data and _big_enough(data):
                return data, ext
    except Exception as ex:
        log(f"Google image search failed: {ex}")
    return None, None


def _openverse_photo(query: str):
    """Openverse (open-licensed Flickr etc.) — keyless, commercial-use
    filter, dead-link filter. Returns (bytes, ext, creator) or Nones."""
    if not query or not query.strip():
        return None, None, None
    try:
        r = requests.get("https://api.openverse.org/v1/images/",
                         params={"q": query[:100], "page_size": 6,
                                 "filter_dead": "true",
                                 "license_type": "commercial"},
                         headers={"User-Agent": "ethan-cole-fb-bot/1.0"},
                         timeout=20)
        for it in r.json().get("results", []):
            u = it.get("url") or ""
            if (it.get("width") or 0) < 900:
                continue
            data, ext = _download_image(u, min_bytes=30000)
            if data and _big_enough(data):
                return data, ext, (it.get("creator") or "").strip()
    except Exception as ex:
        log(f"Openverse search failed: {ex}")
    return None, None, None


# Photo selectivity: post a photo only when it's genuinely good (the
# story's own image, a face, a logo, or a split starring one). Generic
# scene splits go text-only. PHOTO_SELECTIVE=0 restores always-photo.
PHOTO_WORTHY = {"source", "og:image", "face", "entity-logo",
                "split:face+logo", "split:face", "split:logo"}


def photo_worth_posting(src) -> bool:
    s = src or ""
    if s.endswith("+live"):
        s = s[:-5]
    if s.startswith("flag:") or s.startswith("inst:"):
        return True
    if s.startswith("split:"):
        return s != "split:scene"
    return s in PHOTO_WORTHY


# Visual subject hierarchy (spec sections 2, 20, 29): person > product/
# company > institution > state/city > country > generic. select_visuals
# implements the decision tree; find_photo() calls it after the story's
# own image, keeping the old fetchers as fallbacks.
INSTITUTIONS = [
    (["federal reserve", "fed", "fomc"], "fed",
     ["Eccles Federal Reserve Building", "Federal Reserve headquarters"]),
    (["white house"], "whitehouse", ["White House Washington DC"]),
    (["u.s. capitol", "us capitol", "capitol hill", "congress"], "capitol",
     ["United States Capitol building"]),
    (["european central bank", "ecb"], "ecb",
     ["European Central Bank Frankfurt"]),
    (["nato"], "nato", ["NATO headquarters Brussels"]),
    (["united nations", "un general assembly", "un security council"],
     "un", ["United Nations headquarters New York"]),
    (["european commission", "berlaymont"], "eu",
     ["Berlaymont Brussels"]),
]


def _match_table(text: str, table: list) -> list:
    """Entries whose keywords appear in text, in table order. A keyword
    prefixed with 'w:' matches on word boundaries instead (e.g. 'w:us'
    matches 'US tariffs' but not 'campus'; 'w:xi' matches 'Xi' not
    'Xiaomi')."""
    out = []
    for e in table:
        for k in e[0]:
            if k.startswith("w:"):
                if re.search(r"\b" + re.escape(k[2:]) + r"\b", text):
                    out.append(e)
                    break
            elif k in text:
                out.append(e)
                break
    return out


def _by_position(text_l: str, matches: list) -> list:
    """Earliest-named-subject-first: the story's subject is usually named
    before background mentions (e.g. FTX before its SpaceX holding), so
    sort matches by first keyword occurrence, not table order."""
    def pos(e):
        best = None
        for k in e[0]:
            if k.startswith("w:"):
                m = re.search(r"\b" + re.escape(k[2:]) + r"\b", text_l)
                i = m.start() if m else -1
            else:
                i = text_l.find(k)
            if i >= 0 and (best is None or i < best):
                best = i
        return best if best is not None else 10 ** 9
    return sorted(matches, key=pos)


def _geo_kind(code: str) -> str:
    return "state" if code.startswith("us-") else "country"


def _bundled_logo_for(entity) -> bytes | None:
    """Bundled assets/logos/<slug>.png bytes, else None."""
    lp = os.path.join(ASSETS_DIR, "logos",
                       f"{_slug(entity[0][0]) or 'entity'}.png")
    if os.path.exists(lp):
        try:
            with open(lp, "rb") as fh:
                return fh.read()
        except Exception:
            return None
    return None


def institution_photo_bytes(inst) -> bytes | None:
    """Raw institution photo bytes via Commons search. Never raises."""
    for q in inst[2]:
        try:
            j = _commons_api({"generator": "search",
                              "gsrsearch": f"filetype:bitmap {q}",
                              "gsrnamespace": "6", "gsrlimit": "8",
                              "prop": "imageinfo", "iiprop": "url|size",
                              "iiurlwidth": "1200"})
            pages = list(((j.get("query") or {}).get("pages") or {})
                         .values())
            data, _ext = _commons_fetch(
                pages, prefer=("building", "headquarters", "logo"))
            if data:
                return data
        except Exception as ex:
            log(f"Commons institution {q[:40]} failed: {ex}")
            continue
    return None


def select_visuals(candidate: dict):
    """(bytes, ext, src) for the story's MAIN subject (spec section 29):
    person > company/product > institution > state/city > country.
    Never forces a famous face: unnamed leaders fall back to flag/
    institution visuals. Returns (None, None, None) on no match."""
    title = candidate.get("title", "")
    text = (title + " " + candidate.get("summary", "")).lower()
    title_l = title.lower()
    persons_t = _match_table(title_l, PEOPLE_PHOTOS)
    persons = _match_table(text, PEOPLE_PHOTOS)
    companies_t = _by_position(
        title_l, [e for e in _match_table(title_l, ENTITY_LOGOS)])
    geos = _match_table(text, COUNTRY_PHOTOS)
    geos_t = _match_table(title_l, COUNTRY_PHOTOS)
    insts = _match_table(text, INSTITUTIONS)

    def face_of(entry):
        try:
            return _fetch_face_raw(entry[1], entry[2])
        except Exception:
            return None

    def flag_of(geo):
        try:
            return _flag_photo(geo[1])
        except Exception:
            return None

    # 1. person vs person ("Xi meets Trump") -> face + face
    if len(persons_t) >= 2:
        f1, f2 = face_of(persons_t[0]), face_of(persons_t[1])
        if f1 and f2:
            try:
                out = _split_pair(f1, f2, left_face=True, right_face=True)
            except Exception:
                out = None
            if out:
                return out[0], out[1], "split:face+face"
    # 2. one person as the subject
    if len(persons_t) == 1:
        f = face_of(persons_t[0])
        if f:
            if companies_t:
                logo = _bundled_logo_for(companies_t[0])
                if logo:
                    try:
                        out = _split_pair(logo, f, left_logo=True,
                                          right_face=True)
                    except Exception:
                        out = None
                    if out:
                        return out[0], out[1], "split:face+logo"
            if insts:
                ibytes = institution_photo_bytes(insts[0])
                if ibytes:
                    try:
                        out = _split_pair(ibytes, f, right_face=True)
                    except Exception:
                        out = None
                    if out:
                        return out[0], out[1], "split:face+inst"
            if geos_t:
                fl = flag_of(geos_t[0])
                if fl:
                    try:
                        out = _split_pair(fl, f, right_face=True)
                    except Exception:
                        out = None
                    if out:
                        return out[0], out[1], "split:flag+face"
            try:
                branded, ext = _brand_image(f)
                return branded, ext, "face"
            except Exception:
                pass
    # 3. single-company subject; named CEO anywhere -> logo + face,
    # else logo. (Two-company pairs are handled at step 5.)
    if len(companies_t) == 1:
        logo = _bundled_logo_for(companies_t[0])
        if logo:
            for p in persons:
                f = face_of(p)
                if f:
                    try:
                        out = _split_pair(logo, f, left_logo=True,
                                          right_face=True)
                    except Exception:
                        out = None
                    if out:
                        return out[0], out[1], "split:face+logo"
            # Unnamed CEO ("Apple CEO announces..."): verified sitting
            # CEO only, never a guess (spec section 11).
            if not persons and ("ceo" in title_l
                                or "chief executive" in title_l):
                okey = {"apple": "apple"}.get(_slug(companies_t[0][0][0]))
                if okey and office_verified(okey):
                    ceo = next((p for p in PEOPLE_PHOTOS
                                if p[1] == OFFICES[okey][1]), None)
                    f = face_of(ceo) if ceo else None
                    if f:
                        try:
                            out = _split_pair(logo, f, left_logo=True,
                                              right_face=True)
                        except Exception:
                            out = None
                        if out:
                            return out[0], out[1], "split:face+logo"
            try:
                card = _logo_card(logo)
                if card:
                    return card[0], card[1], "entity-logo"
            except Exception:
                pass
    # 4. two countries directly involved -> flag + flag
    countries = [g for g in geos if _geo_kind(g[1]) == "country"]
    if len(countries) >= 2 and countries[0][1] != countries[1][1]:
        f1, f2 = flag_of(countries[0]), flag_of(countries[1])
        if f1 and f2:
            try:
                out = _split_pair(f1, f2)
            except Exception:
                out = None
            if out:
                return out[0], out[1], "split:flag+flag"
    # 5. two companies -> logo + logo
    if len(companies_t) >= 2:
        l1 = _bundled_logo_for(companies_t[0])
        l2 = _bundled_logo_for(companies_t[1])
        if l1 and l2:
            try:
                out = _split_pair(l1, l2, left_logo=True, right_logo=True)
            except Exception:
                out = None
            if out:
                return out[0], out[1], "split:logo+logo"
    # 6. institution subject (+ named person -> person + institution).
    # Fed with no person defaults to the VERIFIED sitting chair only.
    if insts:
        tag = insts[0][1]
        ibytes = institution_photo_bytes(insts[0])
        if ibytes:
            for p in persons:
                f = face_of(p)
                if f:
                    try:
                        out = _split_pair(ibytes, f, right_face=True)
                    except Exception:
                        out = None
                    if out:
                        return out[0], out[1], "split:face+inst"
            if tag == "fed" and not persons and office_verified("fed"):
                warsh = next((p for p in PEOPLE_PHOTOS
                              if p[1] == "Kevin Warsh"), None)
                if warsh:
                    f = face_of(warsh)
                    if f:
                        try:
                            out = _split_pair(ibytes, f, right_face=True)
                        except Exception:
                            out = None
                        if out:
                            return out[0], out[1], "split:face+inst"
            try:
                branded, ext = _brand_image(ibytes)
                return branded, ext, "inst:" + tag
            except Exception:
                pass
    # 7. state/country subject -> verified flag logic (leaders only when
    # named or freshly office-verified; else fullscreen flag)
    if geos:
        cimg, cext, csrc = country_photo(candidate)
        if cimg:
            return cimg, cext, csrc
    return None, None, None


def find_photo(candidate: dict):
    """(bytes, ext, src). SUBJECT-FIRST: curated relevance beats source art.
    Oct 2026 incident: a bitcoin ETF story shipped the article's generic
    gold-bars hero image. The story's own subject (face/logo/topic scene)
    always wins now; source/og art is fallback; scraped web photos last
    resort before neutral. X attachments stay deprioritized: X media is
    unvetted (memes, screenshots, pricing cards)."""
    # 1. subject visuals: person/face, entity logo, topic scenes
    vimg, vext, vsrc = select_visuals(candidate)
    if vimg:
        return vimg, vext, vsrc
    simg, sext, ssrc = split_card(candidate)
    if simg:
        return simg, sext, ssrc
    face = people_photo(candidate)
    if face[0]:
        return face[0], face[1], "face"
    card = entity_logo(candidate)
    if card[0]:
        return card[0], card[1], "entity-logo"
    timg, text_, tsrc = topic_photo(candidate)
    if timg:
        return timg, text_, tsrc
    # 2. source art fallback (demoted from first: editorial hero images are
    # generic as often as apt)
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
        gdata, _gext = _google_photo(
            " ".join((candidate.get("keywords") or [])[:3])
            or candidate.get("title", "")[:80])
        if gdata:
            raw = (gdata, "google")
    if not raw:
        odata, _oext, _ocreator = _openverse_photo(
            " ".join((candidate.get("keywords") or [])[:3])
            or candidate.get("title", "")[:80])
        if odata:
            raw = (odata, f"openverse:{_ocreator or 'Openverse'}")
    if not raw:
        # No blind web search: a relevant curated photo always beats a
        # random one. Neutral finance fallback rotates per story link.
        neutral = ["stocks-nyse.jpg", "market-hall.jpg", "wallstreet.jpg"]
        fn = neutral[int(hashlib.sha256(
            candidate.get("link", "").encode()).hexdigest(), 16)
            % len(neutral)]
        p = os.path.join(ASSETS_DIR, "topics", fn)
        if not os.path.exists(p):
            return None, None, None
        try:
            with open(p, "rb") as f:
                branded, ext = _brand_image(f.read())
            return branded, ext, f"topic:{fn}"
        except Exception:
            return None, None, None
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


UPLOAD_W, UPLOAD_H = 1200, 630


def _normalize_upload(data: bytes, ext: str = "jpeg"):
    """Force any outgoing photo to exactly UPLOAD_W x UPLOAD_H.

    Without this the page mixes shapes: 1200x630 cards, 848x1100 portrait
    faces, 3840x1646 hires shots. Facebook crops each one to its own
    containers, so a portrait next to a 1.91:1 card (or an ultra-wide frame)
    renders as if it had been squeezed. One canvas, no surprises.

    _cover only scales proportionally and crops the overflow, so this can
    never stretch a face. Portrait sources are cropped top-biased to keep the
    head in frame. Returns (jpeg_bytes, 'jpeg').
    """
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return data, ext
    top_bias = im.size[1] > im.size[0]
    out = (_cover(im, UPLOAD_W, UPLOAD_H, top_bias=top_bias)
           if im.size != (UPLOAD_W, UPLOAD_H) else im)
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=95, optimize=True, progressive=True)
    return buf.getvalue(), "jpeg"


def publish_photo_to_facebook(image_bytes: bytes, ext: str,
                                caption: str) -> str:
    page_id = os.getenv("FB_PAGE_ID", "").strip()
    token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    if not page_id or not token:
        raise RuntimeError("FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not set")
    # single choke point: nothing reaches Facebook off-canvas
    image_bytes, ext = _normalize_upload(image_bytes, ext)
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


EMOJI_STRIP = None  # lazy compiled (runner fonts lack color emoji)


def _story_text(caption: str) -> list:
    """Body lines for the story card: no hashtags, no tofu emoji."""
    global EMOJI_STRIP
    if EMOJI_STRIP is None:
        import re as _re
        EMOJI_STRIP = _re.compile(
            "[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")
    body = re.sub(r"((?:#\w+\s*)+)\s*$", "", caption).strip()
    lines = [EMOJI_STRIP.sub("", ln).strip()
             for ln in body.splitlines() if ln.strip()]
    return [ln for ln in lines if ln]


def _story_card(caption: str, image: bytes | None):
    """1080x1920 story creative: photo top (when the post has one), the
    actual post text below, house footer. Text-only posts get a full
    text card. This puts the POST (not just a picture) on stories."""
    from PIL import Image, ImageDraw
    import textwrap
    W, H = 1080, 1920
    card = Image.new("RGB", (W, H), (11, 18, 32))
    d = ImageDraw.Draw(card)
    if image is None:
        y = 140
    else:
        try:
            im = Image.open(io.BytesIO(image)).convert("RGB")
        except Exception:
            return None
        # strip our branded footer bar (bottom ~9%) so it doesn't sit mid-story
        im = im.crop((0, 0, im.size[0], int(im.size[1] * 0.91)))
        card.paste(_cover(im, W, 1000), (0, 0))
        d.line([0, 1000, W, 1000], fill=(255, 255, 255), width=3)
        y = 1045
    wrapped: list = []
    for i, ln in enumerate(_story_text(caption)[:10]):
        size = 54 if i == 0 else 36
        width = 20 if i == 0 else 30
        for wline in textwrap.wrap(ln, width=width)[:4 if i == 0 else 3]:
            wrapped.append((wline, size))
    if image is None and wrapped:
        total = sum(s + 10 for _, s in wrapped)
        y = max(120, (1830 - total) // 2)
    for wline, size in wrapped:
        if y > 1760:
            break
        d.text((50, y), wline, font=_font(size), fill=(255, 255, 255))
        y += size + 10
    buf = io.BytesIO()
    _footer(card, 90).save(buf, "JPEG", quality=95)
    return buf.getvalue(), "jpeg"


def publish_story_from_photo(image_bytes: bytes, ext: str,
                             caption: str = "") -> str:
    """Publish the POST as a 24h Page Story (POST_STORIES toggle): renders
    the photo + caption as a vertical story card, uploads it unpublished,
    then publishes via /photo_stories. Bonus step that must never fail
    the run — callers wrap it in try/except."""
    page_id = os.getenv("FB_PAGE_ID", "").strip()
    token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    if not page_id or not token:
        raise RuntimeError("FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not set")
    creative = _story_card(caption, image_bytes) if caption else None
    creative = creative or (image_bytes, ext)
    r = requests.post(
        f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}/photos",
        files={"source": ("story.jpeg", creative[0], "image/jpeg")},
        data={"published": "false", "access_token": token}, timeout=60)
    up = r.json()
    pid = up.get("id")
    if r.status_code != 200 or not pid:
        raise RuntimeError(f"story upload failed: {json.dumps(up)[:200]}")
    r2 = requests.post(
        f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}/photo_stories",
        json={"photo_id": pid, "access_token": token}, timeout=20)
    st = r2.json()
    if r2.status_code != 200 or not st.get("success"):
        raise RuntimeError(f"story publish failed: {json.dumps(st)[:200]}")
    return st.get("post_id", "")


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


def notify_post_live(post_id: str, post_text: str) -> None:
    """One-tap group-share ping (never fails the run): Telegram message with
    the live post URL plus copy/paste share text for manual Group shares
    (Groups API is deprecated, so auto-posting to groups is impossible)."""
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat:
            return
        page_id = os.getenv("FB_PAGE_ID", "").strip()
        if "_" in (post_id or ""):
            pid, suffix = post_id.split("_", 1)
            url = f"https://www.facebook.com/{pid}/posts/{suffix}"
        elif post_id and page_id:
            url = f"https://www.facebook.com/{page_id}/posts/{post_id}"
        elif page_id:
            url = f"https://www.facebook.com/{page_id}"
        else:
            url = ""
        lines = [ln.strip() for ln in (post_text or "").splitlines()
                 if ln.strip()][:2]
        share = " ".join(lines)[:200]
        groups = os.getenv("GROUP_SHARE_TARGETS", "").strip()
        msg = (f"✅ Ethan Cole post live\n{url}\n"
               f"Share text (paste into groups):\n{share}\n"
               f"Groups: {groups or '(set GROUP_SHARE_TARGETS)'}")
        requests.post("https://api.telegram.org/bot" + token + "/sendMessage",
                      json={"chat_id": chat, "text": msg[:4000],
                            "disable_web_page_preview": True},
                      timeout=20)
    except Exception as ex:
        print(f"telegram share ping skipped: {ex}")


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
    """Daily post floor (MIN_POSTS_PER_DAY, default 10).

    Returns (score_discount, catchup). Behind pace -> discount lowers the
    publish bar toward FLOOR_MIN_SCORE (default 2); after
    FLOOR_DEADLINE_HOUR UTC (default 21) with the floor unmet, catchup
    mode shrinks the cooldown so the day still hits its minimum."""
    floor = int(os.getenv("MIN_POSTS_PER_DAY", "14"))
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
    max_age = int(os.getenv("MAX_AGE_MINUTES", "1440"))  # 24h cap
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

    # DAILY FLOOR: at least MIN_POSTS_PER_DAY (default 10) every day, always.
    # Behind pace -> publish bar drops; late-day + unmet -> catchup burst.
    today = now.date().isoformat()
    day_counts = state.get("day_counts", {})
    posts_today = day_counts.get(today, 0)
    floor = int(os.getenv("MIN_POSTS_PER_DAY", "14"))
    discount, catchup = floor_plan(posts_today, now.hour)
    eff_gap = 20 if catchup else int(os.getenv("MIN_POST_GAP_MINUTES", "20"))
    eff_bar = max(int(os.getenv("FLOOR_MIN_SCORE", "2")),
                  int(os.getenv("MIN_PUBLISH_SCORE", "6")) - discount)
    log(f"floor: {posts_today}/{floor} posts today, bar={eff_bar}, "
        f"gap={eff_gap}{' CATCHUP' if catchup else ''}")

    # Cooldown: never post more often than the effective gap (anti-spam:
    # cron runs every 20 min but the page posts ~15/day, not 72).
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

    # Daily cap (live wire: up to ~15/day).
    if posts_today >= int(os.getenv("MAX_POSTS_PER_DAY", "15")):
        log("Daily cap reached. Skipping.")
        return 0

    candidates = (fetch_candidates(max_age) + fetch_x_candidates(max_age)
                  + fetch_tg_candidates(max_age) + fetch_sec_13f(max_age))
    candidates.sort(key=lambda c: c["score"], reverse=True)
    log(f"{len(candidates)} candidates passed filter")
    n_corr = corroboration_boost(candidates)
    if n_corr:
        log(f"Corroborated: {n_corr} stories confirmed by 2+ feeds (+2)")
    # HOT LANE: stories under 60 min old post live — freshness beats polish.
    # Without this, a fresh 4-pointer sits until the evening floor-drop and
    # goes out 12h stale. +2 puts live breaking over the publish bar now.
    n_hot = 0
    for c in candidates:
        a = c.get("age_min")
        if a is not None and a <= 60:
            c["score"] = round(c["score"] + 2, 1)
            c.setdefault("keywords", []).append("+hot")
            n_hot += 1
    if n_hot:
        log(f"Hot lane: {n_hot} stories <60m old (+2)")
        candidates.sort(key=lambda c: c["score"], reverse=True)
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
                        notify_post_live(post_id, vpost)
                    except Exception as ex:
                        log(f"Video publish failed: {ex}")
                        return 4
                    posted.add(vh)
                    state["posted_hashes"] = sorted(posted)[-500:]
                    day_counts[today] = day_counts.get(today, 0) + 1
                    keep_from = (now.date() - timedelta(days=2)).isoformat()
                    state["day_counts"] = {k: v for k, v in day_counts.items()
                                           if k >= keep_from}
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
    pick_topics = sorted({KW_TO_TOPIC[k] for k in pick.get("keywords", [])
                          if k in KW_TO_TOPIC})
    div = diversity_penalty(pick_topics, state.get("history", []))
    if div:
        pick["score"] = round(pick["score"] - div, 1)
        fresh.sort(key=lambda c: c["score"], reverse=True)
        pick = fresh[0]
        log(f"diversity: -{div} fatigue guard, new top [{pick['feed']}]")
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
    if os.getenv("PHOTO_SELECTIVE", "1") == "1" \
            and not photo_worth_posting(src):
        log(f"Photo {src} not worth posting, going text-only.")
        img, src = None, "text-only"
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
            log("Text-only post (no worthy photo).")
            post_id = publish_to_facebook(post)
            log(f"Published (text-only)! FB post id={post_id}")
        notify_post_live(post_id, post)
        if os.getenv("POST_STORIES", "1") == "1":
            try:
                story_id = publish_story_from_photo(img, ext, post)
                log(f"Story published! id={story_id}")
            except Exception as ex:
                log(f"Story skipped (feed post is live): {ex}")
    except Exception as ex:
        log(f"Publish failed: {ex}")
        return 4

    posted.add(h)
    state["posted_hashes"] = sorted(posted)[-500:]
    day_counts[today] = day_counts.get(today, 0) + 1
    keep_from = (now.date() - timedelta(days=2)).isoformat()
    state["day_counts"] = {k: v for k, v in day_counts.items()
                           if k >= keep_from}
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
        "photo": src,
        "at": state["last_post"]["at"],
    })
    state["history"] = hist[-50:]
    save_state(state_file, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
