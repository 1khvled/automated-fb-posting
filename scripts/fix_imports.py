"""Fix the broken scripts/ imports + add a concurrency guard.

Two bugs found 2026-10-21:

1. `import growth` and `import no_llm` FAILED SILENTLY. post_bot.py did
   sys.path.insert(0, dirname(__file__)) - the REPO ROOT - but both modules
   live in scripts/. The import raised, the bare `except` set the module to
   None, and the growth hook did nothing at all. Same for the no-LLM safety
   net: the page could still have gone dark.
   Fix: put scripts/ on the path.

2. Two runs overlapped (the 20-min cron plus a manual force run), both read
   the same dedup state before either had committed it, and both posted the
   SAME story 40 seconds apart. Fix: a workflow-level concurrency group so
   only one posting run exists at a time.
"""
import re
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
bot = REPO / "post_bot.py"
src = bot.read_text(encoding="utf-8")
changed = []

old = "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))"
new = ("sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),\n"
       "                                   \"scripts\"))")
n = src.count(old)
if n:
    src = src.replace(old, new)
    changed.append(f"sys.path now includes scripts/ ({n} place(s))")

# make the silent failure loud: a missing growth module must be visible
src = src.replace(
    "try:\n    import growth\nexcept Exception:  # growth engine is optional - never fail a post for it\n    growth = None",
    "try:\n    import growth\nexcept Exception as _gerr:  # optional, but never fail silently\n"
    "    growth = None\n    print(f\"WARNING: growth engine not loaded: {_gerr}\", flush=True)")
src = src.replace(
    "try:\n    import no_llm\nexcept Exception:\n    no_llm = None",
    "try:\n    import no_llm\nexcept Exception as _nerr:  # the safety net must be visible if it is missing\n"
    "    no_llm = None\n    print(f\"WARNING: no_llm safety net not loaded: {_nerr}\", flush=True)")
if "WARNING: growth engine not loaded" in src:
    changed.append("import failures are now loud, not silent")

bot.write_text(src, encoding="utf-8")

# ---- concurrency guard on the workflow
wf = REPO / ".github" / "workflows" / "fb-post.yml"
w = wf.read_text(encoding="utf-8")
if "concurrency:" not in w:
    guard = ("\n# Only one posting run at a time. Two overlapping runs read the same\n"
             "# dedup state before either had committed it, and posted the SAME story\n"
             "# 40 seconds apart. The group serialises the runs; the second one\n"
             "# waits for the first to finish and then finds the story already done.\n"
             "concurrency:\n"
             "  group: fb-post\n"
             "  cancel-in-progress: false\n")
    w = w.replace("jobs:\n", guard + "\njobs:\n", 1)
    wf.write_text(w, encoding="utf-8")
    changed.append("workflow concurrency guard added")

print(f"[{REPO.name}]")
for c in changed:
    print("  -", c)
if not changed:
    print("  (nothing to do)")
