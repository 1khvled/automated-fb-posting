# ⛔ ACCOUNT POLICY — READ BEFORE TOUCHING ANYTHING

**Owner mandate, 22 October 2026. This is a rule, not a preference.**

---

## 1. The one rule

**The personal Facebook account — "Khaled Abdelli" — is OFF LIMITS.**

It must never:

- post anything, anywhere
- browse as it, comment, react, like, share, message, or follow
- be signed into, by any tool, for any purpose
- be stored on this machine as a session, a cookie file, a browser profile, or a token
- be used "just to look at" something, or "just to list" something

**Every public post goes out as a PAGE**, using a page-scoped access token:

| page | id | what it is |
|---|---|---|
| **Ethan Cole** | `1264009986803820` | the English page — sells in USD to US readers |
| **سوق اليوم The Market Today** | `1421089964411983` | the Arabic page — news only, sells nothing |

If a task appears to need the personal account, **stop and ask.** Do not
improvise, and do not work around it.

---

## 2. The one exception, and why it is not an exception

Facebook pages are **owned** by the personal account. Minting a page token
requires the owner's user token — that is a one-time authorisation, and it
is the mechanism by which Facebook lets you act *as the page*. Minting a
page token is **not** acting as Khaled Abdelli.

| | permitted? |
|---|---|
| Minting a page token with the user token (`scripts/reseed_token.py`, `scripts/provision_page.py`) | **yes** — one-time, unavoidable, and it produces a *page* identity |
| Publishing a post with a page token | **yes** — this is the normal path |
| Publishing anything as Khaled Abdelli | **no** |
| Reading the feed of the personal account | **no** |
| Keeping a personal session on disk | **no** |

---

## 3. Where this is enforced in code, not by convention

- `eight-dollar/bot/group_share.py` — **hard-blocked.** Every command that
  would open a browser session (`--login`, `--find-groups`, `--probe`,
  `--share`) prints a refusal and exits. The module is kept only for the
  record of what it used to do.
- `eight-dollar/bot/group_share_page.py` — the replacement. It never opens a
  browser and never touches a personal session; it posts into groups **as the
  page** over the Graph API with a page-scoped token.
- The global agent memory at `~/.config/opencode/AGENTS.md` carries the same
  rule, so it applies in every session, not just this one.

The saved personal session was deleted from this machine on 22 October 2026.
Nothing is left behind: no profile folder, no cookie file, no browser process.

---

## 4. The group-sharing situation, honestly

Groups are the channel — a Facebook page's organic reach is about 1.25 % of
its followers, and groups deliver 10–20× that. Two facts decide it:

1. **The page must be a member of the group.** The owner adds it once, by
   hand: *page settings → Groups → add*. A page cannot post into a group it
   does not belong to.
2. **The app needs the `publish_to_groups` permission.** Without it the API
   answers, live, as of 22 October 2026:

   ```
   (#10) Application does not have the capability to make this API call.
   ```

   That is **App Review**: *facebook.com/developers → your app → App Review
   → permissions → `publish_to_groups`*. Days to weeks, and it can be
   refused.

Until both are true, the group path reports the exact blocker instead of
pretending. `python group_share_page.py --probe --page ethan` prints it.

**The pages' own feeds are unaffected** — they publish through the Graph API
with the same page tokens, and they are live.

---

## 5. If you are an agent reading this

The forbidden path is not "hard" or "awkward", it is **out of scope**. It
does not matter that it would be faster, that it would work today, or that
the alternative is blocked. If the only way forward seems to be the personal
account, then the honest answer is: **that part is blocked, and here is what
can be done instead.**
