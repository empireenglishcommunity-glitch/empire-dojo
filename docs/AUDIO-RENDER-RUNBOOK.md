# Audio render runbook

How to turn the authored extended-listening scripts into studio audio.

**Status: 162 clips are authored and registered but NOT rendered.** Every page
works without them — each clip falls back to the browser's speech voice — so
nothing is broken. But the fallback is noticeably worse, and for the multi-voice
scenes it changes the exercise (see [What the fallback costs](#what-the-fallback-costs)).

This has to run on a machine that can reach Kokoro. It cannot be done from the
build/CI environment, which has no Kokoro server.

---

## The one command

```bash
cd empire-dojo
python3 scripts/generate_audio.py
```

That is it. It will:

1. read `scripts/audio-manifest.json` (written by `generate.py`);
2. **skip** every clip that already has an MP3 — so the 630 existing shadowing
   clips are untouched and cost nothing;
3. render the 162 outstanding broadcast clips, **each in the voice its script
   names**;
4. write them to `site/audio/{clip_id}.mp3`;
5. **exit non-zero and list any clip it failed to produce.**

Expect roughly **20–45 minutes** on CPU-only inference, most of it in B2.

---

## Prerequisites

Kokoro must be running and reachable:

```bash
# default location the script expects
curl http://localhost:8880/health

# if it is elsewhere
export KOKORO_URL=http://my-host:8880
```

To start it (per the header of `scripts/generate_audio.py`):

```bash
cd /opt/kokoro-tts && docker compose up -d
```

The script probes Kokoro before doing anything and exits 1 with instructions if
it cannot connect, so a wrong URL fails immediately rather than half-way through.

---

## What gets rendered

| level | scripts | clips | words per clip | notes |
|---|---|---|---|---|
| A1 | 10 | 10 | 62–76 | one voice each — cheapest, and the most important to get right |
| A2 | 12 | 15 | 15–159 | mostly single voice; two scripts have 2–3 turns |
| B1 | 14 | 29 | 4–181 | phone-ins and interviews, 3–5 turns each |
| B2 | 16 | 108 | 1–256 | five long drama scenes; week 15 alone is 20 turns |
| **total** | **52** | **162** | | **8,574 spoken words** |

Clip ids are `{level}-w{week}-bc{index}` — no day component, because extended
listening is **weekly**: all seven days of a week share the same clips.

The longest single clip is `b2-w6-bc0` at **256 words**, about 100 seconds of
speech.

**Very short clips are expected, not a bug.** The drama scenes contain real
dialogue turns like *"And?"*, *"It's off."* and *"I know."* — some are one word.
They are separate clips because they are separate speakers. If you see a 4 KB MP3
in the B2 set, that is correct.

---

## Verifying afterwards

```bash
# 1. the script's own check — exits non-zero if anything is missing or empty
python3 scripts/generate_audio.py ; echo "exit=$?"

# 2. count what landed
ls site/audio/*-bc*.mp3 | wc -l          # expect 162

# 3. nothing should be zero bytes
find site/audio -name '*-bc*.mp3' -size 0

# 4. listen to one of each kind before trusting the batch
#    a beginner script, a news bulletin, and a two-person scene:
#      site/audio/a1-w1-bc0.mp3
#      site/audio/b2-w9-bc0.mp3
#      site/audio/b2-w15-bc0.mp3  (then bc1, bc2 — they should sound like
#                                  different people)
```

Then commit the new MP3s and deploy:

```bash
git add site/audio
git commit -m "chore: render extended-listening audio (162 clips)"
git push
# then the usual wrangler deploy
```

> **Size note.** `site/audio/` is already **151 MB** of committed MP3s. Measured
> against the existing clips (~5 KB per spoken word), these 8,574 words will add
> roughly **40 MB**, taking the directory to ~190 MB and the repo's `site/` to
> ~260 MB.
>
> That still works, but it is the point at which to decide about **Git LFS or an
> external bucket** — and to decide it *before* C1/C2 extended listening is ever
> authored, since those two levels would add another 38 scripts at the longest
> word counts in the course.

---

## What the fallback costs

Until the clips exist, `KokoroAudio.playSequence()` falls back to the browser's
`SpeechSynthesis` voice, per clip and independently. Concretely:

- **A1/A2 single-voice scripts** — acceptable. Robotic, but the content is short
  and clear and the exercise still works.
- **B1 interviews and phone-ins** — degraded. The speaker labels on the page
  still show who is talking, but every part is read in one voice.
- **B2 drama scenes** — **materially different from the authored exercise.** A
  20-turn scene between three characters, read by one undifferentiated voice,
  loses the turn-taking that carries the meaning. The comprehension questions ask
  about implication, and implication in dialogue depends on knowing who just
  spoke.

So: A1 and A2 can ship as they are. **Render before pointing B1 or B2 students at
this exercise.**

---

## Regenerating a clip after editing a script

Clip ids come from the script's **position** (level, week, index), not from a
hash of its text. So if you edit a script's wording, the id does not change and
`generate_audio.py` will **skip** the existing stale MP3.

To re-render, delete the specific clips first:

```bash
rm site/audio/b2-w15-bc*.mp3
python3 scripts/generate_audio.py
```

`--regenerate` also exists, but it re-renders **all 792 clips** including the 630
shadowing ones, which takes hours. Prefer deleting the few you changed.

> Also: the service worker (`site/sw.js`) caches `/audio/` **cache-first,
> forever**, under a manually versioned `CACHE_NAME`. A student who has already
> played a clip keeps the old bytes until that version is bumped. If you
> re-render audio that students have already heard, bump `CACHE_NAME` in
> `site/sw.js` in the same commit.

---

## Choosing different voices

Each segment names its own voice in the content file
(`content/{level}/broadcast/week*.json`, `segments[].voice`). To change one, edit
that field in **empire-nexus**, re-run `generate.py` in empire-dojo to refresh
the manifest, delete the affected MP3, and re-render.

Available voices — `python3 scripts/generate_audio.py --list-voices`:

| id | character |
|---|---|
| `af_heart` | female, warm, professional (default) |
| `af_bella` | female, clear, neutral |
| `af_nicole` | female, calm, mature |
| `af_sarah` | female, bright, energetic |
| `af_sky` | female, young, friendly |
| `am_adam` | male, professional, neutral |
| `am_michael` | male, warm, conversational |
| `bf_emma` | British female, clear, professional |
| `bf_isabella` | British female, elegant |
| `bm_george` | British male, authoritative |
| `bm_lewis` | British male, warm |

`--voice X` sets the default for clips that do **not** name one; it does **not**
override a script's own choice. All 630 shadowing clips use the default, so
`--voice` still behaves as it always did for them.
