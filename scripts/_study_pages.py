"""Study the pages that actually get engagement on this kind of content.

Target pages: WatcherGuru (the reference) and comparable finance / crypto /
AI news pages. For each one we pull, logged out:
  - the page's own cover + profile image
  - the recent feed posts: the image, the first line, the length, the hashtags
  - the visible engagement numbers
and we build a contact sheet of the post images so the visual style can be
compared side by side, plus a summary of the format.

Nothing here posts anything. It is reconnaissance.
"""
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

PAGES = [
    ("WatcherGuru", "https://www.facebook.com/WatcherGuru"),
    ("LiveSquawk", "https://www.facebook.com/LiveSquawk"),
    ("Investing.com", "https://www.facebook.com/Investingdotcom"),
    ("CoinMarketCap", "https://www.facebook.com/CoinMarketCap"),
    ("CryptoCompare", "https://www.facebook.com/CryptoCompare"),
    ("CoinDesk", "https://www.facebook.com/CoinDesk"),
]

OUT = Path(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot\_study")
OUT.mkdir(parents=True, exist_ok=True)
summary = {}


async def study(page, label, url):
    rec = {"url": url, "ok": False, "posts": [], "note": ""}
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        for _ in range(3):
            await page.mouse.wheel(0, 2200)
            await page.wait_for_timeout(1200)
        body = await page.inner_text("body")
        title = await page.title()
        rec["title"] = title
        if "Log In" in body and len(body) < 3000:
            rec["note"] = "login wall / little content"
        # collect the feed images
        imgs = await page.eval_on_selector_all(
            "img", "els => els.map(e => ({src: e.src, w: e.naturalWidth, h: e.naturalHeight,"
                   " alt: e.alt || ''}))")
        good = [i for i in imgs if i["w"] >= 300 and i["h"] >= 150]
        rec["images_found"] = len(good)
        # text of the page, to read the post copy
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        rec["sample_text"] = lines[:40]
        # engagement-ish numbers
        nums = re.findall(r"\b([\d.,]+[KMB]?)\s*(likes|comments|shares|reactions|views)\b",
                          body, re.I)
        rec["engagement_mentions"] = nums[:25]
        rec["ok"] = True
        # save the page screenshot
        await page.screenshot(path=str(OUT / f"{label}.png"), full_page=False)
    except Exception as e:  # noqa: BLE001
        rec["note"] = f"{type(e).__name__}: {str(e)[:120]}"
    return rec


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await b.new_context(locale="en-US", user_agent=UA,
                                   viewport={"width": 1400, "height": 1000})
        page = await ctx.new_page()
        for label, url in PAGES:
            print("=" * 66)
            print(label, url)
            rec = await study(page, label, url)
            summary[label] = rec
            print("  title  :", rec.get("title", "")[:70])
            print("  note   :", rec["note"] or "-")
            print("  images :", rec.get("images_found"))
            print("  engage :", rec.get("engagement_mentions", [])[:8])
            for l in rec.get("sample_text", [])[:12]:
                print("    |", l[:100])
        await ctx.close()
        await b.close()
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    print("\nsaved ->", OUT)


asyncio.run(main())
