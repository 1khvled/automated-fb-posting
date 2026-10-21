#!/usr/bin/env python3
"""Growth engine: the two things that actually make a 0-follower page grow.

1. GROUP DISTRIBUTION. Facebook's Groups API is dead, so a post cannot be
   pushed into groups automatically - it has to be pasted. That is a manual
   step, so the job of the bot is to make the step take five seconds: one
   Telegram message, per post, with the ready-to-paste text for three
   different kinds of group, and the shortlist of groups to paste into.
   This is THE follower mechanism for a small page. The algorithm will not
   surface a page with no followers; a group will.

2. COMMENT REPLIES. Reach on Facebook is driven by comment count, and a
   comment that is answered pulls a second person in. The page replies to
   every comment within minutes, in the same language, with a real answer.
   Plus one seed comment per post to start the thread.

3. MONETISATION READINESS. Facebook Content Monetization is invite-only and
   needs specific thresholds. The tracker says exactly how far away they are,
   so the moment to apply is never a guess.

Nothing here posts engagement bait ("like and share") - that is explicitly
excluded by the platforms' own monetisation rules and it repels readers.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FB_API_VERSION = "v26.0"

# ---------------------------------------------------------------- share kit
# topic -> (group types that want this, one-line why)
TOPIC_GROUPS = {
    "crypto": ("Crypto & Web3 groups, DeFi, altcoin trading rooms",
               "these groups are the highest-intent audience for any crypto story"),
    "bitcoin": ("Bitcoin groups, halving watchlists, BTC/ETH trading rooms",
                "the same audience, sharper"),
    "eth": ("Ethereum staking groups, L2 and DeFi rooms", "same crowd, ETH-native"),
    "stocks": ("Stock-picking groups, dividend and value-investing groups, "
               "per-stock fan groups",
               "single-ticker fan groups are the cheapest reach on Facebook"),
    "ai": ("AI-tool groups, AI-for-work groups, indie-maker and SaaS groups, "
           "AI news groups",
           "AI is the one topic where the audience is still growing"),
    "gold": ("Gold and safe-haven groups, macro and inflation groups, "
             "precious-metals groups", "a real niche with almost no competition"),
    "macro": ("Macro/economics groups, recession-watch groups, "
              "central-bank watchers", "fewer posts, high-quality comments"),
    "oil": ("Energy and oil groups, OPEC watchers, commodities groups",
            "oil moves fast and the crowd is small but loud"),
    "inflation": ("Personal-finance groups, money-management groups, "
                  "inflation-hedge groups", "the most relatable topic for readers"),
    "default": ("General finance and business groups, your city/country "
                "business groups, and any group you already read",
                "niche groups convert; general groups give volume"),
}

# three share angles, so the same post can go into three different groups
# without looking like a copy-paste spammer
ANGLES = [
    ("Insight", "{title}\n\n{line}\n\n{cta}"),
    ("Number", "{number_line}\n\n{title}\n\n{cta}"),
    ("Question", "{question}\n\n{title}\n\n{cta}"),
]


def share_variants(title: str, text: str, topics: list, cta: str,
                   lang: str = "en") -> list:
    """Three ready-to-paste share messages + the groups to paste them into."""
    text = (text or "").strip()
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    first = lines[0] if lines else title
    # the most useful line: the one with a number, else the second line
    numeric = next((ln for ln in lines if re.search(r"\d", ln)), "")
    body_line = numeric or (lines[1] if len(lines) > 1 else first)

    grp_hits = []
    for t in topics or []:
        for key, (groups, why) in TOPIC_GROUPS.items():
            if key in str(t).lower() and key not in [g[0] for g in grp_hits]:
                grp_hits.append((key, groups, why))
    if not grp_hits:
        grp_hits = [("default", *TOPIC_GROUPS["default"])]

    out = []
    for i, (label, tmpl) in enumerate(ANGLES):
        key, groups, why = grp_hits[i % len(grp_hits)]
        if label == "Number":
            core = numeric or body_line
        elif label == "Question":
            core = "What does this mean for you?"
        else:
            core = body_line
        msg = tmpl.format(title=title, line=core, number_line=core,
                           question=core, cta=cta)
        out.append({
            "angle": label,
            "group_type": groups,
            "why": why,
            "text": msg,
        })
    return out


def format_share_kit(title: str, post_url: str, variants: list,
                     lang: str = "en") -> str:
    """The Telegram payload: one block per share angle, copy-paste ready."""
    if lang == "ar":
        head = ("📣 نشر جديد — انسخ والصق في 3 مجموعات:\n"
                f"🔗 {post_url}\n")
    else:
        head = ("📣 NEW POST - copy/paste into 3 different groups:\n"
                f"🔗 {post_url}\n")
    parts = [head]
    for i, v in enumerate(variants, 1):
        if lang == "ar":
            parts.append(f"\n--- {i}. [{v['angle']}] ---\n{v['text']}\n"
                         f"👥 المجموعات: {v['group_type']}\n"
                         f"💡 {v['why']}")
        else:
            parts.append(f"\n--- {i}. [{v['angle']}] ---\n{v['text']}\n"
                         f"👥 Groups: {v['group_type']}\n"
                         f"💡 {v['why']}")
    parts.append("\n⚠️ One post per group. Do not paste the same angle twice "
                 "into the same group.")
    return "".join(parts)


# ---------------------------------------------------------------- comments
def _page_token() -> str:
    return os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()


def _page_id() -> str:
    return os.getenv("FB_PAGE_ID", "").strip()


def fetch_recent_comments(fb_ids: list, limit: int = 50) -> list:
    """All comments on the given posts, newest first."""
    tok = _page_token()
    out = []
    for fid in fb_ids:
        if not fid:
            continue
        try:
            r = requests.get(
                f"https://graph.facebook.com/{FB_API_VERSION}/{fid}/comments",
                params={"fields": "id,message,created_time,from{name}",
                        "limit": limit, "access_token": tok}, timeout=20)
            d = r.json() or {}
            if "error" in d:
                continue
            for c in d.get("data", []):
                c["_post"] = fid
                out.append(c)
        except Exception:
            continue
    return out


def post_reply(comment_id: str, message: str) -> bool:
    tok = _page_token()
    try:
        r = requests.post(
            f"https://graph.facebook.com/{FB_API_VERSION}/{comment_id}/comments",
            params={"access_token": tok}, json={"message": message}, timeout=20)
        d = r.json() or {}
        ok = "error" not in d
        if not ok:
            print(f"  reply failed: {json.dumps(d)[:140]}", file=sys.stderr)
        return ok
    except Exception as e:  # noqa: BLE001
        print(f"  reply error: {type(e).__name__}", file=sys.stderr)
        return False


def post_seed_comment(post_id: str, question: str) -> str:
    """The page comments on its own post first - it starts the thread and
    doubles as the engagement question."""
    tok = _page_token()
    try:
        r = requests.post(
            f"https://graph.facebook.com/{FB_API_VERSION}/{post_id}/comments",
            params={"access_token": tok}, json={"message": question}, timeout=20)
        d = r.json() or {}
        if "error" in d:
            return ""
        return d.get("id", "")
    except Exception:
        return ""


# ---------------------------------------------------------------- money
# Facebook Content Monetization gates (invite-only) and the fan-funding tier.
MONETISATION_GATES = [
    ("followers", 5000, "Facebook Content Monetization - followers"),
    ("minutes_viewed_60d", 60000, "Facebook Content Monetization - minutes viewed (60d)"),
    ("subscribers", 1000, "YouTube Partner Program - subscribers"),
    ("watch_hours_365d", 4000, "YouTube Partner Program - watch hours (365d)"),
    ("shorts_views_90d", 10000000, "YouTube Partner Program - Shorts views (90d)"),
    ("videos", 5, "YouTube Partner Program - uploaded videos"),
]


def monetisation_readiness(snap: dict) -> str:
    lines = ["", "=" * 62, "  MONETISATION READINESS", "=" * 62]
    for key, target, label in MONETISATION_GATES:
        have = snap.get(key) or 0
        pct = min(100.0, (have / target * 100.0)) if target else 0.0
        bar = "#" * int(pct / 5) + "." * (20 - int(pct / 5))
        lines.append(f"  {label:<46} {have:>10,.0f} / {target:<9,.0f} "
                     f"[{bar}] {pct:5.1f}%")
    lines.append("")
    lines.append("  Apply when the Facebook row is 100%. It is invite-only, so")
    lines.append("  submit the interest form the day you cross the line:")
    lines.append("  Page -> Professional Dashboard -> Monetization ->")
    lines.append("  Content Monetization -> interest form.")
    lines.append("  Until then the money on this page is the CLIENT SERVICE")
    lines.append("  (the 13k/19k/30k DZD packages) - the page is the proof.")
    return "\n".join(lines)


REPLY_SYSTEM = {
    "en": ("You are the page. Reply to a reader's comment under a finance/markets "
           "post. One or two short sentences. Answer what they actually asked, "
           "using only facts already in the post. Be warm and specific, never "
           "generic. No emoji spam, no 'like and share', no follow-begging. "
           "If the comment is a question you cannot answer from the post, say "
           "what is actually happening and keep it honest."),
    "ar": ("أنت الصفحة. ترد على تعليق قارئ تحت منشور عن الأسواق والمال. "
           "جملة أو جملتان قصيرتان. تجيب على ما سأل فعلا، مع المعلومات "
           "الموجودة في المنشور فقط. دافئ ومحدد، لا عمومي. بدون إيموجي مبالغ "
           "فيه، وبدون طلب مشاركة أو متابعة. إذا كان السؤال خارج المنشور، قل "
           "بصراحة ما هو معروف وما هو غير معروف."),
}

SEED_SYSTEM = {
    "en": ("Write ONE short question that a real reader of a finance/markets "
           "page would want to answer, based on the post below. It must be a "
           "genuine question about the reader's own situation or opinion - not "
           "'like and share', not 'what do you think'. One line, no emoji."),
    "ar": ("اكتب سؤالا واحدا قصيرا قد يجيب عليه قارئ حقيقي لصفحة عن الأسواق. "
           "يجب أن يكون سؤالا حقيقيا عن رأيه أو وضعه، وليس 'شارك' ولا "
           "'ما رأيك'. سطر واحد بدون إيموجي."),
}


def _telegram(text: str) -> bool:
    tok = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not tok or not chat:
        return False
    try:
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      json={"chat_id": chat, "text": text[:4000],
                            "disable_web_page_preview": True}, timeout=20)
        return True
    except Exception:
        return False


def after_publish(post_id: str, post_text: str, title: str, topics: list,
                  llm=None, lang: str = "en") -> dict:
    """Run right after a post goes live: start the thread, hand over the
    share kit. Everything here is best-effort - it must never fail a post."""
    out = {"seed_comment_id": "", "share_sent": False}
    # A photo post's node id is "pageid_photoid"; a video post's is a bare
    # id. The COMMENT endpoint needs the full node id, not the last segment.
    node = (post_id or "").strip()
    pid = node.split("_")[-1] if node else ""

    # 1. a genuine question as the first comment (starts the thread)
    question = ""
    if llm:
        try:
            question = llm(SEED_SYSTEM[lang],
                           f"Post:\n{post_text[:900]}").strip()
            question = re.sub(r"^[\"'`]|[\"'`]$", "", question).strip()
            question = question.split("\n")[0][:180]
        except Exception:
            question = ""
    if not question:
        question = ("What does this mean for your portfolio?"
                    if lang == "en" else "شنو يعني هذا لمحفظتك؟")
    if node:
        out["seed_comment_id"] = post_seed_comment(node, question) or \
            post_seed_comment(pid, question)

    # 2. the share kit
    try:
        cta = ("Full breakdown on the page - link below."
               if lang == "en" else "التحليل الكامل في الصفحة - الرابط تحت.")
        variants = share_variants(title or (post_text or "")[:80], post_text,
                                  topics, cta, lang)
        page = _page_id()
        url = (f"https://www.facebook.com/{page}/posts/{pid}" if page and pid
               else "")
        out["share_sent"] = _telegram(format_share_kit(title, url, variants, lang))
    except Exception:
        pass
    return out


def reply_backlog(state: dict, llm=None, lang: str = "en", max_posts: int = 8,
                  max_replies: int = 12) -> int:
    """Answer every unanswered comment on the recent posts.

    Comment count is what drives reach on Facebook, and an answered comment
    pulls a second reader in. Replies are written in the page's language and
    are short. This is the engagement half of the growth engine."""
    replied = set(state.get("replied_comments") or [])
    history = [h for h in (state.get("history") or []) if h.get("fb_id")][-max_posts:]
    if not history:
        return 0
    comments = fetch_recent_comments([h["fb_id"] for h in history])
    if not comments:
        return 0
    # newest first, and skip anything already answered
    comments.sort(key=lambda c: c.get("created_time") or "", reverse=True)
    n = 0
    for c in comments:
        if n >= max_replies:
            break
        cid = c.get("id")
        msg = (c.get("message") or "").strip()
        if not cid or not msg or cid in replied:
            continue
        if msg.lower() in ("like", "👍", "🔥", "❤️", "❤", "nice", "good"):
            replied.add(cid)
            continue
        reply = ""
        if llm:
            try:
                reply = llm(REPLY_SYSTEM[lang],
                            f"Post:\n{(state.get('last_post') or {}).get('title', '')}\n\n"
                            f"Comment:\n{msg[:400]}").strip()
                reply = re.sub(r"^[\"'`]|[\"'`]$", "", reply).strip().split("\n")[0][:300]
            except Exception:
                reply = ""
        if not reply:
            replied.add(cid)
            continue
        if post_reply(cid, reply):
            replied.add(cid)
            n += 1
            time.sleep(1.5)          # never hammer the API
    state["replied_comments"] = sorted(replied)[-500:]
    return n


if __name__ == "__main__":
    demo = share_variants(
        "Bitcoin whale moves $34 million in BTC it got in 2013",
        "🚨 JUST IN: Bitcoin ($BTC) whale MOVES $34 MILLION.\n"
        "A long-dormant wallet from 2013 just transferred 250 BTC.\n"
        "Odds of a market impact: unclear.",
        ["crypto", "bitcoin"],
        "Full read on the page - link in the first comment.")
    for v in demo:
        print("=" * 60)
        print(v["angle"], "|", v["group_type"])
        print(v["text"])
    print()
    print(monetisation_readiness({"followers": 6, "minutes_viewed_60d": 0}))
