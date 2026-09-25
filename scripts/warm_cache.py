#!/usr/bin/env python3
"""Pre-warm .photo_cache: faces, entity logos, generic queries."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import post_bot  # noqa: E402

ok = fail = 0
for keys, wiki, _q in post_bot.PEOPLE_PHOTOS:
    cand = {"title": keys[0] + " makes market-moving announcement",
            "summary": keys[0], "keywords": [], "link": "https://x.com/x"}
    try:
        hit = bool(post_bot.people_photo(cand)[0])
    except Exception as ex:
        print("ERR ", wiki, str(ex)[:80])
        hit = False
    print(("OK  " if hit else "FAIL"), wiki)
    ok, fail = ok + hit, fail + (not hit)
    time.sleep(3)

for title, kw in [("OpenAI launches", ["openai"]),
                  ("Nvidia earnings", ["nvidia"]),
                  ("Bitcoin breaks out", ["bitcoin"]),
                  ("Tesla robotaxi", ["tesla"])]:
    cand = {"title": title, "summary": title, "keywords": kw,
            "link": "https://x.com/x"}
    try:
        hit = bool(post_bot.entity_logo(cand)[0])
    except Exception:
        hit = False
    print(("OK  " if hit else "FAIL"), title)
    ok, fail = ok + hit, fail + (not hit)
    time.sleep(2)

files = sorted(os.listdir(post_bot.PHOTO_CACHE_DIR))
total = sum(os.path.getsize(os.path.join(post_bot.PHOTO_CACHE_DIR, f))
            for f in files)
print(f"\n{len(files)} files, {total // 1024} KB | faces ok={ok} fail={fail}")
