"""Wire the product posts into the posting bot.

Three changes:
  1. the product copy is used AS WRITTEN. It is hand-written, pre-checked and
     already in the house voice, so the LLM must not rewrite it and the QC
     (which compares against a source headline) must not run on it.
  2. the prepared image is used. The product screenshots are the point.
  3. the rotation is rate-limited: at most PRODUCT_PER_DAY product posts a
     day, inside a posting window, so the page stays a news page with a
     product in it - not an ad feed.
"""
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
bot = REPO / "post_bot.py"
src = bot.read_text(encoding="utf-8")
changed = []

# ---------------------------------------------------------------- 1. import
if "import product_source" not in src:
    src = src.replace(
        "try:\n    import growth",
        "try:\n    import product_source\n"
        "except Exception:\n"
        "    product_source = None\n"
        "try:\n    import growth", 1)
    changed.append("import product_source")

# ---------------------------------------------------------------- 2. the copy is used as written
old = """    fallback = False
    try:
        post = rewrite_with_llm(pick)"""
new = """    fallback = False
    if pick.get("is_product"):
        # A hand-written product post: already in the house voice, already
        # fact-checked, already has its image. The LLM must not touch it and
        # the QC (which checks the copy against a source headline) must not
        # run on it either.
        post = (pick.get("summary") or "").rstrip()
        _tags = " ".join(pick.get("keywords") or [])
        if _tags and _tags not in post:
            post = f"{post}\\n\\n{_tags}"
        fallback = True
        log(f"PRODUCT POST: {pick.get('product_id')}")
    else:
        try:
            post = rewrite_with_llm(pick)"""
if old in src:
    src = src.replace(old, new, 1)
    # re-indent the except branch that belonged to the old try
    src = src.replace(
        """    else:
        try:
            post = rewrite_with_llm(pick)
    except Exception as ex:
        # Every writer is down.""",
        """    else:
        try:
            post = rewrite_with_llm(pick)
        except Exception as ex:
            # Every writer is down.""", 1)
    changed.append("the product copy is published as written")
else:
    print("  !! rewrite anchor not found")

# ---------------------------------------------------------------- 3. the prepared image
old_img = """    post = add_source(post, outlet_for(pick["feed"]))
    img, ext, src = find_photo(pick)"""
new_img = """    if pick.get("is_product"):
        img = ext = src = None
        _lp = pick.get("local_photo") or ""
        if _lp and os.path.exists(_lp):
            try:
                with open(_lp, "rb") as _f:
                    img = _f.read()
                ext, src = "jpeg", "product"
            except Exception:
                img = None
        if not img:
            log("product post image missing - skipping this candidate")
            return 0
    else:
        post = add_source(post, outlet_for(pick["feed"]))
        img, ext, src = find_photo(pick)"""
if old_img in src:
    src = src.replace(old_img, new_img, 1)
    changed.append("the prepared product image is used")
else:
    print("  !! image anchor not found")

# the credit line is for stock photos, not for our own product screenshots
src = src.replace(
    '    post = add_credit(post, credit_for(pick["feed"], src))\n'
    '    log(f"Visual: {src} | credit added")',
    '    if not pick.get("is_product"):\n'
    '        post = add_credit(post, credit_for(pick["feed"], src))\n'
    '    log(f"Visual: {src} | credit added")', 1)

# ---------------------------------------------------------------- 4. the rotation
old_fresh = '    log(f"{len(fresh)} fresh (not yet posted)")'
new_fresh = '''    log(f"{len(fresh)} fresh (not yet posted)")
    # PRODUCT ROTATION. The pages are the top of the funnel for a paid
    # membership, so the product goes out on a schedule - at most
    # PRODUCT_PER_DAY a day, inside PRODUCT_WINDOW_UTC, and never more than
    # one in a row, so the page stays a page and not an ad feed.
    try:
        import product_source as _ps
        _per_day = int(os.getenv("PRODUCT_PER_DAY", "1"))
        _win = os.getenv("PRODUCT_WINDOW_UTC", "9-21")
        _lo, _hi = (int(x) for x in _win.split("-"))
        _now_h = datetime.now(timezone.utc).hour
        _count = _ps.daily_count(state)
        _last_was_product = bool(state.get("history") and
                                 state["history"][-1].get("is_product"))
        if (_lo <= _now_h < _hi and _count < _per_day and not _last_was_product
                and _ps.load_posts()):
            _pcands = _ps.candidates(state)
            if _pcands:
                fresh.insert(0, _pcands[0])
                log(f"PRODUCT ROTATION: injecting '{_pcands[0].get('product_id')}' "
                    f"({_count}/{_per_day} today, hour {_now_h} in {_win} UTC)")
        else:
            log(f"product rotation skipped: {_count}/{_per_day} today, "
                f"hour {_now_h} not in {_win} UTC, "
                f"last was product={_last_was_product}")
    except Exception as _pe:
        log(f"product rotation unavailable: {_pe}")'''
if old_fresh in src:
    src = src.replace(old_fresh, new_fresh, 1)
    changed.append("the product rotation is rate-limited and windowed")
else:
    print("  !! fresh anchor not found")

# record that the post was a product post, and count it
src = src.replace(
    """    hist.append({
        "fb_id": post_id,
        "topics": sorted({KW_TO_TOPIC[k] for k in pick.get("keywords", [])
                          if k in KW_TO_TOPIC}),""",
    """    hist.append({
        "fb_id": post_id,
        "is_product": bool(pick.get("is_product")),
        "product_id": pick.get("product_id"),
        "topics": sorted({KW_TO_TOPIC[k] for k in pick.get("keywords", [])
                          if k in KW_TO_TOPIC}),""", 1)
src = src.replace(
    "    save_state(state_file, state)\n    return 0\n\n\nif __name__ == \"__main__\":",
    "    try:\n"
    "        import product_source as _ps2\n"
    "        if pick.get(\"is_product\"):\n"
    "            _ps2.mark_used(state, pick.get(\"product_id\", \"\"))\n"
    "    except Exception:\n"
    "        pass\n"
    "    save_state(state_file, state)\n    return 0\n\n\nif __name__ == \"__main__\":", 1)

# the product candidates must not be caught by the news-only filters
src = src.replace(
    '    fresh = [c for c in fresh if not _too_similar(c["title"])]',
    '    fresh = [c for c in fresh\n'
    '             if c.get("is_product") or not _too_similar(c["title"])]', 1)

bot.write_text(src, encoding="utf-8")
print(f"[{REPO.name}]")
for c in changed:
    print("  -", c)
if not changed:
    print("  (nothing to do)")
