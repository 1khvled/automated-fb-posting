"""Make the bots publish GENERATED reels instead of downloaded footage.

The pages were posting mp4s downloaded from X and Telegram - other people's
footage. For a page that has to look like a brand (and that Facebook's own
originality policy can de-monetise), redistributed footage is the wrong
material. The reel is generated: three designed scenes on a slow Ken Burns
pan, a Gemini TTS voiceover in the page's own language, and burned-in
subtitles. The downloaded video stays as a fallback.
"""
import shutil
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
BRAND = sys.argv[2] if len(sys.argv) > 2 else "ethan"
bot = REPO / "post_bot.py"
src = bot.read_text(encoding="utf-8")
changed = []

# ---- import
if "import reel" not in src:
    src = src.replace(
        "try:\n    import card_design",
        "try:\n    import reel\n"
        "except Exception as _rerr:\n"
        "    reel = None\n"
        "    print(f\"WARNING: reel not loaded: {_rerr}\", flush=True)\n"
        "try:\n    import card_design", 1)
    changed.append("import reel")

# ---- build a reel instead of downloading a video
old = """                vid = _download_video(vpick["video_url"])
"""
new = """                vid = None
                try:
                    if reel is None:
                        raise RuntimeError("reel module not available")
                    vid = reel.build_reel(
                        vpost, vpick.get("keywords", []),
                        outlet_for(vpick["feed"]),
                        os.getenv("CARD_BRAND", "%s"),
                        LANG,
                        llm=lambda s, u: gen_gemini("gemini-3.5-flash", s, u))
                    if vid:
                        log("Generated reel built (original content)")
                except Exception as _rex:
                    log(f"reel build failed: {_rex}")
                if not vid:
                    vid = _download_video(vpick["video_url"])
                    if vid:
                        log("Falling back to the downloaded footage")
""" % BRAND
if old in src:
    src = src.replace(old, new, 1)
    changed.append("generated reel replaces downloaded footage")
else:
    print("  !! video-download anchor not found")

bot.write_text(src, encoding="utf-8")

# ---- requirements: a full ffmpeg
req = REPO / "requirements.txt"
r = req.read_text(encoding="utf-8")
if "imageio-ffmpeg" not in r:
    r = r.rstrip("\n") + "\nimageio-ffmpeg>=0.5\n"
    req.write_text(r, encoding="utf-8")
    changed.append("requirements: imageio-ffmpeg")

# ---- the reel module itself
shutil.copy2(Path(__file__).parent / "reel.py", REPO / "scripts" / "reel.py")
shutil.copy2(Path(__file__).parent / "reel.py",
             Path(r"C:\Users\Abdelli\Documents\soq-alyoum-fb-bot\scripts\reel.py"))
changed.append("scripts/reel.py copied")

print(f"[{REPO.name}]")
for c in changed:
    print("  -", c)
if not changed:
    print("  (nothing to do)")
