"""Capture REAL screenshots of the StockerAI terminal.

These are the product images for the pitch: the landing page and the Facebook
posts need to show the actual product, not a mockup. The terminal runs
locally on :5001, so we boot it, drive it with a real browser, and shoot the
pages that matter.

Output: C:\\Users\\Abdelli\\Documents\\eight-dollar\\assets\\terminal\\
"""
import asyncio
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

TERMINAL = Path(r"D:\Projects\STOCK_TERMINAL_ALONE")
OUT = Path(r"C:\Users\Abdelli\Documents\eight-dollar\assets\terminal")
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:5001"

SHOTS = [
    ("01_hub", "/", 1440, 900),
    ("02_screener", "/api/stocks", 1440, 900),
    ("03_portfolio", "/portfolio", 1440, 900),
    ("04_market_feed", "/market-feed", 1440, 900),
    ("05_intel", "/news-impact", 1440, 900),
    ("06_committee", "/committee", 1440, 900),
    ("07_red_flags", "/red-flags", 1440, 900),
    ("08_scenario", "/scenario-lab", 1440, 900),
    ("09_watchlist", "/watchlist", 1440, 900),
]


async def shoot():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width": 1440, "height": 900},
                                  device_scale_factor=2)
        page = await ctx.new_page()
        for name, path, w, h in SHOTS:
            try:
                await page.set_viewport_size({"width": w, "height": h})
                r = await page.goto(BASE + path, wait_until="domcontentloaded",
                                    timeout=45000)
                await page.wait_for_timeout(3500)
                # let the live quote polls and charts settle
                await page.wait_for_timeout(2500)
                fn = OUT / f"{name}.png"
                await page.screenshot(path=str(fn))
                size = fn.stat().st_size
                print(f"  {name:<18} {path:<18} HTTP {r.status if r else '?'}  "
                      f"{size:>8,}B")
            except Exception as e:  # noqa: BLE001
                print(f"  {name:<18} FAILED {type(e).__name__}: {str(e)[:70]}")
        await ctx.close()
        await b.close()


asyncio.run(shoot())
print("done ->", OUT)
