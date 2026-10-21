import os, sys, base64, subprocess, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot\.env")
FF = r"C:\Users\Abdelli\AppData\Local\ms-playwright\ffmpeg-1013\ffmpeg-win64.exe"

print("=== ffmpeg encoders ===")
r = subprocess.run([FF, "-hide_banner", "-encoders"], capture_output=True, text=True)
for line in (r.stdout or "").splitlines():
    if any(k in line for k in ("libx264", "aac", "mpeg4", "libmp3", "h264")):
        print("   ", line.strip()[:110])
if not r.stdout:
    print("   stdout empty:", (r.stderr or "")[:300])

print("\n=== ffmpeg version ===")
r2 = subprocess.run([FF, "-hide_banner", "-version"], capture_output=True, text=True)
print("   ", (r2.stdout or r2.stderr or "").splitlines()[0][:120] if (r2.stdout or r2.stderr) else "no output")

print("\n=== gemini TTS ===")
keys = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
if os.getenv("GEMINI_API_KEY", "").strip():
    keys.append(os.getenv("GEMINI_API_KEY").strip())
keys = list(dict.fromkeys(keys))
text = "Breaking: Bitcoin just moved. Your portfolio, right now."
for model in ("gemini-2.5-flash-preview-tts", "gemini-3.8-flash-tts"):
    ok = False
    for k in keys[:3]:
        try:
            rr = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
                f":generateContent?key={k}",
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": text}]}],
                      "generationConfig": {
                          "responseModalities": ["AUDIO"],
                          "speechConfig": {"voiceConfig": {
                              "prebuiltVoiceConfig": {"voiceName": "Kore"}}},
                      }},
                timeout=90)
            d = rr.json() or {}
            if d.get("error"):
                print(f"   {model}: {str(d['error'])[:110]}")
                continue
            part = d["candidates"][0]["content"]["parts"][0]
            data = part.get("inlineData") or {}
            if data.get("data"):
                raw = base64.b64decode(data["data"])
                out = Path(f"_tts_{model}.{data.get('mimeType','audio/pcm').split('/')[-1]}")
                out.write_bytes(raw)
                print(f"   {model}: OK {len(raw)} bytes  mime={data.get('mimeType')}  -> {out.name}")
                ok = True
                break
        except Exception as e:  # noqa: BLE001
            print(f"   {model}: {type(e).__name__} {str(e)[:80]}")
    if not ok:
        print(f"   {model}: FAILED")
