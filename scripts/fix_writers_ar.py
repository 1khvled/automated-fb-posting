"""Wire the no-LLM floor into the Arabic bot (its code differs from the English one).

Same three changes as fix_writers.py, but against the soq code shape:
  post = rewrite_with_llm(pick, shape)   <- takes a shape argument
  quality_check(post, title, summary)    <- takes a summary argument
"""
import shutil
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
bot = REPO / "post_bot.py"
src = bot.read_text(encoding="utf-8")
changed = []

old = """    try:
        post = rewrite_with_llm(pick, shape)
    except Exception as ex:
        log(f"Rewrite failed: {ex}")
        return 2
"""
new = """    fallback = False
    try:
        post = rewrite_with_llm(pick, shape)
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
if old in src:
    src = src.replace(old, new, 1)
    changed.append("no-LLM fallback on the text branch")
else:
    print("  !! text-branch anchor not found")

old_qc = """    problems = quality_check(post, pick["title"], pick.get("summary", ""))
    if problems:
"""
new_qc = """    problems = ([] if fallback else
                quality_check(post, pick["title"], pick.get("summary", "")))
    if problems:
"""
if old_qc in src:
    src = src.replace(old_qc, new_qc, 1)
    changed.append("skip QC on the fallback post (a dark page is worse)")
else:
    print("  !! qc anchor not found")

old_v = """            try:
                vpost = sanitize(rewrite_with_llm(vpick))
                vprobs = quality_check(vpost, vpick["title"],
                                       vpick.get("summary", ""))
            except Exception as ex:
                vpost, vprobs = None, [str(ex)[:100]]
"""
new_v = """            try:
                vpost = sanitize(rewrite_with_llm(vpick))
                vprobs = quality_check(vpost, vpick["title"],
                                       vpick.get("summary", ""))
            except Exception as ex:
                log(f"Video rewrite failed: {ex} - using the no-LLM builder")
                try:
                    vpost = sanitize(no_llm.build_video_post(vpick, LANG))
                    vprobs = []
                except Exception as ex2:
                    vpost, vprobs = None, [f"{ex} | {ex2}"[:160]]
"""
if old_v in src:
    src = src.replace(old_v, new_v, 1)
    changed.append("no-LLM fallback on the video branch")
else:
    print("  !! video anchor not found")

if "import no_llm" not in src:
    src = src.replace("import feedparser\nimport requests",
                      "import feedparser\nimport requests\n\n"
                      "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
                      "try:\n"
                      "    import no_llm\n"
                      "except Exception:\n"
                      "    no_llm = None", 1)
    changed.append("import no_llm")

if "LANG = " not in src:
    src = src.replace("ASSETS_DIR = os.path.join", 'LANG = "ar"\nASSETS_DIR = os.path.join', 1)
    changed.append("LANG constant")

bot.write_text(src, encoding="utf-8")
shutil.copy2(Path(__file__).parent / "no_llm.py", REPO / "scripts" / "no_llm.py")
print("[soq]")
for c in changed:
    print("  -", c)
