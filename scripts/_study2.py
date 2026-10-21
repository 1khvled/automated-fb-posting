"""Competitive study, part 2: the public embeds.

Facebook's own Page Plugin renders a page timeline without a login:
    /plugins/page.php?href=<url>&tabs=timeline
and the old X syndication endpoint renders a public timeline:
    cdn.syndication.twimg.com/timeline/profile?screen_name=<name>

Those give the real post copy and the real post images.
"""
import asyncio
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

FB_PAGES = [
    ("Watcher.Guru", "https://www.facebook.com/WatcherGuru"),
    ("CoinMarketCap", "https://www.facebook.com/CoinMarketCap"),
    ("CryptoCompare", "https://www.facebook.com/CryptoCompare"),
    ("CoinDesk", "https://www.facebook.com/CoinDesk"),
]
X_ACCOUNTS = ["WatcherGuru", "DeItaone", "KobeissiLetter", "BitcoinMagazine"]

OUT = Path(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot\_study")
OUT.mkdir(parents=True, exist_ok=True)


async def fb_study(page, label, url):
    plug = ("https://www.facebook.com/plugins/page.php?href="
            + url.replace("&", "%26") + "&tabs=timeline&width=500&small_iframe=true")
    await page.goto(plug, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(6000)
    for _ in range(4):
        await page.mouse.wheel(0, 1800)
        await page.wait_for_timeout(1200)
    body = await page.inner_text("body")
    lines = [l.strip() for l in body.split("\n") if l.strip()]
    imgs = await page.eval_on_selector_all(
        "img", "els => els.map(e => ({src:e.src, w:e.naturalWidth, h:e.naturalHeight}))")
    good = [i for i in imgs if i["w"] >= 200 and i["h"] >= 120 and "scontent" in i["src"]]
    print("=" * 70)
    print("FB", label, f"({len(good)} post images, {len(lines)} lines)")
    for l in lines[:26]:
        print("   |", l[:110])
    return {"lines": lines, "images": good}


async def x_study(page, label, name):
    url = (f"https://cdn.syndication.twimg.com/timeline/profile?screen_name={name}"
           "&dnt=true&lang=en")
    try:
        r = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(3500)
        body = await page.inner_text("body")
    except Exception as e:  # noqa: BLE001
        print("X", label, "->", type(e).__name__, str(e)[:90])
        return {}
    items = re.findall(r'\{[^{}]*"text":"(.*?)"[^{}]*\}', body)
    if not items:
        try:
            data = json.loads(body)
            items = [t.get("text", "") for t in data.get("timeline", {}).get("entries", [])]
        except Exception:
            items = []
    print("=" * 70)
    print("X", label, f"({len(items)} posts)")
    for t in items[:12]:
        t = re.sub(r"<[^>]+>", "", t)
        t = t.encode().decode("unicode_escape", errors="ignore")
        print("   |", t[:150].replace("\n", " / "))
    return {"posts": items}


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await b.new_context(locale="en-US", user_agent=UA,
                                   viewport={"width": 1200, "height": 1000})
        page = await ctx.new_page()
        for label, url in FB_PAGES:
            try:
                await fb_study(page, label, url)
            except Exception as e:  # noqa: BLE001
                print("FB", label, "->", type(e).__name__, str(e)[:100])
        for nm in X_ACCOUNTS:
            try:
                await x_study(page, nm, nm)
            except Exception as e:  # noqa: BLE001
                print("X", nm, "->", type(e).__name__, str(e)[:100])
        await ctx.close()
        await b.close()


asyncio.run(main())
