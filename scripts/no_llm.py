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

import difflib
import re

# Wire-service prefixes that make a post read like a ticker, not a page.
_WIRE = re.compile(
    r"(?i)^[\s🚨⚡🔴🟠🟡🔵📌❗️]*(?:just\s+in|breaking|developing|alert)"
    r"\s*[:\-–—]\s*")


def _strip_wire(s: str) -> str:
    return _WIRE.sub("", (s or "").strip()).strip()


def _is_shouty(s: str) -> bool:
    letters = [c for c in (s or "") if c.isalpha()]
    return len(letters) >= 30 and sum(c.isupper() for c in letters) / len(letters) > 0.8


def _sentence_case(s: str) -> str:
    """'BAIRD SLASHES NVIDIA TARGET' -> 'Baird slashes Nvidia target'."""
    s = (s or "").strip()
    if not s:
        return s
    low = s.lower()
    keep = {"ai", "us", "uk", "eu", "ceo", "cfo", "cto", "etf", "ipo", "gdp",
            "cpi", "ppi", "pce", "fomc", "sec", "fed", "ecb", "boe", "boj",
            "opec", "nato", "imf", "hmm"}
    words = []
    for w in low.split(" "):
        core = w.strip(".,;:!?()[]\"'")
        if core in keep:
            words.append(w.replace(core, core.upper()))
        else:
            words.append(w)
    out = " ".join(words)
    return out[:1].upper() + out[1:]

# First person in the SOURCE is not first person for the page. A feed that
# writes "our direct experience... we published" is describing itself; copying
# that onto the page claims the experience as Ethan's, which is fabrication.
_FIRST_PERSON = re.compile(
    r"(?i)(?<!the )\b(?:we|our|ours|my|mine|me|i)\b|\b(?:we|i)['’](?:ve|re|ll|m|d)\b")


def _is_first_person(s: str) -> bool:
    return bool(_FIRST_PERSON.search(s or ""))


def _clean(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^[\s\-\*\|\u2022]+", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = s.replace("**", "").replace("__", "").replace("`", "")
    s = re.sub(r"(?<!\w)#\w+", "", s)
    s = re.sub(r"\s+([.,!?؛])", r"\1", s)
    return s.strip()


def _neutral_sentences(text: str, n: int) -> str:
    """Up to n sentences that do not speak in the source's first person."""
    text = _clean(text)
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?؟])\s+", text)
    out, total = [], 0
    for p in parts:
        if not p or _is_first_person(p):
            continue
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
    """A complete, truthful post with no model involved.

    Reads like a wire brief, not a template: the headline with any wire
    prefix stripped, then the facts. No appended question - a generic
    "what do you think?" on every post is exactly the generated feel the
    page is trying to lose.
    """
    title = _strip_wire(_clean(candidate.get("title", "")))
    summary = candidate.get("summary", "") or ""
    if not _is_target_lang(title + " " + summary, lang):
        return ""
    # The page is Ethan Cole, not the feed. Any sentence that speaks in the
    # source's own first person is dropped - publishing it would claim the
    # source's experience, opinion or scoop as the page's own.
    title_is_fp = _is_first_person(title)
    body = _neutral_sentences(summary, 3)
    if title_is_fp:
        title = ""
    # Feeds often repeat the headline as the summary's first sentence.
    # Drop it rather than print the same line twice.
    if body and title:
        first = re.split(r"(?<=[.!?؟])\s+", body)[0]
        if difflib.SequenceMatcher(None, first.lower(), title.lower()).ratio() > 0.7:
            rest = body[len(first):].strip()
            body = rest

    # A shouted headline is the biggest "bot" tell. If the summary carries
    # the facts in normal prose, lead with that instead of the caps title.
    if not title:
        lines = [body] if body else []
    elif body and _is_shouty(title):
        lines = [body]
    else:
        lines = [_sentence_case(title) if _is_shouty(title) else title]
        if body:
            lines += ["", body]
    if not lines:
        return ""

    if lang == "ar":
        outlet = (candidate.get("feed") or "").strip()
        head = f"من {outlet}: " if outlet else ""
        return "\n".join([head + lines[0]] + lines[1:]).strip()

    return "\n".join(lines).strip()


def build_video_post(candidate: dict, lang: str = "en") -> str:
    title = _strip_wire(_clean(candidate.get("title", "")))
    if not _is_target_lang(title, lang):
        return ""
    return title
