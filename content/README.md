# content/ — EdgeTrading Pro product posts (English page)

This folder holds the **ready-to-publish product posts** for the
"Ethan Cole Finance + AI" page, plus the images that go with them and the
two scripts that keep everything consistent.

```
content/
  product_posts.json   <- THE DELIVERABLE: 13 posts, machine readable
  image_spec.json      <- source of truth for the copy + which image each post uses
  img/                 <- 13 prepared 1200x630 JPGs, named after the post id
  src/                 <- the REAL product screenshots the images are built from
  make_images.py       <- rebuilds img/*.jpg and rewrites product_posts.json
  check_posts.py       <- house-style QC over product_posts.json
```

## 1. The format

`product_posts.json` is a **JSON array** of post objects. One object per
post, no wrapper object, `lang` inside every entry tells you which page it
belongs to.

```jsonc
{
  "id": "en-07-nvda-model-fair-value",   // unique, also the image filename
  "lang": "en",                          // "en" | "ar"
  "title": "📉 Nvidia ($NVDA) AT $224.41 — THE MODEL'S FAIR VALUE IS $266.71",
  "body":  "Its DCF puts intrinsic value at $258.07 on a 15.0% WACC and 2.5% terminal growth. A 1,000-trial Monte Carlo P50 lands on $258.07, while 57 analysts carry a $325.98 consensus.",
  "hashtags": ["#ethancole", "#nvidia", "#stockmarket", "#investing", "#finance"],
  "image": "C:\\...\\content\\img\\en-07-nvda-model-fair-value.jpg",  // absolute path
  "image_rel": "img/en-07-nvda-model-fair-value.jpg",               // repo-relative
  "questions": ["Which input would you change first in a 15% WACC model?"],
  "cta": "EdgeTrading Pro founding spots are open — DM me and I'll send the suite details.",
  "source": "StockerAI terminal run for NVDA, data refreshed 2026-09-03 …",   // see §3
  "image_headline": "NVIDIA ($NVDA) — FAIR VALUE $266.71"                    // see §4
}
```

Required: `id`, `lang`, `title`, `body`, `hashtags`, `image`, `questions`,
`cta`.  `source`, `image_rel` and `image_headline` are extra and are used by
the tooling (§3, §4) — keep them when you edit.

> **`image` vs `image_rel`.** `image` is the **absolute** path to the
> prepared 1200×630 JPG, exactly as the campaign spec requires.
> `image_rel` is the same file relative to `content/`, and it is what the
> bot resolves first (`scripts/product_source.py` → `load_posts()`), because
> an absolute Windows path does not exist on the Linux runner that publishes
> the posts. **Set both.**

| field | rule |
|---|---|
| `id` | `en-NN-slug`, lower case. Must match the image filename. |
| `title` | the hook, **one line**, must contain a number, ≤ 110 chars. |
| `body` | 2–3 short sentences (or 2–3 emoji-led lines on the Arabic page). |
| `hashtags` | 5–6 tags, **`#ethancole` first**, then 4–5 house topic tags. |
| `image` | **absolute** path to a prepared 1200×630 JPG. |
| `image_rel` | the same file relative to `content/` — what the bot resolves. |
| `questions` | one genuine question a reader would actually answer. |
| `cta` | the call to action. A DM ask, never a like/share/comment ask. |

## 2. House rules the posts already satisfy

`check_posts.py` re-runs the bot's own gates (`post_bot.py` →
`quality_check`, `_outlet_leak`, `_latin_runs`, `_dialect_hits`,
`_emoji_lines`) plus two campaign gates, and must print
`13 passed, 0 failed`:

* no source / outlet name, no URL, no bare domain, no `@handle`
* no attribution line (`Source:`, 🔗, 📸), no markdown (`*`, `` ` ``, `_x_`)
* no engagement bait (`share this`, `like if`, `comment below`, …)
* every company named with its ticker on first mention (`Nvidia ($NVDA)`)
* every post carries at least one concrete number
* post length 180–350 characters (title + body + hashtags)
* **traceability**: every number in the copy also appears in that post's
  `source`, so no figure can be invented
* every image exists, is 1200×630, and is named after the post id

## 3. `source` — why every post carries one

`source` is the factual excerpt from the shipped product material (the
EdgeTrading 4‑in‑1 Pro indicator-suite manual, or a real StockerAI terminal
run) that backs the post. Two jobs:

1. **It is the provenance record.** The bot's prompt is SOURCE‑ONLY
   ("use ONLY the facts… stated in the provided headline/summary"). Pass
   `source` as the Headline/Summary to the writer and every claim is inside
   the source window.
2. **It feeds the Arabic Latin allowlist.** The Arabic QC allows a Latin
   token only if it is a ticker, a mapped name, or a word that appears in
   the source it was given. `source` is where `COT`, `DCF`, `WACC`,
   `Monte Carlo`, `Composite Score`, `EdgeTrading`, `StockerAI` … come from.

Never delete `source`, and never write a number in the copy that is not in
it — `check_posts.py` fails the post.

## 4. `image_headline` and the images

`image_headline` is the single line of type that is burned into the image.
`make_images.py` composites it over the real product screenshot in the
brand's own dark system (deep matte black `#08090b`, volcanic panel
`#0d0e12`, corporate-blue accent `#3f61ec`), with a bottom gradient scrim
and a text stroke for legibility.

**Every image is a real screenshot of the product**, not an abstract
graphic:

| source | what it is |
|---|---|
| `web/image1.jpg` | EdgeTrading COT Index running on a live chart |
| `web/image2.jpg` | EdgeTrading Seasonality projection |
| `web/image3.jpg` | EdgeTrading smart money vs retail |
| `web/image4.jpg` | EdgeTrading Valuation Tool (BTC vs gold vs bonds) |
| `web/image5.jpg` | EdgeTrading 4‑in‑1 Pro hero asset |
| `pdfimg/p2_1.png` … `p5_1.png` | charts lifted out of the suite brochure PDF |
| `shots/nvda_dash.png`, `shots/nvda_stats.png` | the StockerAI terminal, rendered from its own `output/NVDA/NVDA_dashboard.html` |
| `shots/screener.png`, `shots/hub_index.png`, `shots/guide_top.png` | the terminal's screener, hub and quantitative reference guide |

Arabic images use the same screenshots with the headline in shaped Arabic
(`arabic-reshaper` + `python-bidi`, modern UAX#9 `bidi.get_display` — the
legacy `bidi.algorithm` mis-places brackets and currency signs), right
aligned, accent bar on the right.

## 5. Adding a post

1. Edit `content/image_spec.json` — add an object with the same keys
   (`id`, `lang`, `title`, `body`, `hashtags`, `image_src`,
   `image_headline`, `questions`, `cta`, `source`). `image_src` must be one
   of the keys in `SOURCES` inside `make_images.py`; add a new entry there
   if you need a new screenshot (drop the file in `content/src/`).
2. Run `python content/make_images.py --lang en`. It reads
   `content/image_spec.json` and `content/src/`, writes `img/<id>.jpg` and
   rewrites `product_posts.json` with the absolute and relative image
   paths.
3. Run `python content/check_posts.py`. Fix every FAIL before publishing.
4. The bot posts from `product_posts.json`: copy `title` + `body` +
   `hashtags` as the message, upload `image` with the post, append
   `questions[0]` and `cta`.

## 6. Notes for the owner

* `Altman`, `Piotroski`, `Beneish`, `DuPont` are the names of formulas and
  scores (the product's own module is literally labelled "Red flags
  (Beneish, Altman, DuPont)"), not listed companies — so they carry no
  ticker. Same for the product names `EdgeTrading`, `StockerAI`, `Pine`,
  `TradingView`.
* The CTA asks for a **DM**, never a like/share/comment: engagement bait
  kills Facebook Content Monetization eligibility.
* The NVDA numbers are a real terminal run stamped **2026‑09‑03**; that
  date is stated in the post. Re-run the terminal and refresh `source` (and
  the numbers) before re-publishing that post.
* Nothing in this folder invents performance, win rates, or guarantees.
  The indicator manual's own disclaimer (educational purposes only, not
  financial advice) is respected throughout.
