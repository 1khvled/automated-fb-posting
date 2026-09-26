#!/usr/bin/env python3
"""Refresh the bundled photo pile through Google Custom Search.

Usage: GOOGLE_CSE_KEY=... GOOGLE_CSE_CX=... python scripts/fetch_google.py
Downloads top editorial results per topic into ./pile_new/ for human
(eyeball) review before bundling into assets/topics/. Needs no FB token.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import post_bot  # noqa: E402

QUERIES = {
    "stocks": "new york stock exchange wall street",
    "fed": "federal reserve building washington",
    "bitcoin": "bitcoin cryptocurrency",
    "gold": "gold bars vault",
    "oil": "oil pumpjack field",
    "chips": "semiconductor chip factory",
    "whitehouse": "white house washington dc",
    "market": "stock market trading screens",
}

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pile_new")
os.makedirs(OUT, exist_ok=True)
for slug, q in QUERIES.items():
    data, ext = post_bot._google_photo(q)
    if data:
        fn = f"{slug}.{ext or 'jpg'}"
        with open(os.path.join(OUT, fn), "wb") as f:
            f.write(data)
        print("SAVED", fn, len(data))
    else:
        print("MISS", slug)
    time.sleep(2)
