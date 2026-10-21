import os, sys, json, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot\.env", override=False)
keys = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
if os.getenv("GEMINI_API_KEY", "").strip():
    keys.append(os.getenv("GEMINI_API_KEY").strip())
keys = list(dict.fromkeys(keys))
print("pool:", len(keys))

# what models does the API actually offer for this key?
r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                 params={"key": keys[0], "pageSize": 200}, timeout=40)
d = r.json() or {}
names = sorted({m["name"].replace("models/", "") for m in d.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])})
flash = [n for n in names if "flash" in n.lower()]
print(f"\n{len(names)} generateContent models; flash candidates:")
for n in flash:
    print("   ", n)

probe = "Reply with exactly: OK"
print("\ntesting each candidate across every key:")
best = None
for model in flash:
    ok = 0
    for k in keys:
        try:
            rr = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
                f":generateContent?key={k}",
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": probe}]}],
                      "generationConfig": {"maxOutputTokens": 40, "temperature": 0.2,
                                           "thinkingConfig": {"thinkingBudget": 0}}},
                timeout=45)
            dd = rr.json() or {}
            if not dd.get("error"):
                ok += 1
        except Exception:
            pass
    print(f"   {model:<44} {ok}/{len(keys)} keys")
    if ok >= max(2, len(keys) // 2) and (best is None or ok > best[1]):
        best = (model, ok)

print("\nBEST:", best)
if best:
    with open("_gemini_model.json", "w", encoding="utf-8") as f:
        json.dump({"model": best[0], "usable_keys": best[1], "pool": len(keys)}, f, indent=1)
