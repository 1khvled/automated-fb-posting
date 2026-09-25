#!/usr/bin/env python3
"""Model bake-off: generate the same Ethan Cole posts across OpenRouter
free models + Gemini, so a winner (main) and runner-up (backup) can be picked.

Usage:
  OPENROUTER_API_KEY=... GEMINI_API_KEY=... python scripts/bakeoff.py
Keys come from env only — never put them in code or git.
"""
import json
import os
import sys

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import post_bot  # noqa: E402

OR_MODELS = [
    "nvidia/nemotron-3.5-lightning:free",
    "qwen/qwen3.8-27b:free",
    "google/gemma-4-26b-a4b-it:free",
]
GEM_MODELS = ["gemini-2.5-flash", "gemini-3.5-flash-lite"]
NUM_TOPICS = int(os.getenv("NUM_TOPICS", "1"))


def gen_openrouter(model, system, user):
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}",
                 "HTTP-Referer": "https://github.com/ethan-cole-fb-bot",
                 "X-Title": "ethan-cole-fb-bot bakeoff",
                 "Content-Type": "application/json"},
        json={"model": model, "max_tokens": 500, "temperature": 0.5,
              "reasoning": {"exclude": True},  # no leaked thinking traces
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]},
        timeout=90)
    d = r.json()
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {json.dumps(d)[:200]}"
    try:
        return d["choices"][0]["message"]["content"].strip(), None
    except Exception as ex:
        return None, f"parse: {ex} {json.dumps(d)[:200]}"


def gen_gemini(model, system, user):
    key = os.getenv("GEMINI_API_KEY", "").strip()
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
    try:
        return d["candidates"][0]["content"]["parts"][0]["text"].strip(), None
    except Exception:
        return None, f"HTTP {r.status_code}: {json.dumps(d)[:200]}"


def main():
    cands = post_bot.fetch_candidates(int(os.getenv("MAX_AGE_MINUTES", "720")))
    if len(cands) < 2:
        print("not enough fresh candidates for a bake-off")
        return 2
    for i, c in enumerate(cands[:NUM_TOPICS]):
        print(f"\n===== TOPIC {i + 1} [{c['feed']}] score={c['score']} =====")
        print("HEADLINE:", c["title"][:150])
        user = post_bot.USER_TEMPLATE.format(**c)
        for m in OR_MODELS:
            text, err = gen_openrouter(m, post_bot.SYSTEM_PROMPT, user)
            tag = f"OR/{m}"
            if err:
                print(f"\n--- {tag} ERROR: {err}")
                continue
            probs = post_bot.quality_check(text, c["title"])
            print(f"\n--- {tag} (len={len(text)}, QC={probs or 'pass'}) ---\n{text}")
        for m in GEM_MODELS:
            text, err = gen_gemini(m, post_bot.SYSTEM_PROMPT, user)
            tag = f"GEM/{m}"
            if err:
                print(f"\n--- {tag} ERROR: {err}")
                continue
            probs = post_bot.quality_check(text, c["title"])
            print(f"\n--- {tag} (len={len(text)}, QC={probs or 'pass'}) ---\n{text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
