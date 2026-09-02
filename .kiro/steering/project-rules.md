
# empire-dojo — AI Agent Steering Rules

> This file is automatically loaded by Kiro and any AI agent working on this repository.
> It provides critical context, constraints, and decision rules for all future work.

---

## 1. Project Identity

- **Project:** Empire English Practice Platform ("Darb") — the web companion to the Discord Learning Bot
- **Parent project:** Empire English Community (see `empire-nexus/.kiro/steering/project-rules.md` for org-wide rules)
- **Levels:** the **six CEFR levels A1–C2**, 90 curriculum weeks, 6,948 generated
  pages, 1,095 Kokoro TTS clips. *(Updated 2026-08-29 — legacy `L0`–`L3` was
  retired and its content, pages and audio deleted on 2026-08-25. Anything in
  this file still written in L0–L3 terms is historical.)*
- **Purpose:** Gives students a page to land on when a Discord daily task says "go practice your accent/shadowing/listening/vocab" — the bot links here, this repo has no independent content strategy of its own
- **Live at:** https://practice.empireenglish.online
- **Repository:** `empireenglishcommunity-glitch/empire-dojo`
- **Note:** this repo was previously named `empire-practice`. The Cloudflare Pages *project* is still named `empire-practice` (unchanged, external resource) — only the GitHub repo was renamed. Don't confuse the two.

---

## 2. Repository Structure (STRICT — read before deploying)

```
empire-dojo/
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
was still publicly reachable at that URL. The real fix (this repo's
PR #4, back when it was still named `empire-practice`) was this
`site/` vs `scripts/` split. Never deploy `.` (the repo root) — always
deploy `site/` explicitly.

Also watch for: `.pyc` bytecode files and other build artifacts getting
committed to git and then served publicly. `.gitignore` does **not**
retroactively untrack files that are already committed — if you find a
build artifact tracked in git, use `git rm --cached` to actually remove
it, not just add a gitignore rule.

---

## 3. Content Source of Truth

- **All curriculum content (vocabulary, accent drills, shadowing text) comes from `empire-nexus/bots/discord-learning-bot/`** — specifically its `data/` and `content/` directories. This repo has ZERO independent content — it only renders what the bot's curriculum already contains.
- Never fabricate or invent curriculum content here (dialogue, vocabulary, drills) to "fill in" a level or week. If real content doesn't exist yet in empire-nexus for some week/level, that's a signal to go fix it there, not to invent placeholder text here.
- `CEFR_WEEK_COUNTS = {"a1": 10, "a2": 12, "b1": 14, "b2": 16, "c1": 18, "c2": 20}` in `scripts/generate.py` MUST always match the identical constant in `empire-nexus/bots/discord-learning-bot/src/curriculum.py` (which keys it upper-case: `{"A1": 10, …}`). If the bot's curriculum grows, update both in the same PR. *(Corrected 2026-08-29: this rule previously named `LEVEL_WEEK_COUNTS = {"l0": 8, "l1": 10, "l2": 12, "l3": 8}`, which is now an empty dict on both sides — legacy L0–L3 was retired 2026-08-25. Following the old rule literally would have told you to restore a retired model.)*
- Shadowing pages use the curriculum's real `sentence_practice`/`record_this` text. Listening pages use a grounded vocab-comprehension check (hear a real word, pick its correct Arabic meaning from real same-week distractors) — this was a deliberate choice to scale to all weeks without fabricating dialogue content that only existed for weeks 1-2 in an earlier version of this generator.
- Vocab flashcard pages (1,843 words across L0-L3) deliberately do NOT have pre-generated Kokoro audio — only browser TTS. This was a scope/storage tradeoff, explicitly flagged as open to revisiting.
- **Every curriculum-derived string must go through `esc_html()` (for HTML body/attribute context) or `safe_json_for_script_tag()` (for embedding inside a `<script>` tag) before being written into generated HTML.** Found via adversarial-input stress testing (2026-07-13, [PR #10](https://github.com/empireenglishcommunity-glitch/empire-dojo/pull/10)): curriculum text was previously interpolated raw, and a crafted `<img onerror>` in a vocabulary word's `arabic` field was proven to actually execute in a browser via `app.js`'s `Flashcard.render()` (which itself was also fixed to use `textContent`/`createElement` instead of `innerHTML`). If you add a new page generator function in `generate.py`, apply the same escaping to any curriculum-derived value before interpolating it — don't assume curriculum content is safe just because it's currently hand-authored/repo-committed rather than user-submitted.
- **Bilingual UI labels: `bl()` produces HTML (a `<span>`) — use it ONLY in element BODY content. In an HTML ATTRIBUTE (`placeholder`, `title`, `aria-label`, `value`), use `bl_attr()` instead.** `bl(en, ar)` returns `en <span class="ar-inline" …>/ ar</span>`; that span is valid between tags (buttons, headings, instructions) but **not** inside an attribute — the span's first `"` terminates the attribute and the rest of the markup leaks into the UI as literal text. Found live 2026-08-29 ([PR #136](https://github.com/empireenglishcommunity-glitch/empire-dojo/pull/136)): the grammar fill-in-the-blank `<input>` and the mediation `<textarea>` used `placeholder="{bl(...)}"`, so students saw `your answer <span class` and `اكتب اللي هتقوله...<span/>"` inside the fields. `bl_attr(en, ar)` returns `esc_html(f"{en} / {ar}")` — plain, attribute-safe text like `your answer / جوابك`. Rule: any bilingual label going into an attribute uses `bl_attr`; never put `bl()` (or any raw `<…>` markup) inside a `"…"` attribute value. A quick guard when in doubt: after regenerating, `grep -rE 'placeholder="[^"]*<' site/` (and the same for `title=`/`aria-label=`) must return zero matches.

---

## 4. Regenerating the Site

Requires `empire-nexus` cloned as a sibling directory:
```
parent/
  empire-nexus/
  empire-dojo/
```

```bash
cd empire-dojo
python3 scripts/generate.py                # writes into site/, all 4 levels
python3 scripts/generate.py --level l1      # single level only
EEC_REPO_DIR=/path/to/empire-nexus python3 scripts/generate.py   # override sibling assumption

# Kokoro TTS audio for shadowing pages (writes into site/audio/):
python3 scripts/generate_audio.py
```

After any regeneration, diff `site/` against what's currently committed
before pushing — a generator bug should never be assumed absent just
because the script exited 0. (A real, previously-shipped bug: after the
`scripts/` folder move, `generate.py`'s default `EEC_REPO_DIR` path
calculation pointed one directory level too deep and would have failed
outright — caught only by actually re-running the script, not by code
review. A second, since-fixed bug: after both repos were renamed
[`EEC-REPO`→`empire-nexus`, `empire-practice`→`empire-dojo`], the
default sibling-directory path still pointed at the old `EEC-REPO` name,
so `python3 scripts/generate.py` with no `EEC_REPO_DIR` override failed
outright for anyone following this file's own setup instructions.
Verified fixed by actually running the command, not just editing text.)

---

## 4.5. Audio: the single brand voice, pacing, and the render rule

> Owner decision (2026-09-02): **`af_heart` is the ONE brand voice for the
> entire platform** — every UI surface AND every extended-listening broadcast
> passage. This replaced an earlier multi-voice cast and a rotating listening
> set. Do NOT reintroduce other voices or a rotation without the owner's
> explicit agreement. The decision and its rationale are recorded in
> `scripts/voice_cast.json` under `_brand_voice_decision_2026_09_02`.

**Two separate audio systems — know which you're touching:**

- **UI speech clips** (vocab, grammar, listening, reading, shadowing, etc.):
  served from **R2** at `audio.empireenglish.online/speech/<vN>/<clip-id>.mp3`.
  Clip id = `sha256(voice|normalised text)[:16]`, so the id changes if the voice
  OR the text changes. Rendered by `scripts/render_speech.py` via the
  **`speech render (kokoro -> R2)`** GitHub workflow. The committed record of
  what's on R2 is `scripts/speech-rendered.json`, which `speech_registry.py
  --check` gates on. Current prefix: **`speech/v4`** (also in `site/js/app.js`
  `BASE`).
- **Broadcast (extended-listening) clips:** committed in-repo under
  `site/audio/*.mp3`, served by Cloudflare Pages. Rendered by
  `scripts/render_broadcast_local.py`. Cache-busted by the service worker
  `CACHE_NAME` in `site/sw.js` (currently `empire-v9`).

**The voice cast is DUPLICATED in two files and a parity test enforces they
match:** `scripts/voice_cast.json` (Python) and `site/js/speech-id.js`
(`CAST` + `LISTENING_ROTATION`, because the browser can't read the JSON).
Change both together or `verify_clip_id_parity.py` fails the build.

**Pace must NOT be achieved by slowing synthesis.** Kokoro corrupts phonemes
below ~0.90 `speed` (ASR-confirmed: af_heart at 0.73 renders "She is a student."
as "as she is a student."). af_heart's natural rate is ~212 wpm, so the lower
CEFR levels — which the descriptors require to be *slow* — are handled by
`audio_pace.split_pace()`: render at a phoneme-safe floor (≥ 0.90) and apply the
rest of the slowdown at **playback** via `audio.playbackRate` (the browser
pitch-corrects; phonemes are untouched). The per-clip `playback_rate` is stored
in `audio-manifest.json` and emitted into the page. `verify_audio_pace.py`
measures **effective** pace (rendered × playback_rate), not raw file duration.
If you add a voice or change pacing, keep this split — do not render below 0.90.

**⚠️ THE RENDER RULE — read before adding or editing curriculum audio:**
The **assessment** (`/assessment/`) and **placement** (`/placement/`) tests build
their listening dictation from the SERVER at runtime (`TTS.speak(item.say_en)`),
NOT from static pages. So `speech_registry.scan()`, which only reads generated
HTML, cannot see those words. `speech_registry.add_assessment_pool()` closes
this by pulling the whole assessment/placement word pool (every vocabulary
`word` + authored `say_en` in `empire-nexus/.../data/*.json`) into the render set
and the `--check` gate.

Consequence you MUST remember:
- **Whenever curriculum vocabulary or listening content changes in empire-nexus
  (new words, new weeks, edited text), RUN THE `speech render` WORKFLOW** so the
  new/changed words get af_heart clips on R2. A word with no clip shows students
  the red "Audio missing for this page" banner. `speech_registry.py --check` (in
  CI) now flags any uncovered word, so a red gate here means "render, don't
  override".
- Single-letter WORDS ("I", "a") are legitimate and must be rendered — see
  `is_speakable()`. This exact gap once left the a1 word **"I"** (أنا) with no
  clip, reported by a student. Don't reinstate a blanket `len < 2` skip.

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
`empire-chronicle/SESSION_CONTINUITY.md`'s "session 5" section): the
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
See `empire-chronicle/SESSION_CONTINUITY.md`'s "session 5" section for
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

## 7. What CI actually checks (and what it deliberately cannot)

*(This section number was missing entirely until 2026-08-29 — the file jumped
from §6 to §8. Added here because the CI gates were expanded in the same pass.)*

`.github/workflows/dojo-verify.yml` runs on every PR touching `scripts/` or
`site/`, and on pushes to `main`. **Five gates, in order:**

1. **Regenerate** `site/` from `empire-nexus`'s curriculum.
2. **Drift gate** — `git diff --quiet -- site/ scripts/audio-manifest.json`.
   The committed `site/` must be **byte-identical** to what `generate.py`
   produces. Before 2026-08-29 the workflow regenerated `site/` and then verified
   the *regenerated* output, which meant a divergence between the committed pages
   and the generator could never fail the build — and `site/` is the thing that
   actually gets deployed. So **commit your regenerated pages**; if this gate
   fails, run `EEC_REPO_DIR=<nexus> python3 scripts/generate.py` and commit.
3. **`verify_pages.py`** — 6,948 pages, real `html.parser` parse + injection sweep.
4. **`verify_audio_pace.py`** — delivery pace per CEFR level. **Not cosmetic:**
   several descriptors are claims about speed (`A1.R.1` "speak slowly and
   clearly" … `C2.R.1` "fast native speed") and this is the only check that tests
   that claim against the rendered artefact. It has caught a real shipped defect.
   Needs `pip install soundfile`.
5. **`verify_authentic_audio.py`** — guards the two film reservations
   (`B2.R.2`, `C1.R.2`).

**What CI cannot check, so you must:**

- **Visual regression.** A page can parse cleanly, match the generator and still
  look broken. That is what §8's preview-URL discipline is for.
- **Whether the English is any good.** The validators check shape, script purity
  and structure — not writing quality. A green build has passed an ungrammatical
  sentence before.
- **Per-clip pace for short clips.** Only clips at or above
  `MIN_WORDS_FOR_PACE` are measurable — currently **204 of 465** broadcast clips.
  The rest contribute nothing to the aggregate, so "pace verified" means *per
  level*, not *per clip*. Do not overstate it.
- **That audio declared authentic really is authentic.** Gate 5 catches missing
  files, implausibly small files, and files byte-identical to the TTS clip they
  claim to replace. It **cannot** distinguish a human performance from a
  convincing substitute. Listing a scene in `authentic_audio.json` is a human
  trust declaration. Never call a green tick proof of authenticity.
- **That the live site is current.** CI never deploys. See §8.5.

---

## 8. Preview Discipline (Aegis — never merge a visual change unseen)

> 🔴 **CORRECTED 2026-08-29.** This section used to assert: *"Cloudflare Pages
> automatically generates a unique preview URL for every PR branch (visible in the
> PR's Deployments section or commit status checks). This has been happening since
> the project's creation."* **That is false, and following it wastes time looking
> for a URL that does not exist.** The Pages project has **no Git integration** —
> the Cloudflare API reports `source: null` for `empire-practice`, which means
> Cloudflare never sees the GitHub repo and therefore builds **no automatic
> preview deployments for PRs at all**. Verified by API inspection, and by PR #136
> having no preview URL. Every deployment this project has ever had was pushed
> **manually** with `wrangler`. Do not go hunting for a preview link in the PR UI.

**Hard rule: never merge a PR that changes what a student SEES (`site/`, or
`scripts/generate.py` output) without previewing it somewhere first.**

Since there are no automatic previews, create one deliberately. Two options:

```bash
# A. Named preview alias (does NOT touch production, which is branch "main"):
npx wrangler pages deploy site --project-name=empire-practice --branch=preview-<topic>
#    -> serves at https://preview-<topic>.empire-practice-8l0.pages.dev

# B. Purely local, no Cloudflare needed — enough for layout/markup checks:
python3 -m http.server 8000 --directory site
#    (the edge gate in functions/ does not run locally, so pages render ungated)
```

Why previewing matters at all:
- `generate.py` exiting 0 does NOT mean the pages look right (see
  rule 6 above — multiple real bugs passed exit-0 checks).
- The CI `verify_pages.py` check catches structural/injection issues,
  but it can't catch visual regressions (layout broken, wrong content
  displayed, CSS broken).
- Creating a preview costs one command — cheaper than shipping a broken
  page to 17 students and finding out from a screenshot.

What previewing means in practice:
1. Open the preview alias (or the local server) you created above.
2. Spot-check at least one page per affected level (**A1–C2**; the legacy
   L0–L3 zone was retired 2026-08-25 and no longer exists).
3. Confirm the page loads, renders correctly, has the right content, and
   navigation links work.
4. Optionally run the differ to confirm only intended changes are present:
   ```bash
   python3 scripts/diff_against_live.py <preview-or-live-url>
   ```

**A worked example of why this section exists:** on 2026-08-29 the grammar
fill-in-the-blank and mediation pages shipped with raw HTML inside their input
`placeholder` attributes (`your answer <span class …`) — see §3's `bl_attr` rule.
`verify_pages.py` passed all 6,948 pages, the drift gate was green, and the
generator exited 0. Only a human looking at the page caught it, and that human
was a **student**. Structural validators cannot see "this looks broken."

---

## 8.5. Production Deploy (Hisn — merge now deploys itself, but verify)

> ✅ **UPDATED 2026-08-29.** This section used to say *"merging a PR to `main`
> does NOT put it on the live site — this repo has no CI/CD auto-deploy
> pipeline"*. **That is no longer true.** `.github/workflows/deploy-site.yml`
> now deploys `site/` to Cloudflare Pages automatically on every push to `main`
> that touches `site/`, `functions/`, or that workflow. The manual command is
> still the fallback and is still what you use for previews.

**How production is updated now:** merge to `main` → `deploy-site.yml` runs
`wrangler pages deploy site` → it then **asserts against the Cloudflare API that
the newest production deployment carries that exact commit** (not merely that
wrangler exited 0), plus an advisory live-asset hash check.

**Manual deploy** (fallback, or after changing something outside those paths):
```bash
cd empire-dojo
git checkout main && git pull
npx wrangler pages deploy site --project-name=empire-practice --branch=main
```

**Why this automation exists — the gap was real, twice:**
- **2026-07-15 (defect D008):** PR #21 (Wuslah W1 dashboard) was merged but
  nobody ran the deploy. Live kept serving an older build — missing the whole
  `/dash/` page and the homepage link to it — caught only by a crawler diffing
  repo state against live HTTP responses.
- **2026-08-29:** PR #135 was merged and sat undeployed until an unrelated
  deploy happened to carry it. Harmless *that* time (it changed no `site/`
  files), but the same hole. A "hard rule" that depends on a human remembering
  is not a control; a workflow is.

**Still true, and still your job:** auto-deploy proves the bytes are live, not
that they are *correct*. §8's preview discipline is not optional — production
deploying itself makes an unreviewed visual regression reach students *faster*.

**Two Cloudflare facts worth knowing before you debug a deploy:**
- The Pages project has **no Git integration** (`source: null`). Cloudflare is
  not watching this repo; the GitHub Action is the only thing that pushes.
  So the *only* deploys that exist are ones a workflow or a human ran.
- The workflow needs the repository secret **`CLOUDFLARE_API_TOKEN`**
  (scope: *Account > Cloudflare Pages > Edit*). If it is missing or revoked the
  workflow fails loudly on its first step by design — never silently.

If you ever doubt whether live is current, don't guess: query the API for the
newest production deployment's commit and compare it to `main`, and/or hash an
ungated public asset (`/js/app.js`, `/css/empire.css`) against the repo copy.
Content pages cannot be checked anonymously — `functions/_middleware.js` serves
the "Access Required" gate to any request without a student session, so a curl
of `/a1/week1/day1/grammar` returns the gate, **not** stale content.

---

## 9. Related Repos

- `empire-nexus/bots/discord-learning-bot/` — canonical curriculum source AND the consumer of this site's URLs (`src/curriculum.py`'s `practice_platform_task_url()`/`practice_platform_day_url()`). Any URL-shape change here requires a matching change there, and vice versa. (Formerly named `EEC-REPO` — update this note again if it's renamed a second time.)
- `empire-chronicle` — session checkpoint history for this whole project (superseded the old `Kiro-Master-Index` name); read its `SESSION_CONTINUITY.md` before starting new work here.
