"""Fix the writer chain and stop the Arabic page from publishing English.

Found 21 Oct 2026, live in the CI log of the Arabic page:

  1. Groq failed with "returned no text (finish_reason=length)". The
     gpt-oss models are REASONING models: they spend the token budget on
     reasoning before emitting the post. max_tokens=1000 was too small,
     so the content came back empty every time. Raising the budget and
     retrying on an empty-but-length-truncated answer restores the free
     fallback. Same for OpenRouter (max_tokens=500) and NVIDIA.

  2. With every model down, the no-LLM builder fired and published the
     RAW ENGLISH SOURCE on the ARABIC page. The page's own QC would have
     rejected it, but the fallback path skipped the QC. Publishing English
     on an Arabic page is worse than publishing nothing: the readers
     leave and the algorithm learns the page is for someone else. So the
     no-LLM builder now returns EMPTY when it cannot write in the target
     language, and the bot skips the run instead.
"""
import shutil
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
LANG = sys.argv[2] if len(sys.argv) > 2 else "en"
bot = REPO / "post_bot.py"
src = bot.read_text(encoding="utf-8")
changed = []

# ---- 1. a bigger token budget for the reasoning models
if '"max_tokens": 1000' in src:
    src = src.replace('"max_tokens": 1000', '"max_tokens": 4000')
    changed.append("groq max_tokens 1000 -> 4000 (reasoning models were "
                   "truncating before they emitted any text)")
if '"max_tokens": 500' in src:
    src = src.replace('"max_tokens": 500', '"max_tokens": 3000')
    changed.append("openrouter max_tokens 500 -> 3000")

# retry once with a much bigger budget when the answer was truncated
old_groq = """        text = (d["choices"][0]["message"].get("content") or "").strip()
        if not text:
            raise RuntimeError(
                f"Groq {model} returned no text "
                f"(finish_reason={d['choices'][0].get('finish_reason')}, "
                f"output_json={_json.dumps(d)[:300]})")
        return text"""
new_groq = """        text = (d["choices"][0]["message"].get("content") or "").strip()
        if not text:
            fr = d["choices"][0].get("finish_reason")
            if fr == "length":
                # A reasoning model burned the whole budget thinking and
                # never emitted the post. Give it a lot more room.
                r2 = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"},
                    json={"model": model, "max_tokens": 12000,
                          "temperature": 0.5,
                          "messages": [{"role": "system", "content": system},
                                       {"role": "user", "content": user}]},
                    timeout=120)
                d2 = r2.json()
                try:
                    text = (d2["choices"][0]["message"].get("content")
                            or "").strip()
                except Exception:
                    text = ""
                if text:
                    return text
            raise RuntimeError(
                f"Groq {model} returned no text "
                f"(finish_reason={d['choices'][0].get('finish_reason')}, "
                f"output_json={_json.dumps(d)[:300]})")
        return text"""
if old_groq in src:
    src = src.replace(old_groq, new_groq, 1)
    changed.append("groq retries with 12000 tokens when the answer was truncated")
else:
    print("  !! groq anchor not found")

# ---- 2. never publish the wrong language
old_fb = """        try:
            post = no_llm.build_post(pick, LANG)
            fallback = True
        except Exception as ex2:
            log(f"no-LLM builder failed too: {ex2}")
            return 2"""
new_fb = """        try:
            post = no_llm.build_post(pick, LANG)
            if not post.strip():
                # The no-LLM builder cannot write Arabic without a model.
                # Publishing the English source on the Arabic page is worse
                # than publishing nothing, so skip the run instead.
                log("no-LLM builder cannot write in the target language - "
                    "skipping this run rather than post the wrong language")
                return 2
            fallback = True
        except Exception as ex2:
            log(f"no-LLM builder failed too: {ex2}")
            return 2"""
if old_fb in src:
    src = src.replace(old_fb, new_fb, 1)
    changed.append("a wrong-language fallback skips the post instead of "
                   "publishing it")
else:
    print("  !! text-branch fallback anchor not found")

old_vid = """                try:
                    vpost = sanitize(no_llm.build_video_post(vpick, LANG))
                    vprobs = []
                except Exception as ex2:
                    vpost, vprobs = None, [f"{ex} | {ex2}"[:160]]"""
new_vid = """                try:
                    vpost = sanitize(no_llm.build_video_post(vpick, LANG))
                    vprobs = ([] if vpost else
                              ["no-LLM builder cannot write in the target "
                               "language - skipping rather than posting the "
                               "wrong language"])
                except Exception as ex2:
                    vpost, vprobs = None, [f"{ex} | {ex2}"[:160]]"""
if old_vid in src:
    src = src.replace(old_vid, new_vid, 1)
    changed.append("the video branch skips too instead of posting the wrong "
                   "language")

bot.write_text(src, encoding="utf-8")

# ---- 3. the no_llm builder itself: refuse to write in a language it cannot
nolm = REPO / "scripts" / "no_llm.py"
n = nolm.read_text(encoding="utf-8")
if "_is_target_lang" not in n:
    n = n.replace(
        "def build_post(candidate: dict, lang: str = \"en\") -> str:",
        '''def _is_target_lang(text: str, lang: str) -> bool:
    """Can this text be published on this page as-is?

    The no-LLM builder cannot translate. If the source is not already in the
    page's language, the post is refused rather than shown in the wrong
    language - an English post on an Arabic page pushes the audience away
    and teaches the algorithm the page is for someone else."""
    if not text:
        return False
    if lang == "ar":
        arabic = sum(1 for c in text if "\\u0600" <= c <= "\\u06ff")
        return arabic >= max(8, len(text) * 0.15)
    latin = sum(1 for c in text if c.isascii() and (c.isalpha() or c.isspace()))
    return latin >= len(text) * 0.5


def build_post(candidate: dict, lang: str = "en") -> str:''', 1)
    n = n.replace(
        '    title = _clean(candidate.get("title", ""))\n    summary = candidate.get("summary", "") or ""',
        '    title = _clean(candidate.get("title", ""))\n'
        '    summary = candidate.get("summary", "") or ""\n'
        '    if not _is_target_lang(title + " " + summary, lang):\n'
        '        return ""', 1)
    n = n.replace(
        '    title = _clean(candidate.get("title", ""))\n    q_en, q_ar = _question(candidate.get("keywords", []) or [])',
        '    title = _clean(candidate.get("title", ""))\n'
        '    if not _is_target_lang(title, lang):\n'
        '        return ""\n'
        '    q_en, q_ar = _question(candidate.get("keywords", []) or [])', 1)
    nolm.write_text(n, encoding="utf-8")
    changed.append("no_llm refuses to write in a language it cannot")
    shutil.copy2(nolm, Path(r"C:\Users\Abdelli\Documents\soq-alyoum-fb-bot\scripts\no_llm.py"))

print(f"[{REPO.name}]")
for c in changed:
    print("  -", c)
if not changed:
    print("  (nothing to do)")
