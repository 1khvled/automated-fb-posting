#!/usr/bin/env python3
"""Fetch a curated set of Wikimedia Commons photos into assets/topics/.

Why this exists: the page's "neutral" fallback was three stock files
(stocks-nyse.jpg, market-hall.jpg, wallstreet.jpg) rotated by story hash, so
an oil story and a cocoa story got the same picture. Google Custom Search
is configured but its API is disabled on the project (HTTP 403
PERMISSION_DENIED), so every run silently fell through to those three.

Commons is keyless, licensed, and carries a real photograph of almost every
subject this page covers. This script pulls one good photo per subject,
resizes to 1600px wide, and writes it to assets/topics/ under a stable name
that TOPIC_PHOTOS references.

Idempotent: an existing file over 100 KB is left alone. Run with --force to
re-download everything.

    python scripts/fetch_commons_photos.py [--force] [--only fed,oil]
"""
import io
import os
import sys
import time

import requests
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOPICS = os.path.join(ROOT, "assets", "topics")
UA = {"User-Agent": "ethan-cole-fb-bot/1.0 (page photo library)"}

# (filename, Commons search query OR exact "File:..." title).
# Pinned titles: a free-text search ranks by the wrong thing (the largest
# result is usually a 1900s glass-plate scan or a panorama), so anything
# that has a known good file is pinned by name.
MANIFEST = [
    ("fed-eccles.jpg",
     "File:The Federal Reserve Building - Washington D.C..jpg"),
    ("ecb-frankfurt.jpg",
     "File:Seat of the European Central Bank and Frankfurt Skyline at dawn "
     "20150422 1.jpg"),
    ("treasury-building.jpg", "Treasury Building Washington DC"),
    ("capitol.jpg",
     "File:2018-03-26 \u2013 United States Capitol East Front, viewed from "
     "the east \u2013 Washington, D.C., United States.jpg"),
    ("whitehouse-north.jpg", "File:The White House South Portico.jpg"),
    ("nyse-floor.jpg", "New York Stock Exchange trading floor"),
    ("nyse-building.jpg", "New York Stock Exchange building"),
    ("wallstreet-bull.jpg",
     "File:Bowling Green td (2018-12-13) 06 - 26 Broadway, Charging Bull.jpg"),
    ("dollar-bills.jpg", "File:Benjamin-Franklin-U.S.-$100-bill.jpg"),
    ("euro-bills.jpg", "Euro banknotes"),
    ("gold-bars.jpg", "Gold bars bullion"),
    ("silver-coins.jpg", "Silver coins bullion"),
    ("oil-pumpjack.jpg", "Pumpjack oil well"),
    ("oil-refinery.jpg",
     "File:Refinery, Bayport Industrial Complex, Harris County, Texas.jpg"),
    ("oil-tanker.jpg", "Oil tanker ship"),
    ("bitcoin-atm.jpg", "Bitcoin ATM"),
    ("crypto-mining.jpg", "Bitcoin mining farm"),
    ("data-center.jpg", "File:Datacenter Server Racks (22370909788).jpg"),
    ("semiconductor-fab.jpg", "Semiconductor cleanroom"),
    ("shipping-port.jpg", "Container terminal port"),
    ("wheat-field.jpg", "Wheat field"),
    ("coffee-beans.jpg", "Coffee beans"),
    ("copper.jpg", "File:1 kilo copper bar 999 fineness from Degussa.jpg"),
    ("car-assembly.jpg",
     "File:001 Car factory assembly line - Opel factory in Gliwice, "
     "Poland.jpg"),
    ("solar-farm.jpg", "File:Solar array-2.jpg"),
    ("apartment-blocks.jpg", "Apartment buildings New York City"),
]

MIN_W = 1400
OUT_W = 1600


def looks_like_photo(im: Image.Image) -> bool:
    """Flat graphics, logos and screenshots have a few dozen colours; a
    photograph has thousands. Same test post_bot.py applies."""
    w, h = im.size
    if w < 800 or h < 450:
        return False
    try:
        small = im.convert("RGB").resize((80, 80), Image.BILINEAR)
        colours = len(set(small.quantize(colors=48).getdata()))
    except Exception:
        return False
    return colours >= 10


def search(query: str, limit: int = 10) -> list:
    """Candidates for a query. A "File:..." query is fetched by exact title,
    which is how the pinned entries avoid search ranking entirely."""
    exact = query.startswith("File:")
    for attempt in range(3):
        try:
            params = {"action": "query", "format": "json",
                      "prop": "imageinfo", "iiprop": "url|size",
                      "iiurlwidth": str(OUT_W)}
            if exact:
                params["titles"] = query
            else:
                params.update({"generator": "search",
                               "gsrsearch": f"filetype:bitmap {query}"[:250],
                               "gsrnamespace": "6",
                               "gsrlimit": str(limit)})
            r = requests.get("https://commons.wikimedia.org/w/api.php",
                             params=params, headers=UA, timeout=25)
            pages = (r.json().get("query") or {}).get("pages") or {}
            break
        except Exception as ex:
            print(f"  retry  {query!r}: {type(ex).__name__}")
            time.sleep(2 + attempt * 3)
    else:
        return []

    def area(pg):
        info = (pg.get("imageinfo") or [{}])[0]
        try:
            return int(info.get("width") or 0) * int(info.get("height") or 0)
        except Exception:
            return 0

    return sorted(pages.values(), key=area, reverse=True)


def fetch_one(name: str, query: str) -> bool:
    dest = os.path.join(TOPICS, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 100_000:
        print(f"  skip   {name} (exists)")
        return True
    for pg in search(query):
        info = (pg.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        title = pg.get("title") or ""
        if not url or url.lower().endswith(".svg"):
            continue
        try:
            if int(info.get("width") or 0) < MIN_W:
                continue
        except Exception:
            pass
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code != 200 or "image" not in r.headers.get(
                    "Content-Type", ""):
                continue
            im = Image.open(io.BytesIO(r.content))
            im.load()
        except Exception:
            continue
        if not looks_like_photo(im):
            continue
        im = im.convert("RGB")
        if im.size[0] > OUT_W:
            im = im.resize((OUT_W, int(im.size[1] * OUT_W / im.size[0])),
                           Image.LANCZOS)
        im.save(dest, "JPEG", quality=84, optimize=True)
        print(f"  ok     {name:26s} {im.size[0]}x{im.size[1]} "
              f"{os.path.getsize(dest)//1024}KB  <- {title[:60]}")
        return True
    print(f"  FAILED {name} (no usable result for {query!r})")
    return False


def main() -> int:
    force = "--force" in sys.argv
    only = ""
    for a in sys.argv:
        if a.startswith("--only"):
            only = a.split("=", 1)[-1] if "=" in a else ""
    if force:
        for name, _ in MANIFEST:
            p = os.path.join(TOPICS, name)
            if os.path.exists(p):
                os.remove(p)
    os.makedirs(TOPICS, exist_ok=True)
    ok = fail = 0
    for name, query in MANIFEST:
        if only and not any(name.startswith(o) for o in only.split(",")):
            continue
        if fetch_one(name, query):
            ok += 1
        else:
            fail += 1
        time.sleep(0.5)
    print(f"\n{ok} ok, {fail} failed -> {TOPICS}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
