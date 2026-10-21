# Ethan Cole FB auto-poster

Runs every 20 min via GitHub Actions. 1 post max per run, only if fresh
finance/AI news passes the filter. Dedup via `posted.json`.

## October 2026 incident (read this before changing anything)

Two separate problems, both fixed or diagnosed below.

**1. The Page token is dead, and it cannot be fixed from the server.**
The self-heal log says it exactly:

```
refresh: page_not_managed - the Facebook account behind FB_USER_TOKEN
manages 1 other page(s) (816138634925735) but not our page
```

A Page token inherits the life of the user token that minted it. The profile
behind `FB_USER_TOKEN` no longer administers the Ethan Cole Page, so every
publish returns error 190 (*"This Page access token belongs to a Page that is
not accessible"*) and re-minting from the same user token just reproduces the
same dead token. **The fix is one interactive login on the Facebook profile
that actually owns the Page.** `scripts/reseed_token.py` makes that a
two-minute job: it exchanges the token, lists the Pages it can manage, mints
and stores the Page token, re-enables this workflow, and tells you plainly
which profile to log into when the Page is missing.

**2. The page was posting 15 times a day into 8 followers and getting zero
engagement.** `MIN_POSTS_PER_DAY` was 14. It is not a floor, it is a *target*:
behind pace the bot lowers its publish bar, and after 21:00 UTC it shrinks the
cooldown so the day hits its minimum. Result: 15 mediocre posts a day, every
one of them diluting the reach of the others. The README's own monetisation
goal says 4–11 posts/day is the consistency band, and the audience is 8
people, so the floor is now **4**. The cron went from every 10 min to every
20 min (144 runs/day to produce 15 posts was mostly wasted runner time).
Raise both only when the audience does.

**3. The tuner was blind.** `tune_from_engagement` had never learned anything
because there was never any engagement to learn from, and `metrics.jsonl` had
been returning `null` for impressions/engagement because the token was dead
too. Both resolve once the token is re-seeded.

**4. `GROUP_SHARE_TARGETS` is not set.** It is referenced by this workflow and
by `notify_post_live`, but the secret does not exist, so the group-share
distribution path has never run. For a page with a small audience this is the
reach mechanism that matters. Set it to a comma-separated list of group ids.

## 1. Facebook token (you do this once, ~10 min)

1. Go to https://developers.facebook.com → My Apps → Create App (type: Business, or Other → Business).
2. Add product: **Facebook Login** (needed for Graph Explorer auth).
3. Graph API Explorer (https://developers.facebook.com/tools/explorer):
   - Select your App → Get User Access Token → tick:
     `pages_show_list`, `pages_manage_posts`, `pages_manage_read_engagement`, `pages_manage_metadata`
   - Submit → copy user token.
4. Get Page token: `GET /me/accounts` → find your Page → copy its `access_token` + `id`.
5. Extend to long-lived (~60 days): in Graph Explorer do
   `GET /oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=SHORT_TOKEN`
   Use the returned token as your Page token (Page tokens inherit longevity).
6. Test post: `POST /{page-id}/feed` with param `message=hello test` using the Page token.
   Check your Page, then delete the test post.

Note: app can stay in Dev mode if you are admin of both App + Page.
Token expires ~60 days → repeat step 5 and update the secret.

## 2. GitHub setup (runner option A — recommended)

1. Create a **new private repo** (e.g. `automated-fb-posting`), upload the contents of this folder.
2. Repo → Settings → Secrets and variables → Actions → New repository secret:
   - `FB_PAGE_ID` = `1264009986803820` (Ethan Cole — already filled in for you)
   - `FB_PAGE_ACCESS_TOKEN` = long-lived Page token
   - `GEMINI_API_KEYS` = your 5 Google AI Studio keys, comma-separated, no spaces
     (the bot rotates the starting key every 20-min run and fails over on 429s,
     so all keys share the load evenly across the day)
   - `OPENROUTER_API_KEY` (backup writer, only used if all Gemini keys fail)
3. Actions tab → enable workflows → use **Run workflow** with dry_run=1 first to test
   (generates a post, skips Facebook publish — check the logs).
4. Done. Cron `*/20 * * * *` runs automatically. Max 1 post per run.

## 2b. Vercel setup (runner option B — pick ONE runner, never both)

Running on both GitHub Actions AND Vercel at once will double-post.
Pick one. GitHub Actions is recommended (dedup state persists via git).

1. Push the same repo to GitHub, then Vercel → Add New → Project → Import.
2. Vercel → Project → Settings → Environment Variables → **Import .env**:
   upload your filled local `.env` file (`ethan-cole-fb-bot/.env`, never committed
   to git). Variables needed: `FB_PAGE_ID`, `FB_PAGE_ACCESS_TOKEN`,
   `GEMINI_API_KEYS`, `OPENROUTER_API_KEY`, plus optional `CRON_SECRET`
   (if set, `/api/cron` requires `Authorization: Bearer <secret>`).
3. Deploy. `vercel.json` already schedules `/api/cron` every 20 min
   (`api/cron.py` runs `post_bot.main()`, state in `/tmp/posted.json`).
4. Nothing runs on your computer — your PC is only for chatting here and
   improving the algo. All posting happens in the cloud.

## 3. Undying token + auto-refresh (do once, ~15 min)

Why tokens die: a Page token inherits the life of the user token that
minted it. Ours came from a short-lived user token (hours). Minted from a
**long-lived** (60-day) user token, the Page token gets **no expiry date**
(Meta docs) — plus a monthly workflow re-mints the chain automatically.

1. Graph Explorer → your App → Get **User** Access Token → tick
   `pages_show_list`, `pages_manage_posts`, `pages_read_engagement` → copy.
2. Extend it (paste in browser, fill APP_ID/APP_SECRET/TOKEN):
   `https://graph.facebook.com/v26.0/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=TOKEN`
   → this is your 60-day `FB_USER_TOKEN`.
3. Get the undying Page token (paste with USER_TOKEN + PAGE_ID):
   `https://graph.facebook.com/v26.0/me/accounts?access_token=USER_TOKEN`
   → find your Page → its `access_token` never expires → set as
   `FB_PAGE_ACCESS_TOKEN` secret (and in local `.env`).
4. Repo Secrets → add `FB_APP_ID`, `FB_APP_SECRET`, `FB_USER_TOKEN`.
5. GitHub → Settings → Developer settings → Personal access tokens →
   **classic** token with `repo` scope → add as repo secret `GH_PAT`.
6. Done. `refresh-token.yml` runs monthly: while the user token is alive it
   mints a fresh 60-day user token + fresh undying Page token and stores
   both back. Self-sustaining — only a fully dead user token needs one
   more manual login (the workflow log will say so).

## 4. Local test

```
python -m pip install -r requirements.txt
set DRY_RUN=1
python -c "import post_bot; print(len(post_bot.fetch_candidates(70))))"
```

Full dry run needs an LLM key:
```
set GEMINI_API_KEYS=key1,key2
set DRY_RUN=1
python post_bot.py
```

## 5. Tuning

- `RSS_FEEDS` / `TOPIC_WEIGHTS` / `EXCLUDE` / `X_HANDLES` in `post_bot.py` control what qualifies.
- `MAX_AGE_MINUTES` (default 70) = how fresh news must be. Cron is 20 min, 70 gives overlap.
- Voice rules live in `SYSTEM_PROMPT` — mirrors the Ethan Cole skill (verify → rewrite → context → hook → QC).

## 6. Monetization roadmap (365-day goal)

Facebook Content Monetization is **invite-only** (no application). Realistic bar:
~10K followers, strong 28-day views/watch time, 5+ videos, original content,
clean policy record. Stars unlock earlier (~500 followers).

What the bot already does for this: 4–11 posts/day consistency, daily reel
(watch time), 60% rage mix (reach), QC bans on markdown + engagement bait
(asking for likes/shares/comments kills eligibility — never do it).

What you must do (can't be automated):
1. **Keep the token alive.** Page tokens from short-lived logins die in hours;
   do the one-time undying setup in section 3, then the monthly workflow
   sustains itself. If the bot ever logs `FB token invalid/expired`, re-seed
   per section 3. No token = no posts = no growth.
2. **Interest form:** FB mobile app → Professional Dashboard → Monetization →
   Content Monetization → submit the interest form.
3. **Originality:** re-uploaded viral videos risk "unoriginal content" flags.
   Original clips/charts perform safest for eligibility.
4. **Track:** `scripts/metrics.py` snapshots followers + 28-day reach every
   month (`metrics.jsonl`). Review it here and we steer the algo.

## 7. When something breaks (alerts keep you posted)

Every bot-run failure and the weekly Sunday credential check ping you on
Telegram (bot + `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` secrets — message
the bot once first, then set your numeric chat id). Triage by cause:

1. **FB token dead/expired** (`FB token invalid`, `debug_token error`,
   publish `OAuthException`). Fix: re-seed per section 3. If the monthly
   self-heal workflow also fails with exit 4, the user token is fully
   dead — a human login is required, it cannot self-fix.
2. **All Gemini keys exhausted** (`429`, `quota`, `GenerateContent 400`).
   Fix: wait for the daily quota reset, or add fresh AI Studio keys to
   `GEMINI_API_KEYS` (comma-separated). Rotation + failover is automatic.
3. **QC loop** (`Quality check FAILED`, exit 3). Fix: read the listed
   reason in the run log (usually length/tags); the writer prompt or
   thresholds need a nudge — tell me here and we tune it.
4. **Publish error** (FB API message in log, e.g. permission removed).
   Fix: re-grant `pages_manage_posts` on the Page for the App, then test
   with a dry run (`Run workflow` → dry_run=1).
5. **Leadership mismatch** (`LEADERSHIP MISMATCH ... may have changed`).
   Not fatal — the bot falls back to flag/institution visuals. Fix: confirm
   the new officeholder via an official source, then update the hint in
   `OFFICES` (`post_bot.py`) so inferred faces resume.

## Files

- `ethan-cole-fb-bot/post_bot.py:1` — fetch → filter → rewrite → QC → publish
- `ethan-cole-fb-bot/.github/workflows/fb-post.yml:1` — 20-min schedule
- `ethan-cole-fb-bot/posted.json:1` — dedup state (auto-committed)
