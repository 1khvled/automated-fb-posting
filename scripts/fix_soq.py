"""Repair the soq repo's writer-fallback block and add the product branch.

The soq repo's block is the ORIGINAL shape (a plain try/except at 4 spaces);
an over-eager re-indent moved it. Repair it, and add the product branch with
the soq-specific call signature: rewrite_with_llm(pick, shape).
"""
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
bot = REPO / "post_bot.py"
lines = bot.read_text(encoding="utf-8").split("\n")

# ---- 1. find the block
start = None
for i, l in enumerate(lines):
    if l.strip() == "except Exception as ex:" and i + 1 < len(lines) and \
            "Every writer is down" in lines[i + 1]:
        start = i
        break
if start is None:
    print("  block not found")
    raise SystemExit(1)

end = None
for j in range(start, len(lines)):
    if lines[j].strip().startswith("post = sanitize(post)"):
        end = j
        break
blk_end = end
while blk_end > start and not lines[blk_end - 1].strip():
    blk_end -= 1

block = lines[start:blk_end]
# de-indent everything by 4 so the except lines up with its try
block = [(l[4:] if l.startswith("    ") and l.strip() else l) for l in block]
lines[start:blk_end] = block
print(f"  de-indented {len(block)} lines")

# ---- 2. the product branch (soq calls rewrite_with_llm(pick, shape))
src = "\n".join(lines)
old = """    fallback = False
    try:
        post = rewrite_with_llm(pick, shape)
    except Exception as ex:"""
new = """    fallback = False
    if pick.get("is_product"):
        # A hand-written product post: already in the house voice, already
        # fact-checked, already has its image. The LLM must not touch it and
        # the QC (which compares against a source headline) must not run on it.
        post = (pick.get("summary") or "").rstrip()
        _tags = " ".join(pick.get("keywords") or [])
        if _tags and _tags not in post:
            post = f"{post}\\n\\n{_tags}"
        fallback = True
        log(f"PRODUCT POST: {pick.get('product_id')}")
    else:
        try:
            post = rewrite_with_llm(pick, shape)
        except Exception as ex:"""
if old in src:
    # the except body must be re-indented by 4 to sit under the new try
    head, _, tail = src.partition(old)
    rest = tail.split("\n")
    out = []
    for l in rest:
        if l.strip() and not l.strip().startswith("post = sanitize(post)"):
            out.append(("    " + l) if l.strip() else l)
        else:
            out.append(l)
            if l.strip().startswith("post = sanitize(post)"):
                break
    src = head + new + "\n" + "\n".join(out)
    bot.write_text(src, encoding="utf-8")
    print("  product branch added")
else:
    bot.write_text(src, encoding="utf-8")
    print("  (product branch anchor not found)")
