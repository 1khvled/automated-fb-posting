#!/usr/bin/env python3
"""
check_posts.py — house-style QC for content/product_posts.json.

Runs the same rules the posting bot enforces (post_bot.py quality_check /
_outlet_leak / _latin_allow / _latin_runs / _dialect_hits / _emoji_lines)
plus two product-campaign specific gates:

  1. TRACEABILITY — every number that appears in the copy must also appear
     in that post's `source` field, so no figure can be invented.
  2. IDENTIFICATION — a company name may only appear with its ticker.

Usage:
    python check_posts.py            # checks this repo's content/product_posts.json
    python check_posts.py --json path/to/product_posts.json --lang en
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- copied from the bots so this checker cannot drift from them -------
OUTLET_TOKENS = (
    "deitaone", "kobeissiletter", "watcherguru", "megatron",
    "financialjuice", "firstsquawk", "stockmktnewz", "unusual_whales",
    "breakingdeals", "wallstengine", "financefeeds", "doomberg",
    "coindesk", "cointelegraph", "bitcoinmagazine", "newsquawk",
    "degeneratenews", "clashreport", "congresstrading", "burrytracker",
    "pelositracker", "testingcatalog", "chatgptapp", "priyannkaaaa",
    "bridgemindai", "techcrunch", "bbc", "aljazeera",
)
OUTLET_SHORT = ("cnbc", "sofi", "verge", "ft")
ENGAGEMENT_BAIT = [
    "comment below", "share this", "share if", "tag a friend",
    "like and share", "like if", "follow for more", "comment yes",
    "drop a comment", "type yes",
]
DIALECT_STRONG = ("مش", "عشان", "علشان", "كده", "بقى", "ازاي", "دلوقتي",
                  "برضه", "خلاص", "لسه", "exaيز", "أوي")
MAX_HASHTAGS = 6

# Companies that must always carry their ticker.
TICKERED = {
    "nvidia": "NVDA", "apple": "AAPL", "microsoft": "MSFT",
    "google": "GOOGL", "amazon": "AMZN", "meta": "META",
    "tesla": "TSLA", "broadcom": "AVGO", "coinbase": "COIN",
    "strategy": "MSTR", "vistra": "VST", "strive": "SATA",
}
# Names that are formulas / scores / platforms, not listed companies.
NOT_COMPANIES = {"altman", "piotroski", "beneish", "dupont", "tradingview",
                 "edgetrading", "stockerai", "pine", "capm", "wacc", "dcf",
                 "sec", "edgar", "yahoo", "finance"}
# Product names that are allowed to appear without a ticker.
PRODUCT_NAMES = {"edgetrading", "stockerai", "edge trading", "pine",
                 "tradingview", "pro", "cot", "cot index", "monte carlo",
                 "composite score", "f-score", "m-score", "z-score",
                 "p/e", "peg", "ev/ebitda", "roe", "rss", "txt", "pdf"}


def _outlet_leak(text):
    low = text.lower()
    for tok in OUTLET_TOKENS:
        if tok in low:
            return tok
    for tok in OUTLET_SHORT:
        if re.search(r"\b" + tok + r"\b", low):
            return tok
    return None


def _latin_runs(text):
    best = cur = 0
    for tok in re.split(r"\s+", text):
        t = tok.strip(".,!?;:\"“”'()#$%@").strip()
        if re.fullmatch(r"[A-Za-z]{2,}", t or ""):
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _dialect_hits(text):
    n = sum(text.count(w) for w in DIALECT_STRONG)
    n += len(re.findall(r"[\s(\"“']ب[يتى]\w+", text))
    return n


def _emoji_lines(text):
    n = 0
    for ln in text.split("\n"):
        s = ln.strip()
        if s and not s.startswith("#") and ord(s[0]) >= 0x2190:
            n += 1
    return n


def _arabic_ratio(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if "\u0600" <= c <= "\u06ff") / len(letters)


def _numbers(text):
    out = []
    for m in re.finditer(r"\d+(?:[.,]\d+)*", text):
        tok = m.group(0).replace(",", "")
        out.append(tok)
    return out


def _normalise_numbers(text):
    return {n.replace(",", "") for n in _numbers(text)}


def _traceable(n, src_norm):
    """The number must appear in the source as a standalone figure:
    '15' is found inside '15.0%', '1000' inside '1,000'."""
    return re.search(r"(?<![\d.])" + re.escape(n) + r"(?![\d])", src_norm) is not None


def check_post(post, lang):
    p = []
    pid = post.get("id", "?")
    title = post.get("title", "")
    body = post.get("body", "")
    tags = post.get("hashtags", [])
    cta = post.get("cta", "")
    questions = post.get("questions", [])
    src = post.get("source", "")
    img = post.get("image", "")

    copy = "\n".join([title, body] + questions + [cta])
    full = "\n".join([title, body] + tags + questions + [cta])

    # -- schema ---------------------------------------------------------
    for f in ("id", "lang", "title", "body", "hashtags", "image",
              "questions", "cta"):
        if f not in post or post[f] in (None, "", []):
            p.append(f"missing field '{f}'")
    if post.get("lang") != lang:
        p.append(f"lang is {post.get('lang')!r}, expected {lang!r}")
    if not isinstance(questions, list) or len(questions) < 1:
        p.append("questions must be a non-empty list")
    if not isinstance(tags, list):
        p.append("hashtags must be a list")
        tags = []

    # -- title: hook with a number --------------------------------------
    if not re.search(r"\d", title):
        p.append("title has no number")
    if len(title) > 110:
        p.append(f"title too long ({len(title)} chars)")
    if title.count("\n"):
        p.append("title must be a single line")

    # -- body ------------------------------------------------------------
    sentences = [s for s in re.split(r"(?<=[.!?؟])\s+|\n", body) if s.strip()]
    if not (2 <= len(sentences) <= 4):
        p.append(f"body should be 2-3 short sentences/lines (got {len(sentences)})")

    # -- hashtags --------------------------------------------------------
    if not (5 <= len(tags) <= MAX_HASHTAGS):
        p.append(f"hashtag count {len(tags)} (must be 5-6)")
    if tags and tags[0].lower() != "#ethancole":
        p.append(f"first hashtag is {tags[0]!r}, must be #ethancole")
    if len(set(t.lower() for t in tags)) != len(tags):
        p.append("duplicate hashtags")

    # -- numbers ---------------------------------------------------------
    if not _numbers(title + " " + body):
        p.append("no number in title/body")
    if src:
        src_norm = src.replace(",", "")
        for n in _normalise_numbers(copy):
            if not _traceable(n, src_norm):
                p.append(f"number {n!r} is not traceable to `source`")
                break
    else:
        p.append("no `source` field — claims are not traceable")

    # -- house bans ------------------------------------------------------
    if "http" in full:
        p.append("contains a URL")
    if "@" in full:
        p.append("contains an @handle")
    if re.search(r"(?i)\bwww\.|\.(com|org|net|io)\b", full):
        p.append("contains a bare domain")
    leak = _outlet_leak(full)
    if leak:
        p.append(f"names outlet/feed '{leak}'")
    if re.search(r"(?i)(?<![\w-])sources?\s*:|🔗|📸", full):
        p.append("contains an attribution line")
    if "*" in full or "`" in full:
        p.append("contains markdown asterisk/backtick")
    if re.search(r"(?m)^#{1,6}\s", full):
        p.append("contains a markdown header")
    if re.search(r"(?i)\b_\w+_", full):
        p.append("contains markdown underscore emphasis")
    low = full.lower()
    for bait in ENGAGEMENT_BAIT:
        if bait in low:
            p.append(f"engagement bait ({bait!r})")
    if re.search(r"\bguarantee|\bguaranteed|رضية مضمونة", full, re.I):
        p.append("contains a guarantee claim")

    # -- identification: company => ticker -------------------------------
    for name, tic in TICKERED.items():
        for m in re.finditer(r"(?i)\b" + name + r"\b", copy):
            tail = copy[m.end():m.end() + 12]
            if not tail.strip().startswith(f"(${tic})"):
                p.append(f"company '{name}' mentioned without ({tic})")
                break

    # -- language-specific ----------------------------------------------
    if lang == "en":
        n = len(title) + len(body) + len(" ".join(tags))
        if not (180 <= n <= 350):
            p.append(f"post length {n} chars, house band is 180-350")
    else:
        if _arabic_ratio(full) < 0.40:
            p.append(f"only {_arabic_ratio(full):.0%} Arabic letters")
        if len(full) < 150 or len(full) > 600:
            p.append(f"post length {len(full)} chars, house band is 150-600")
        if _latin_runs(full) >= 3:
            p.append("English phrase (3+ Latin words) inside Arabic copy")
        if _dialect_hits(full) < 1:
            p.append("no Arabic dialect marker")
        if _emoji_lines(full) < 2:
            p.append("fewer than 2 emoji-led lines")
        if re.search(r"(?:^|(?<=\s))(?:[\u0600-\u06FF]{1,2} ){2,}[\u0600-\u06FF]{1,2}"
                     r"(?=\s|$|[.،؟!…])", full):
            p.append("spelled-out acronym")
        # every Latin token must be a ticker, a product name, or present in
        # the post's own `source` (the bot folds source words into its
        # Latin allowlist).
        allowed = set(PRODUCT_NAMES)
        allowed |= {"ethancole", "sway", "al"}
        for name, tic in TICKERED.items():
            allowed.add(name)
            allowed.add(tic.lower())
        allowed |= {w.lower() for w in re.findall(r"[A-Za-z]{2,}", src)}
        bad = sorted({t for t in re.findall(r"\$?([A-Za-z]{2,})", full)
                      if t.lower() not in allowed})
        if bad:
            p.append(f"unlisted Latin words {bad[:5]}")

    # -- image ------------------------------------------------------------
    if not os.path.isabs(img):
        p.append("image path is not absolute")
    elif not os.path.exists(img):
        p.append(f"image missing: {img}")
    else:
        try:
            from PIL import Image
            with Image.open(img) as im:
                if im.size != (1200, 630):
                    p.append(f"image is {im.size}, must be 1200x630")
        except Exception as e:
            p.append(f"image unreadable: {e}")
        if os.path.splitext(os.path.basename(img))[0] != pid:
            p.append("image filename does not match the post id")
    # the bot resolves image_rel first: it must exist next to this file
    rel = post.get("image_rel", "")
    if not rel:
        p.append("no image_rel (the bot needs a repo-relative path)")
    elif not os.path.exists(os.path.join(HERE, rel)):
        p.append(f"image_rel does not resolve: {rel}")
    elif os.path.abspath(os.path.join(HERE, rel)) != os.path.abspath(img):
        p.append("image and image_rel point at different files")

    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(HERE, "product_posts.json"))
    ap.add_argument("--lang", default=None)
    args = ap.parse_args()

    posts = json.load(open(args.json, encoding="utf-8"))
    if isinstance(posts, dict):
        posts = posts.get("posts", [])
    lang = args.lang or (posts[0].get("lang") if posts else "en")

    failed = 0
    ids = set()
    print(f"checking {args.json}  (lang={lang}, {len(posts)} posts)\n")
    for post in posts:
        pid = post.get("id", "?")
        if pid in ids:
            print(f"FAIL {pid}: duplicate id")
            failed += 1
        ids.add(pid)
        problems = check_post(post, lang)
        if problems:
            failed += 1
            print(f"FAIL {pid}")
            for pr in problems:
                print(f"       - {pr}")
        else:
            print(f"PASS {pid}")

    print(f"\n{len(posts) - failed} passed, {failed} failed, {len(posts)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
