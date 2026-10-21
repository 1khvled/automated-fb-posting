"""Re-indent the writer-fallback block after it was moved under an `else:`.

The block used to be:

    try:
        post = rewrite_with_llm(pick)
    except Exception as ex:
        log(...)
        try:
            ...

and is now:

    else:
        try:
            post = rewrite_with_llm(pick)
        except Exception as ex:
            log(...)
            try:
                ...

so the body of the except needs four more spaces. This fixes the
indentation in place, once, idempotently.
"""
import re
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
bot = REPO / "post_bot.py"
lines = bot.read_text(encoding="utf-8").split("\n")

start = None
for i, l in enumerate(lines):
    if l.strip() == "except Exception as ex:" and i + 1 < len(lines) and \
            "Every writer is down" in lines[i + 1]:
        start = i
        break
if start is None:
    print("  (block not found - already fine)")
    raise SystemExit(0)

# the block ends at the last line before the blank line + "post = sanitize("
end = None
for j in range(start, len(lines)):
    if lines[j].strip().startswith("post = sanitize(post)"):
        end = j
        break
if end is None:
    print("  !! end not found")
    raise SystemExit(1)

# strip trailing blank lines inside the block
blk_end = end
while blk_end > start and not lines[blk_end - 1].strip():
    blk_end -= 1

block = lines[start:blk_end]
fixed = []
for l in block:
    if l.strip():
        fixed.append("    " + l)
    else:
        fixed.append(l)
lines[start:blk_end] = fixed
bot.write_text("\n".join(lines), encoding="utf-8")
print(f"[{REPO.name}] re-indented {len(block)} lines of the writer-fallback block")
