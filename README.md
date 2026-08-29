# empire-dojo

The student-facing practice platform ("Darb") for the Empire English Community
Discord Learning Bot.

Covers the **six CEFR levels A1–C2** across **90 curriculum weeks** — accent
drills, vocabulary flashcards, shadowing, listening, speaking, reading, mediation,
extended listening (multi-voice broadcast scripts), grammar cards and weekly
review. **6,948 generated pages** and **1,095 pre-rendered Kokoro TTS clips**.

Live at: https://practice.empireenglish.online

> **Updated 2026-08-29.** This README previously said "Covers L0-L3 curriculum
> (38 weeks)". The home-grown L0–L3 model was retired and its content deleted on
> 2026-08-25; CEFR A1–C2 is the only curriculum. Corrected as part of the
> [2026-08-29 ecosystem audit](https://github.com/empireenglishcommunity-glitch/empire-chronicle/blob/main/audits/2026-08-29-ECOSYSTEM-AUDIT.md)
> (private repo).

## Repo layout

```
site/       <- THE DEPLOYED WEBSITE. Only this directory is uploaded to
               Cloudflare Pages. Nothing else in this repo should ever be
               publicly reachable.
scripts/    <- build + verification tooling (generate.py, generate_audio.py,
               the audio manifest, and the four verify_*.py checks). Lives
               OUTSIDE site/ on purpose so it is structurally impossible to
               deploy by accident, regardless of how the deploy command is
               configured.
functions/  <- Cloudflare Pages Function: the edge gate (_middleware.js).
               Verifies the student's HMAC session, scopes each student to
               their own CEFR level, and passcode-gates /ops-guide and
               /content-review.
docs/       <- audio render runbook, storage decision, recording brief.
```

This split exists because of a real incident: an earlier deploy uploaded the
entire repo root (including `generate.py`, `generate_audio.py`, and
`audio-manifest.json`) as public site files. Moving those files into a
same-level `scripts/` folder (commit `2c5b622`) was not a complete fix,
because that folder was still *inside* the directory that got deployed.
The actual fix is this `site/` vs `scripts/` split — deploy tooling must
always point at `site/` as the build output directory, never the repo
root.

## Content source of truth

**This repo authors no curriculum content.** Every page is generated from
`empire-nexus/bots/discord-learning-bot/`'s `content/` and `data/`. If a level or
week is missing content, fix it *there* — never invent placeholder content here.

## Regenerating the site

```bash
# From a checkout with empire-nexus cloned as a sibling directory:
#   parent/
#     empire-nexus/
#     empire-dojo/
cd empire-dojo
python3 scripts/generate.py                                      # writes into site/
EEC_REPO_DIR=/path/to/empire-nexus python3 scripts/generate.py   # explicit path

# Kokoro TTS audio (writes into site/audio/, needs the Kokoro host reachable):
python3 scripts/generate_audio.py
```

**Commit the regenerated `site/`.** CI enforces that the committed `site/` is
byte-identical to what `generate.py` produces, because `site/` is what actually
gets deployed.

## Verifying

All four run locally and the first four run in CI on every PR:

```bash
python3 scripts/verify_pages.py                 # 6,948 pages: structure + injection sweep
python3.12 scripts/verify_audio_pace.py         # delivery pace per CEFR level (needs: pip install soundfile)
EEC_REPO_DIR=<nexus> python3 scripts/verify_authentic_audio.py   # authentic-audio declarations
python3 scripts/diff_against_live.py <url>      # committed pages vs a live/preview URL
```

Notes worth knowing:

- **Use `python3.12`** for `verify_audio_pace.py`. Python 3.9 is too old for parts
  of this tooling.
- **Delivery pace is a descriptor requirement, not a preference.** A1's
  `A1.R.1` says "speak slowly and clearly"; C2's `C2.R.1` says "fast native
  speed". Pace is normalised **per voice** because the Kokoro voices differ by
  **1.84×** at the same speed setting — before that was handled, some C1/C2 clips
  rendered slower than the A1 target.
- **`verify_authentic_audio.py` catches mechanical failures only** — a missing
  file, an implausibly small one, or one byte-identical to the TTS clip it claims
  to replace. Declaring a scene authentic is a **human trust declaration** that no
  script can verify. Never call a green tick here proof of authenticity.

## Deploying (Cloudflare Pages)

> ⚠️ **Merging is NOT deploying.** This repo has no auto-deploy — CI only
> *verifies*. The live site reflects whatever was last deployed by hand.

```bash
cd empire-dojo && git checkout main && git pull
npx wrangler pages deploy site --project-name=empire-practice --branch=main
```

Never run `wrangler pages deploy .` from the repo root — that would re-expose
`scripts/` as public assets.

> Note: `empire-practice` is the Cloudflare Pages **project** name, not this
> repo's name (this repo is `empire-dojo`). The Pages project kept its original
> name across the repo rename.

**When the bot and a page change together, deploy the page FIRST**, then merge the
bot. Pages are written to render both the old and new payload shapes; the bot is
not written to guess which page is live.

## Related

- **`empire-nexus`** — the bot: curriculum source, and the consumer of this site's
  URLs. Any URL-shape change here needs a matching change there.
- **`empire-chronicle`** (private) — cross-project memory. Read its `STATUS.md`
  first, then `SYSTEM-MAP.md` §12, before starting new work here.
