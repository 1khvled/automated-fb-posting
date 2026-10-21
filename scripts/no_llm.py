#!/usr/bin/env python3
"""No-LLM post builder: the page must never go dark.

A news page's whole value is the daily streak. If every writer is down
(quota, a retired model, a dead free tier) and the bot returns an error,
the page stops posting, the streak breaks, and the algorithm forgets it.

This builds a post from the SOURCE FACTS ONLY - the headline and summary
the feed already gave us - with no model involved. It is less polished than
the LLM version and it never invents anything. It is a floor, not a goal.

For the Arabic page the source feeds are English, so without a translator
the fallback posts the original headline inside a clearly-marked Arabic
frame. Honest and clearly attributed beats a guess.
"""
from __future__ import annotations

import re

# topic -> (english question, arabic question)
QUESTIONS = {
    "crypto": ("What is your read on this - in or out?",
               "شو رأيك في هاد الخبر - داخل ولا خارج؟"),
    "bitcoin": ("Does this change anything for how you size a position?",
                "هل هاد الخبر بيبدل شي في طريقة إدارة صفقتك؟"),
    "eth": ("What does this mean for staking yields?",
            "شو يعني هاد الخبر على العوائد من الستايكنغ؟"),
    "stocks": ("Which name in this story would you actually have owned?",
               "شو الاسم في هاد القصة اللي كنت رح تمتلكه فعلا؟"),
    "ai": ("Where does this actually save you money in your own work?",
           "وين هاد الشي بيوفر عليك فلوس في خدمتك؟"),
    "gold": ("If you hedge with gold, what would you be hedging against?",
             "إذا كنت تحمي حالك بالذهب، شو بالضبط اللي بتحمي حالك منه؟"),
    "macro": ("How does this change the rates picture for you?",
              "كيف هاد الخبر بيبدل صورة أسعار الفائدة عندك؟"),
    "oil": ("What does this do to fuel costs where you live?",
            "شو تأثير هاد الخبر على سعر الوقود عندك؟"),
    "inflation": ("What is one thing you have cut back on because of prices?",
                  "شو الشي الواحد اللي قللت من استهلاكه بسبب الأسعار؟"),
    "default": ("What is your take on this?",
                "شو رأيك في هاد الخبر؟"),
}

LEAD_EN = ["", "", "", "", ""]
LEAD_AR = ["", "", "", "", ""]


def _clean(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^[\s\-\*\|\u2022]+", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = s.replace("**", "").replace("__", "").replace("`", "")
    s = re.sub(r"(?<!\w)#\w+", "", s)
    s = re.sub(r"\s+([.,!?؛])", r"\1", s)
    return s.strip()


def _sentences(text: str, n: int) -> str:
    text = _clean(text)
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?؟])\s+", text)
    out, total = [], 0
    for p in parts:
        if total + len(p) > 420:
            break
        out.append(p)
        total += len(p)
        if len(out) >= n:
            break
    return " ".join(out).strip()


def _question(topics) -> tuple[str, str]:
    for t in (topics or []):
        for k, v in QUESTIONS.items():
            if k in str(t).lower():
                return v
    return QUESTIONS["default"]


def _is_target_lang(text: str, lang: str) -> bool:
    """Can this text be published on this page as-is?

    The no-LLM builder cannot translate. If the source is not already in the
    page's language, the post is refused rather than shown in the wrong
    language - an English post on an Arabic page pushes the audience away
    and teaches the algorithm the page is for someone else."""
    if not text:
        return False
    if lang == "ar":
        arabic = sum(1 for c in text if "\u0600" <= c <= "\u06ff")
        return arabic >= max(8, len(text) * 0.15)
    latin = sum(1 for c in text if c.isascii() and (c.isalpha() or c.isspace()))
    return latin >= len(text) * 0.5


def build_post(candidate: dict, lang: str = "en") -> str:
    """A complete, truthful post with no model involved."""
    title = _clean(candidate.get("title", ""))
    summary = candidate.get("summary", "") or ""
    if not _is_target_lang(title + " " + summary, lang):
        return ""
    topics = candidate.get("keywords", []) or []
    q_en, q_ar = _question(topics)

    body = _sentences(summary, 2)
    if not body:
        body = ""

    if lang == "ar":
        outlet = (candidate.get("feed") or "").strip()
        head = f"🔴 من {outlet}: " if outlet else "🔴 خبر: "
        lines = [head + title]
        if body:
            lines.append("")
            lines.append(body)
        lines.append("")
        lines.append(q_ar)
        lines.append("")
        lines.append("التفاصيل الكاملة في التعليقات.")
        return "\n".join(lines)

    lines = [title]
    if body:
        lines.append("")
        lines.append(body)
    lines.append("")
    lines.append(q_en)
    return "\n".join(lines)


def build_video_post(candidate: dict, lang: str = "en") -> str:
    title = _clean(candidate.get("title", ""))
    if not _is_target_lang(title, lang):
        return ""
    q_en, q_ar = _question(candidate.get("keywords", []) or [])
    if lang == "ar":
        return f"{title}\n\n{q_ar}"
    return f"{title}\n\n{q_en}"
