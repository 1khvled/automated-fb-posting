"""
scripts/page_cleanup.py
-----------------------
Audit the Ethan Cole page feed and remove what makes it read as a bot: the
marketing posts, the visibly broken markdown posts, the engagement-bait posts,
and the page's own comments under its own posts.

The page must read like a person who follows markets, not like a product
brochure talking to itself. This script lists every post, classifies it, and -
only with an explicit flag - deletes.

USAGE
-----
    python scripts/page_cleanup.py                     # report only, no writes
    python scripts/page_cleanup.py --json out.json     # machine-readable report
    python scripts/page_cleanup.py --delete-product    # marketing posts
    python scripts/page_cleanup.py --delete-broken     # markdown defects
    python scripts/page_cleanup.py --delete-bait       # like/share begging
    python scripts/page_cleanup.py --delete-self-comments [--posts 100]
                                                       # the page's own comments

SAFETY
------
- Uses FB_PAGE_ACCESS_TOKEN only, and refuses to run unless /me is the page.
- Never touches the personal profile.
- Every destructive action needs its own flag; the default is a dry run.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GRAPH = "https://graph.facebook.com/v26.0"
HERE = Path(__file__).resolve().parent.parent

PRODUCT_MARKERS = [
    "edgetrading",
    "edge trading",
    "stockerai",
    "4-in-1",
    "$19/mo",
    "$39/mo",
    "$99/mo",
    "founding spot",
    "founding member",
    "dm me",
    "premium toolkit",
    "signal feed",
    "local quant terminal",
    "pine suite",
]

# Asking for likes/shares/reposts is both a credibility tell and a Partner
# Monetization violation. A page that begs reads like a page that is selling.
BAIT_MARKERS = [
    "like, repost",
    "like and share",
    "like & share",
    "share this",
    "share if",
    "follow for part",
    "follow for more",
    "follow for updates",
    "tag a friend",
    "comment below",
    "drop a comment",
    "type yes",
]


def load_env(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def get(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, timeout=30)
    data = r.json()
    if "error" in data:
        raise RuntimeError(json.dumps(data["error"], ensure_ascii=False)[:400])
    return data


def classify(msg: str) -> str:
    low = (msg or "").lower()
    if any(m in low for m in PRODUCT_MARKERS):
        return "product"
    if "**" in (msg or "") or "`" in (msg or ""):
        return "broken"
    if any(m in low for m in BAIT_MARKERS):
        return "bait"
    head = (msg or "").strip().upper()
    if head.startswith("JUST IN:") or head.startswith("BREAKING:"):
        return "template"
    return "story"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=str(HERE / ".env"))
    ap.add_argument("--json", default="")
    ap.add_argument("--delete-product", action="store_true")
    ap.add_argument("--delete-broken", action="store_true")
    ap.add_argument("--delete-bait", action="store_true")
    ap.add_argument("--delete-self-comments", action="store_true")
    ap.add_argument("--posts", type=int, default=100,
                    help="how many recent posts to scan for self-comments")
    ap.add_argument("--limit", type=int, default=0, help="stop after N posts")
    args = ap.parse_args()

    env = load_env(Path(args.env))
    token = env.get("FB_PAGE_ACCESS_TOKEN", "")
    page_id = env.get("FB_PAGE_ID", "")
    if not token or not page_id:
        print("FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN missing in", args.env)
        return 2

    me = get(f"{GRAPH}/me", {"fields": "id,name", "access_token": token})
    if str(me.get("id")) != str(page_id):
        print(f"REFUSING: token belongs to {me.get('id')} ({me.get('name')}), "
              f"not page {page_id}")
        return 3
    print(f"page: {me.get('name')} ({me.get('id')})")

    posts = []
    url = f"{GRAPH}/{page_id}/posts"
    params = {
        "fields": "id,created_time,message,permalink_url,shares,"
                  "reactions.summary(total_count),"
                  "comments.limit(50){id,message,from,created_time}",
        "limit": 100,
        "access_token": token,
    }
    while url:
        data = get(url, params)
        posts.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = {}
        if args.limit and len(posts) >= args.limit:
            posts = posts[:args.limit]
            break

    print(f"posts fetched: {len(posts)}\n")
    counts = {"product": 0, "broken": 0, "bait": 0, "template": 0, "story": 0}
    report = []
    self_comments = []
    for p in posts:
        msg = p.get("message", "") or ""
        kind = classify(msg)
        counts[kind] += 1
        comments = (p.get("comments") or {}).get("data") or []
        own = [c for c in comments
               if str((c.get("from") or {}).get("id")) == str(page_id)]
        self_comments.extend(own)
        report.append({
            "id": p["id"],
            "created_time": p.get("created_time"),
            "kind": kind,
            "reactions": p.get("reactions", {}).get("summary", {}).get("total_count", 0),
            "comments": len(comments),
            "self_comments": len(own),
            "message": msg,
            "permalink_url": p.get("permalink_url"),
        })

    print(f"product={counts['product']}  broken={counts['broken']}  "
          f"bait={counts['bait']}  template={counts['template']}  "
          f"story={counts['story']}")
    print(f"comments written by the page under its own posts: "
          f"{len(self_comments)}\n")
    for r in report:
        if r["kind"] in ("product", "broken", "bait"):
            first = r["message"].strip().split("\n")[0][:95]
            print(f"  {r['kind'].upper():8} {r['created_time'][:16]}  {first}")

    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print(f"\nreport written: {args.json}")

    if not any((args.delete_product, args.delete_broken, args.delete_bait,
                args.delete_self_comments)):
        print("\ndry run - nothing deleted. Flags: --delete-product, "
              "--delete-broken, --delete-bait, --delete-self-comments.")
        return 0

    kinds = []
    if args.delete_product:
        kinds.append("product")
    if args.delete_broken:
        kinds.append("broken")
    if args.delete_bait:
        kinds.append("bait")
    victims = [r for r in report if r["kind"] in kinds]
    ok = 0
    if victims:
        print(f"\ndeleting {len(victims)} posts ({', '.join(kinds)})...")
        for r in victims:
            resp = requests.delete(f"{GRAPH}/{r['id']}",
                                   params={"access_token": token},
                                   timeout=30).json()
            if resp.get("success"):
                ok += 1
                print(f"  deleted {r['id']}  {r['created_time'][:16]}")
            else:
                print(f"  FAILED  {r['id']}: {json.dumps(resp)[:200]}")
            time.sleep(0.2)
        print(f"\ndeleted {ok}/{len(victims)} posts")

    if args.delete_self_comments and self_comments:
        scope = self_comments[:args.posts]
        print(f"\ndeleting {len(scope)} self-comments "
              f"(of {len(self_comments)} found)...")
        cok = 0
        for c in scope:
            resp = requests.delete(f"{GRAPH}/{c['id']}",
                                   params={"access_token": token},
                                   timeout=30).json()
            if resp.get("success"):
                cok += 1
            else:
                print(f"  FAILED comment {c['id']}: {json.dumps(resp)[:160]}")
            time.sleep(0.2)
        print(f"deleted {cok}/{len(scope)} self-comments")
        return 0 if cok == len(scope) else 1

    return 0 if ok == len(victims) else 1


if __name__ == "__main__":
    raise SystemExit(main())
