import os, sys, importlib.util, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv

REPO = Path(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot")
load_dotenv(REPO / ".env", override=False)
spec = importlib.util.spec_from_file_location("bot", REPO / "post_bot.py")
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

cands = bot.fetch_x_candidates(1440)
print(f"{len(cands)} X candidates in the last 24h\n")
by_feed = {}
for c in cands:
    by_feed.setdefault(c.get("feed", "?"), []).append(c)

print("=" * 78)
print("per source")
for f, cs in sorted(by_feed.items(), key=lambda kv: -len(kv[1])):
    print(f"  {f:<34} {len(cs):>3} candidates")

OUT = REPO / "_study"
OUT.mkdir(exist_ok=True)
kept = []
for c in cands:
    if "Watcher" in (c.get("feed") or "") or "Guru" in (c.get("feed") or ""):
        kept.append(c)

print("\n" + "=" * 78)
print(f"WatcherGuru raw posts ({len(kept)}) - the reference")
for c in kept[:8]:
    print("-" * 74)
    print("feed   :", c.get("feed"))
    print("title  :", (c.get("title") or "")[:160])
    print("summary:", (c.get("summary") or "")[:200])
    print("photo  :", (c.get("photo_url") or "(none)")[:120])
    print("video  :", (c.get("video_url") or "(none)")[:100])
    print("score  :", c.get("score"), "| age", c.get("age_min"), "m | mode", c.get("mode"))
    print("keys   :", sorted(c.keys()))

# how many candidates overall carry a real photo?
with_photo = [c for c in cands if c.get("photo_url")]
with_video = [c for c in cands if c.get("video_url")]
print("\n" + "=" * 78)
print(f"candidates with a photo: {len(with_photo)}/{len(cands)}")
print(f"candidates with a video: {len(with_video)}/{len(cands)}")
print("\nphoto sources:")
srcs = {}
for c in with_photo:
    u = c["photo_url"]
    k = "pbs.twimg" if "twimg" in u else ("video" if "video" in u else
                                         ("fbcdn" if "fbcdn" in u else u[:40]))
    srcs[k] = srcs.get(k, 0) + 1
for k, v in sorted(srcs.items(), key=lambda kv: -kv[1]):
    print(f"   {k:<24} {v}")
