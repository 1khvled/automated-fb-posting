import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath("post_bot.py")), "scripts"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(".env")

import reel
import card_design as cd

POST_EN = """JUST IN: JPMorgan just DOUBLED its SpaceX ($SPCX) price target to $500.

Old target: $240
New target: $500
Increase: +108%"""

POST_AR = """مايكل سيلور لشركة الخدمات المالية Charles Schwab: سوق الكريبتو الصاعد بدأ رسميا!

ارتد BTC من متوسط 200 أسبوع وزاد حوالي 20,000 دولار فوق السعر ده."""

LLM = None
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location("ecbot", "post_bot.py")
    bot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bot)
    LLM = lambda s, u: bot.gen_gemini("gemini-3.5-flash", s, u)
except Exception as e:
    print("llm unavailable:", e)

for tag, post, brand, lang in (("EN", POST_EN, "ethan", "en"),
                               ("AR", POST_AR, "market", "ar")):
    t0 = time.time()
    out = Path(f"_reel_{tag}.mp4")
    data = reel.build_reel(post, ["stocks", "crypto"], "Reuters", brand, lang, LLM)
    if data:
        out.write_bytes(data)
        print(f"{tag}: {len(data):,} bytes -> {out.name}  ({time.time()-t0:.1f}s)")
    else:
        print(f"{tag}: FAILED")
