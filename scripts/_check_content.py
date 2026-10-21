import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

REPOS = [Path(r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot"),
         Path(r"C:\Users\Abdelli\Documents\soq-alyoum-fb-bot")]

for repo in REPOS:
    sys.path.insert(0, str(repo / "scripts"))
    for m in ("product_source",):
        sys.modules.pop(m, None)
    import product_source as ps
    posts = ps.load_posts()
    print(f"\n{repo.name}: {len(posts)} posts available")
    ok = bad = 0
    for p in posts:
        probs = ps.check_post(p)
        if probs:
            bad += 1
            print(f"   FAIL {p.get('id')}: {probs}")
        else:
            ok += 1
            print(f"   ok   {p.get('id'):<12} [{p.get('_src',''):<20}] "
                  f"{p.get('title','')[:56]}")
    print(f"   -> {ok} ok, {bad} failed")
