
# empire-practice — AI Agent Steering Rules

> This file is automatically loaded by Kiro and any AI agent working on this repository.
> It provides critical context, constraints, and decision rules for all future work.

---

## 1. Project Identity

- **Project:** Empire English Practice Platform — the web companion to the Discord Learning Bot
- **Parent project:** Empire English Community (see `EEC-REPO/.kiro/steering/project-rules.md` for org-wide rules)
- **Purpose:** Gives students a page to land on when a Discord daily task says "go practice your accent/shadowing/listening/vocab" — the bot links here, this repo has no independent content strategy of its own
- **Live at:** https://practice.empireenglish.online
- **Repository:** `empireenglishcommunity-glitch/empire-practice`

---

## 2. Repository Structure (STRICT — read before deploying)

```
empire-practice/
├── site/       <- THE DEPLOYED WEBSITE. This is the ONLY directory that
│                  should ever be uploaded to Cloudflare Pages. Nothing
│                  else in this repo should ever be publicly reachable.
├── scripts/    <- build tooling (generate.py, generate_audio.py, the
│                  audio manifest). Lives OUTSIDE site/ on purpose — it
│                  must be structurally impossible to deploy by accident,
│                  no matter how the deploy command is configured.
└── README.md
```

**Why this split exists (do not "simplify" it away):** an earlier deploy
uploaded the entire repo root — including `generate.py`,
`generate_audio.py`, and `audio-manifest.json` — as public site files.
A first attempt at fixing this just moved those files into a same-level
`scripts/` folder, which was **not actually a fix** — that folder was
still *inside* the directory being deployed, so `scripts/generate.py`
was still publicly reachable at that URL. The real fix (`empire-practice
PR #4`) was this `site/` vs `scripts/` split. Never deploy `.` (the repo
root) — always deploy `site/` explicitly.

Also watch for: `.pyc` bytecode files and other build artifacts getting
committed to git and then served publicly. `.gitignore` does **not**
retroactively untrack files that are already committed — if you find a
build artifact tracked in git, use `git rm --cached` to actually remove
it, not just add a gitignore rule.

---

## 3. Content Source of Truth

- **All curriculum content (vocabulary, accent drills, shadowing text) comes from `EEC-REPO/bots/discord-learning-bot/`** — specifically its `data/` and `content/` directories. This repo has ZERO independent content — it only renders what the bot's curriculum already contains.
- Never fabricate or invent curriculum content here (dialogue, vocabulary, drills) to "fill in" a level or week. If real content doesn't exist yet in EEC-REPO for some week/level, that's a signal to go fix it there, not to invent placeholder text here.
- `LEVEL_WEEK_COUNTS = {"l0": 8, "l1": 10, "l2": 12, "l3": 8}` in `scripts/generate.py` MUST always match the identical constant in `EEC-REPO/bots/discord-learning-bot/src/curriculum.py`. If the bot's curriculum grows (new weeks/levels), update both in the same PR.
- Shadowing pages use the curriculum's real `sentence_practice`/`record_this` text. Listening pages use a grounded vocab-comprehension check (hear a real word, pick its correct Arabic meaning from real same-week distractors) — this was a deliberate choice to scale to all weeks without fabricating dialogue content that only existed for weeks 1-2 in an earlier version of this generator.
- Vocab flashcard pages (1,843 words across L0-L3) deliberately do NOT have pre-generated Kokoro audio — only browser TTS. This was a scope/storage tradeoff, explicitly flagged as open to revisiting.

---

## 4. Regenerating the Site

Requires `EEC-REPO` cloned as a sibling directory:
```
parent/
  EEC-REPO/
  empire-practice/
```

```bash
cd empire-practice
python3 scripts/generate.py                # writes into site/, all 4 levels
python3 scripts/generate.py --level l1      # single level only
EEC_REPO_DIR=/path/to/EEC-REPO python3 scripts/generate.py   # override sibling assumption

# Kokoro TTS audio for shadowing pages (writes into site/audio/):
python3 scripts/generate_audio.py
```

After any regeneration, diff `site/` against what's currently committed
before pushing — a generator bug should never be assumed absent just
because the script exited 0. (A real, previously-shipped bug: after the
`scripts/` folder move, `generate.py`'s default `EEC_REPO_DIR` path
calculation pointed one directory level too deep and would have failed
outright — caught only by actually re-running the script, not by code
review.)

---

## 5. Deploying (Cloudflare Pages)

```bash
npx wrangler pages deploy site --project-name=empire-practice
```

**Never** run `wrangler pages deploy .` from the repo root.

- Cloudflare account ID: `8c2ca895bd4e579be07d2fa6c9fdba7e`
- Pages project: `empire-practice` (id `49ff22c0-f95c-4e25-bcc5-0b370856b186`)
- Default subdomain: `empire-practice-8l0.pages.dev`
- Custom domain: `practice.empireenglish.online`

### Known quirk — extensionless URLs only
Every internal link (Discord bot task links, in-page nav) points at
extensionless paths (e.g. `/l1/week3/day2/accent`, not `.../accent.html`).
This is required, not stylistic: `.html`-suffixed static asset paths
were verified to return a genuine, non-cached 404 (`cache-control:
no-store`) on the custom domain, while the identical extensionless path
returns 200 everywhere. **Root cause is now understood** (as of the
2026-07-11 DNS zone migration documented in
`Kiro-Master-Index/SESSION_CONTINUITY.md`'s "session 5" section): the
domain's original Cloudflare account had some non-default Page Rule or
Cache Rule intercepting `.html` requests before Cloudflare Pages' own
redirect logic could run. That account is now permanently inaccessible,
so the exact rule can never be inspected — but a fresh, clean zone
(the one this domain now lives in) has zero custom Page Rules/Cache
Rules and correctly 308-redirects `.html` to the extensionless form,
confirming this was account-specific misconfiguration, not a Cloudflare
Pages platform quirk. **Keep using extensionless URLs regardless** —
it's the correct, portable pattern either way. If you ever add a new
generated page type, link to it without the `.html` suffix.

### API token / Cloudflare account
As of 2026-07-11, `empireenglish.online`'s DNS zone lives under the
Cloudflare account `Macalempire@gmail.com` (account id
`8c2ca895bd4e579be07d2fa6c9fdba7e`) — the same account that owns this
project's Pages deployment. A zone-scoped API token with `Zone:Zone
Read`, `Zone:DNS Edit`, `Zone:Page Rules Edit`, and `Zone:Cache Rules
Edit` permissions (no listed expiry as of its creation) was issued for
that migration — if it's still valid, it can also be used for
Pages-affecting zone work here, but always verify via
`/user/tokens/verify` first, never assume a token is still active.
See `Kiro-Master-Index/SESSION_CONTINUITY.md`'s "session 5" section for
the full migration history before assuming anything about domain/zone
config.

---

## 6. Verification Discipline

This repo has been the source of multiple real, live bugs that looked
fine at first glance:
1. Repo-root deploy exposing build scripts publicly.
2. Committed `.pyc` files also exposed publicly.
3. A silently-broken default path after a file move (never re-run after moving).
4. Every single Discord-bot-generated link 404ing in production due to a `.html` suffix.

None of these were caught by reading code or by a single `curl` on one
URL — they were caught by systematically crawling the full site (all
pages, all audio files) against the **live production domain**, using
the **exact URL shape the consuming system (the Discord bot) actually
generates**, not an assumed/simplified version of it. Do this again
after any deploy-affecting change:

```bash
# Crawl every generated page + audio file against the live custom domain,
# using extensionless paths (matching what the bot actually links to).
```

Never declare a fix "done" based on the deploy command exiting 0, or
based on one or two spot-checked URLs.

---

## 7. Related Repos

- `EEC-REPO/bots/discord-learning-bot/` — canonical curriculum source AND the consumer of this site's URLs (`src/curriculum.py`'s `practice_platform_task_url()`/`practice_platform_day_url()`). Any URL-shape change here requires a matching change there, and vice versa.
- `Kiro-Master-Index` — session checkpoint history for this whole project; read `SESSION_CONTINUITY.md` before starting new work here.
