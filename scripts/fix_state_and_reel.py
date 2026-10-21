"""Two fixes to both bots:

1. The reel should fire from ANY story, not only from a candidate that
   happens to carry a video file. A reel is generated - it does not need
   footage. So: if no video candidate clears the bar, the best text
   candidate becomes a reel instead of a static card. That is what makes
   "one reel a day" actually happen.

2. The save-state step pulled with --rebase BEFORE committing, which fails
   whenever the working tree is dirty ("cannot pull with rebase: You have
   unstaged changes"). The commit then lands on a stale base and the push
   can be rejected, which would lose the dedup state and let the bot
   repost a story. Fix: commit first, then pull with --autostash.
"""
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
bot = REPO / "post_bot.py"
wf = REPO / ".github" / "workflows" / "fb-post.yml"
src = bot.read_text(encoding="utf-8")
w = wf.read_text(encoding="utf-8")
changed = []

# ---- 1. the reel falls back to the best text candidate
old = """        if vids and vids[0]["score"] >= min_video_score:
            vpick = vids[0]
            log(f"VIDEO pick [{vpick['feed']}] score={vpick['score']}: "
                f"{vpick['title'][:100]}")
"""
new = """        # A reel is GENERATED - it does not need footage. So if no video
        # candidate clears the bar, the best text candidate becomes a reel
        # instead of a static card. That is what makes "one reel a day"
        # actually happen instead of depending on the luck of the feed.
        if not (vids and vids[0]["score"] >= min_video_score) and fresh:
            vids = [fresh[0]]
            log(f"REEL from the best story (no footage needed) "
                f"[{vids[0]['feed']}] score={vids[0]['score']}")
        if vids and vids[0]["score"] >= min_video_score:
            vpick = vids[0]
            log(f"VIDEO pick [{vpick['feed']}] score={vpick['score']}: "
                f"{vpick['title'][:100]}")
"""
if old in src:
    src = src.replace(old, new, 1)
    changed.append("the reel can be built from any story")
else:
    print("  !! video-pick anchor not found")

bot.write_text(src, encoding="utf-8")

# ---- 2. the save-state step
old_w = """          git pull --rebase || true
          git add posted.json || true
          git diff --staged --quiet || git commit -m "bot: update posted state [skip ci]" || true
          git pull --rebase || true
          git push || true"""
new_w = """          # Commit FIRST, then pull. The old order pulled with --rebase
          # before committing, which fails on a dirty tree and can lose the
          # dedup state - and a lost dedup state means reposted stories.
          git add -A || true
          git diff --staged --quiet || git commit -q -m "bot: update posted state [skip ci]" || true
          git pull --rebase --autostash || true
          git push || true"""
if old_w in w:
    w = w.replace(old_w, new_w, 1)
    wf.write_text(w, encoding="utf-8")
    changed.append("save-state: commit before pull, with autostash")
else:
    print("  !! save-state anchor not found")

print(f"[{REPO.name}]")
for c in changed:
    print("  -", c)
