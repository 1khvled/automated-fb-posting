"""Wire the growth engine into a post_bot.py. Idempotent and reversible.

Patches:
  1. import growth
  2. after a post goes live  -> growth.after_publish (seed comment + share kit)
  3. on every run            -> growth.reply_backlog (answer comments)

Usage: python wire_growth.py <repo_dir> [--lang en|ar]
"""
import re
import shutil
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
LANG = "ar" if "--lang" in sys.argv and sys.argv[sys.argv.index("--lang") + 1] == "ar" else "en"
bot = REPO / "post_bot.py"
src = bot.read_text(encoding="utf-8")
backup = bot.with_suffix(".py.bak")
if not backup.exists():
    shutil.copy2(bot, backup)

if "import growth" in src:
    print("already wired")
    raise SystemExit(0)

# ---- 1. import
src = src.replace(
    "import feedparser\nimport requests",
    "import feedparser\nimport requests\n\n"
    "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
    "try:\n"
    "    import growth\n"
    "except Exception:  # growth engine is optional - never fail a post for it\n"
    "    growth = None",
    1)

# ---- 2. after publish
anchor = "\n        notify_post_live(post_id, post)\n"
add = anchor + (
    "        try:\n"
    "            if growth:\n"
    "                g = growth.after_publish(\n"
    "                    post_id, post, pick[\"title\"],\n"
    "                    pick.get(\"keywords\", []),\n"
    "                    llm=lambda s, u: gen_gemini(\"gemini-2.5-flash\", s, u),\n"
    f"                    lang=\"{LANG}\")\n"
    "                log(f\"growth: seed comment \"\n"
    "                    f\"{g.get('seed_comment_id')}, \"\n"
    "                    f\"share kit sent={g.get('share_sent')}\")\n"
    "        except Exception as _gx:\n"
    "            log(f\"growth hook skipped: {_gx}\")\n"
)
if anchor not in src:
    print("PUBLISH ANCHOR NOT FOUND")
    raise SystemExit(1)
src = src.replace(anchor, add, 1)

# also the video-publish branch
vanchor = "                        notify_post_live(post_id, vpost)\n"
vadd = vanchor + (
    "                        try:\n"
    "                            if growth:\n"
    "                                g = growth.after_publish(\n"
    "                                    post_id, vpost, vpick[\"title\"],\n"
    "                                    vpick.get(\"keywords\", []),\n"
    "                                    llm=lambda s, u: gen_gemini(\"gemini-2.5-flash\", s, u),\n"
    f"                                    lang=\"{LANG}\")\n"
    "                                log(f\"growth: seed comment \"\n"
    "                                    f\"{g.get('seed_comment_id')}, \"\n"
    "                                    f\"share kit sent={g.get('share_sent')}\")\n"
    "                        except Exception as _gx:\n"
    "                            log(f\"growth hook skipped: {_gx}\")\n"
)
if vanchor in src:
    src = src.replace(vanchor, vadd, 1)

# ---- 3. reply backlog on every run (after the state is loaded)
ranchor = "    _TUNER.update(tune_from_engagement(state))\n"
radd = ranchor + (
    "    try:\n"
    "        if growth:\n"
    "            _rn = growth.reply_backlog(\n"
    "                state,\n"
    "                llm=lambda s, u: gen_gemini(\"gemini-2.5-flash\", s, u),\n"
    f"                lang=\"{LANG}\")\n"
    "            if _rn:\n"
    "                log(f\"growth: replied to {_rn} comment(s)\")\n"
    "            save_state(state_file, state)\n"
    "    except Exception as _gx:\n"
    "        log(f\"comment replies skipped: {_gx}\")\n"
)
if ranchor not in src:
    print("REPLY ANCHOR NOT FOUND")
    raise SystemExit(1)
src = src.replace(ranchor, radd, 1)

bot.write_text(src, encoding="utf-8")
print(f"wired {bot} (lang={LANG})  backup: {backup.name}")
