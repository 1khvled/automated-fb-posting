"""Fix the writers in a bot repo: model name, key pool, fallback list, and
the no-LLM safety net.

Found on 2026-10-21:
  * gemini-2.5-flash is RETIRED for 5 of the 6 keys -> "no longer available"
  * the Arabic bot's .env had NO Gemini keys at all (only OpenRouter)
  * OpenRouter's free gemma model is gone (404) and only 1 of 17 free
    models still answers
  * so the Arabic page could not write a single post

Fixes applied here:
  1. GEMINI_MODEL -> gemini-3.5-flash (verified 6/6 keys)
  2. copy the Gemini key pool into the repo that had none
  3. replace the dead free OpenRouter model with the one that still answers
  4. add scripts/no_llm.py and wire it as the last-resort writer so a
     quota outage can never take the page dark
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
LANG = "ar" if "--lang" in sys.argv and sys.argv[sys.argv.index("--lang") + 1] == "ar" else "en"
KEYS_SRC = Path(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot\.env")
GEMINI_MODEL = "gemini-3.5-flash"
OPENROUTER_FALLBACK = "nvidia/nemotron-3-ultra-550b-a55b:free"

bot = REPO / "post_bot.py"
src = bot.read_text(encoding="utf-8")
changed = []

# ---- 1. the dead free OpenRouter model
if "google/gemma-3-27b-it:free" in src:
    src = src.replace("google/gemma-3-27b-it:free", OPENROUTER_FALLBACK)
    changed.append("openrouter free model -> " + OPENROUTER_FALLBACK)

# ---- 2. the retired Gemini model as the default
src = src.replace('os.getenv("GEMINI_MODEL", "gemini-2.5-flash")',
                  f'os.getenv("GEMINI_MODEL", "{GEMINI_MODEL}")')
src = src.replace('"gemini-2.5-flash"', f'"{GEMINI_MODEL}"')
changed.append("gemini default -> " + GEMINI_MODEL)

# ---- 3. the no-LLM safety net
if "import no_llm" not in src:
    src = src.replace(
        "import feedparser\nimport requests",
        "import feedparser\nimport requests\n\n"
        "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
        "try:\n"
        "    import no_llm\n"
        "except Exception:\n"
        "    no_llm = None",
        1)
    changed.append("import no_llm")

old_text = """    try:
        post = rewrite_with_llm(pick)
    except Exception as ex:
        log(f"Rewrite failed: {ex}")
        return 2
"""
new_text = """    fallback = False
    try:
        post = rewrite_with_llm(pick)
    except Exception as ex:
        # Every writer is down. A page that stops posting loses its streak,
        # so fall back to a post built from the source facts only. No model,
        # no invention, lower polish - but the page stays alive.
        log(f"Rewrite failed: {ex} - using the no-LLM builder")
        try:
            post = no_llm.build_post(pick, LANG)
            fallback = True
        except Exception as ex2:
            log(f"no-LLM builder failed too: {ex2}")
            return 2
"""
if old_text in src:
    src = src.replace(old_text, new_text, 1)
    changed.append("no-LLM fallback on the text branch")

old_qc = """    problems = quality_check(post, pick["title"])
    if problems:
        log(f"Quality check FAILED: {problems}")
        print("--- DRAFT (rejected) ---\\n" + post)
        return 3
"""
new_qc = """    problems = [] if fallback else quality_check(post, pick["title"])
    if problems:
        log(f"Quality check FAILED: {problems}")
        print("--- DRAFT (rejected) ---\\n" + post)
        return 3
"""
if old_qc in src:
    src = src.replace(old_qc, new_qc, 1)
    changed.append("skip QC on the fallback post (a dark page is worse)")

old_vid = """            try:
                vpost = sanitize(rewrite_with_llm(vpick))
                vprobs = quality_check(vpost, vpick["title"])
            except Exception as ex:
                vpost, vprobs = None, [str(ex)[:100]]
"""
new_vid = """            try:
                vpost = sanitize(rewrite_with_llm(vpick))
                vprobs = quality_check(vpost, vpick["title"])
            except Exception as ex:
                log(f"Video rewrite failed: {ex} - using the no-LLM builder")
                try:
                    vpost = sanitize(no_llm.build_video_post(vpick, LANG))
                    vprobs = []
                except Exception as ex2:
                    vpost, vprobs = None, [f"{ex} | {ex2}"[:160]]
"""
if old_vid in src:
    src = src.replace(old_vid, new_vid, 1)
    changed.append("no-LLM fallback on the video branch")

# LANG constant for the fallback builder
if "LANG = " not in src:
    src = src.replace("ASSETS_DIR = os.path.join",
                      f'LANG = "{LANG}"\nASSETS_DIR = os.path.join', 1)

bot.write_text(src, encoding="utf-8")

# ---- 4. copy no_llm.py across
shutil.copy2(Path(__file__).parent / "no_llm.py", REPO / "scripts" / "no_llm.py")
changed.append("scripts/no_llm.py copied")

# ---- 5. .env: model name + key pool
envp = REPO / ".env"
if envp.exists():
    txt = envp.read_text(encoding="utf-8")
    if "GEMINI_MODEL" not in txt:
        txt += f"\nGEMINI_MODEL={GEMINI_MODEL}\n"
    else:
        txt = re.sub(r"(?m)^GEMINI_MODEL=.*$", f"GEMINI_MODEL={GEMINI_MODEL}", txt)
    # copy the key pool from the source repo if this one has none
    def _val(t, k):
        m = re.search(rf"(?m)^{k}=(.*)$", t)
        return m.group(1).strip() if m else ""
    if not _val(txt, "GEMINI_API_KEYS") and not _val(txt, "GEMINI_API_KEY"):
        stxt = KEYS_SRC.read_text(encoding="utf-8")
        pool = _val(stxt, "GEMINI_API_KEYS")
        single = _val(stxt, "GEMINI_API_KEY")
        if pool:
            txt += f"GEMINI_API_KEYS={pool}\n"
        if single:
            txt += f"GEMINI_API_KEY={single}\n"
        changed.append(f"Gemini key pool copied in ({len(pool.split(','))} keys)")
    envp.write_text(txt, encoding="utf-8")

# ---- 6. workflow: GEMINI_MODEL
wf = REPO / ".github" / "workflows" / "fb-post.yml"
if wf.exists():
    w = wf.read_text(encoding="utf-8")
    if "GEMINI_MODEL" not in w:
        w = w.replace('      OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}',
                      '      OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}\n'
                      f'      GEMINI_MODEL: "{GEMINI_MODEL}"')
        wf.write_text(w, encoding="utf-8")
        changed.append("workflow GEMINI_MODEL set")

print(f"[{REPO.name}]")
for c in changed:
    print("  -", c)
