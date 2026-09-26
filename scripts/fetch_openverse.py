#!/usr/bin/env python3
"""Refresh the bundled photo pile through Openverse (keyless, open-licensed).

Usage: python scripts/fetch_openverse.py
Downloads top commercial-use results per topic into ./pile_new/ for human
(eyeball) review before bundling into assets/topics/. Needs no keys.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import post_bot  # noqa: E402

QUERIES = {
    "stocks-ov": "new york stock exchange trading floor",
    "fed-ov": "federal reserve building",
    "bitcoin-ov": "bitcoin cryptocurrency",
    "gold-ov": "gold bars",
    "oil-ov": "oil pumpjack",
    "chips-ov": "semiconductor factory",
    "whitehouse-ov": "white house washington dc",
    "market-ov": "stock market chart screen",
}

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pile_new")
os.makedirs(OUT, exist_ok=True)
for slug, q in QUERIES.items():
    data, ext, creator = post_bot._openverse_photo(q)
    if data:
        fn = f"{slug}.{ext or 'jpg'}"
        with open(os.path.join(OUT, fn), "wb") as f:
            f.write(data)
        print("SAVED", fn, len(data), "by", creator)
    else:
        print("MISS", slug)
    time.sleep(2)
