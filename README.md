# Ethan Cole FB auto-poster

Runs every 20 min via GitHub Actions. 1 post max per run, only if fresh
finance/AI news passes the filter. Dedup via `posted.json`.

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

## 3. Local test

```
python -m pip install -r requirements.txt
set DRY_RUN=1
python -c "import post_bot; print(len(post_bot.fetch_candidates(70))))"
```

Full dry run needs an LLM key:
```
set ANTHROPIC_API_KEY=sk-ant-...
set DRY_RUN=1
python post_bot.py
```

## 4. Tuning

- `RSS_FEEDS` / `TOPIC_WEIGHTS` / `EXCLUDE` / `X_HANDLES` in `post_bot.py` control what qualifies.
- `MAX_AGE_MINUTES` (default 70) = how fresh news must be. Cron is 20 min, 70 gives overlap.
- Voice rules live in `SYSTEM_PROMPT` — mirrors the Ethan Cole skill (verify → rewrite → context → hook → QC).

## Files

- `ethan-cole-fb-bot/post_bot.py:1` — fetch → filter → rewrite → QC → publish
- `ethan-cole-fb-bot/.github/workflows/fb-post.yml:1` — 20-min schedule
- `ethan-cole-fb-bot/posted.json:1` — dedup state (auto-committed)
