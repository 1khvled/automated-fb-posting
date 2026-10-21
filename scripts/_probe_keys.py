import os, sys, importlib.util
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv

REPO = Path(sys.argv[1])
load_dotenv(REPO / ".env", override=False)
spec = importlib.util.spec_from_file_location("bot", REPO / "post_bot.py")
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

keys = bot._gemini_keys()
print(f"{REPO.name}: gemini pool = {len(keys)}")
if not keys:
    raise SystemExit(0)

probe = "Reply with exactly: OK"
ok = 0
for i, k in enumerate(keys):
    try:
        import requests
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash:generateContent?key={k}",
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": probe}]}],
                  "generationConfig": {"maxOutputTokens": 40, "temperature": 0.2,
                                       "thinkingConfig": {"thinkingBudget": 0}}},
            timeout=60)
        d = r.json()
        if d.get("error"):
            print(f"  key {i} ...{k[-6:]}: {str(d['error'])[:90]}")
            continue
        txt = d["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"  key {i} ...{k[-6:]}: OK -> {txt[:30]!r}")
        ok += 1
    except Exception as e:  # noqa: BLE001
        print(f"  key {i} ...{k[-6:]}: {type(e).__name__} {str(e)[:70]}")
print(f"\n{ok}/{len(keys)} gemini keys usable")
