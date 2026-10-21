import os, sys, json, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot\.env", override=False)
KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

r = requests.get("https://openrouter.ai/api/v1/models",
                 headers={"Authorization": f"Bearer {KEY}"}, timeout=30)
models = (r.json() or {}).get("data", [])
free = [m for m in models if m.get("id", "").endswith(":free")]
print(f"{len(models)} models, {len(free)} marked free\n")

PROBE = "Reply with exactly: OK"
cands = []
for m in free:
    mid = m["id"]
    if any(k in mid for k in ("gemma-3-27b-it", "gemma-3-12b-it", "llama-3.3-70b",
                              "llama-3.1-8b", "mistral-small", "qwen", "deepseek",
                              "gpt-oss", "phi-4", "nemotron")):
        cands.append(mid)
print("candidates:", cands[:14], "\n")

working = []
for mid in cands[:14]:
    try:
        rr = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY}",
                     "Content-Type": "application/json"},
            json={"model": mid, "max_tokens": 20,
                  "messages": [{"role": "user", "content": PROBE}]}, timeout=45)
        d = rr.json() or {}
        txt = ""
        try:
            txt = d["choices"][0]["message"]["content"]
        except Exception:
            pass
        if txt:
            print(f"  WORKING  {mid:<45} -> {txt[:40]!r}")
            working.append(mid)
        else:
            err = (d.get("error") or {}).get("message", "")[:70]
            print(f"  dead     {mid:<45} {err}")
    except Exception as e:  # noqa: BLE001
        print(f"  err      {mid:<45} {type(e).__name__}")

print("\nWORKING FREE MODELS:", working)
with open("_openrouter_working.json", "w", encoding="utf-8") as f:
    json.dump(working, f, indent=1)
