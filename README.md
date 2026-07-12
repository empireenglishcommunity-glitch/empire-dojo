# empire-dojo

Static practice platform for the Empire English Community Discord Learning
Bot. Covers L0-L3 curriculum (38 weeks) with accent drills, shadowing
(Kokoro TTS audio), listening comprehension, and vocabulary flashcards.

Live at: https://practice.empireenglish.online

## Repo layout

```
site/       <- THE DEPLOYED WEBSITE. Only this directory is uploaded to
               Cloudflare Pages. Nothing else in this repo should ever be
               publicly reachable.
scripts/    <- build tooling (generate.py, generate_audio.py, the audio
               manifest). Lives OUTSIDE site/ on purpose so it is
               structurally impossible to deploy by accident, regardless
               of how the deploy command is configured.
```

This split exists because of a real incident: an earlier deploy uploaded
the entire repo root (including `generate.py`, `generate_audio.py`, and
`audio-manifest.json`) as public site files. Moving those files into a
same-level `scripts/` folder (commit `2c5b622`) was not a complete fix,
because that folder was still *inside* the directory that got deployed.
The actual fix is this `site/` vs `scripts/` split — deploy tooling must
always point at `site/` as the build output directory, never the repo
root.

## Regenerating the site

```bash
# From a checkout with empire-nexus cloned as a sibling directory:
#   parent/
#     empire-nexus/
#     empire-dojo/
cd empire-dojo
python3 scripts/generate.py                # writes into site/
EEC_REPO_DIR=/path/to/empire-nexus python3 scripts/generate.py   # override path

# Generate Kokoro TTS audio for shadowing pages (writes into site/audio/):
python3 scripts/generate_audio.py
```

## Deploying (Cloudflare Pages)

Deploy **only** the `site/` directory, e.g.:

```bash
npx wrangler pages deploy site --project-name=empire-practice
```

> Note: `empire-practice` here is the Cloudflare Pages project name, not
> this repo's name (this repo is `empire-dojo`). The Pages project kept
> its original name across the repo rename.

Never run `wrangler pages deploy .` from the repo root — that would
re-expose `scripts/` (and any other non-site files) as public assets.
