# Audio render runbook

**Status: all 465 extended-listening clips are rendered and committed, for all
six levels.** `site/audio/` holds 1,095 MP3s — 630 shadowing + 465 extended
listening — and nothing in the manifest is missing. This document is (a) the
record of how they were made and why the pace was chosen, and (b) the procedure
for re-rendering after a script edit or authoring a new level.

Pace is verified against the descriptors by a separate checker:

```bash
python3.12 scripts/verify_audio_pace.py     # exit 1 if any level drifts
```

---

## Two ways to render

### A. Kokoro FastAPI server (the project's normal path)

```bash
cd empire-dojo
python3 scripts/generate_audio.py
```

Needs Kokoro reachable — `curl http://localhost:8880/health`, or set
`KOKORO_URL`. To start it: `cd /opt/kokoro-tts && docker compose up -d`.

It skips clips that already exist, honours each clip's own `voice`, applies the
per-level pace below, and **exits non-zero listing anything it failed to
produce**.

### B. Local `kokoro-onnx`, no server (how these 465 were actually made)

The build environment has no Kokoro container, so the clips were rendered
in-process from the ONNX build of the same model (Kokoro-82M):

```bash
pip install kokoro-onnx soundfile
mkdir -p kokoro && cd kokoro
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx   # 311 MB
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin     # 27 MB
```

Then, from the repo:

```bash
python3.12 scripts/render_broadcast_local.py --model-dir ./kokoro
python3.12 scripts/render_broadcast_local.py --model-dir ./kokoro --report   # pace matrix only
python3.12 scripts/render_broadcast_local.py --model-dir ./kokoro --only c2- --regenerate
```

It reads the manifest and writes `site/audio/{id}.mp3`, skipping what already
exists unless `--regenerate` is given. `--only` takes a substring of the clip id,
which is also how to render one level at a time. `libsndfile 1.2.2` writes MP3
directly, so no ffmpeg is needed.

Throughput on CPU is **~2× real time** with pace correction enabled (it was 3.9×
open-loop; the difference is the re-renders needed to hit each level's target).
The full 465-clip set is ~109 minutes of audio in roughly 60 minutes of compute,
so render **one level per invocation** if your shell has a command timeout.

Useful to know because it means **no server is required to fix audio** — any
machine with Python and 340 MB of disk can do it.

---

## Pace is set per level AND per voice, and this is not cosmetic

Several reception descriptors are claims about **delivery speed**, not only about
comprehension:

- `A1.R.1` — *"…when people **speak slowly and clearly**"*
- `A2.R.2` — *"short, **clear**, simple messages and announcements"*
- `B1.R.2` — *"…when delivered **relatively slowly and clearly**"*
- `C1.R.1` — extended speech at native delivery
- `C2.R.1` — *"…delivered at **fast native speed**"*

A beginner given 200 wpm fails on delivery speed alone whatever their
comprehension; a C2 clip delivered at 120 wpm means the programme is claiming
"fast native speed" over audio slower than its own beginner target. Both
directions matter.

### The mistake this replaced

The first version of this set **one `speed` per level**. That assumed all eleven
Kokoro voices speak at the same rate at `speed=1.0`. They do not — measured on a
fixed 53-word reference paragraph there is a **1.84× spread**:

| voice | wpm @1.0 | | voice | wpm @1.0 |
|---|---|---|---|---|
| `af_nicole` | **130** | | `af_sarah` | 222 |
| `am_michael` | 193 | | `am_adam` | 228 |
| `bm_george` | 198 | | `af_sky` | 230 |
| `bm_lewis` | 204 | | `bf_isabella` | 236 |
| `af_bella` | 209 | | `bf_emma` | 238 |
| `af_heart` | 212 | | | |

`af_nicole` is a severe outlier. The consequences were in the shipped audio:

- delivery pace was decided by whichever voice a script happened to name;
- inside one multi-voice scene, one speaker ran at 120 wpm and another at 210 —
  which no real panel or argument sounds like;
- six C1/C2 clips shipped at **120–142 wpm**, at or below the A1 target, on the
  two descriptors whose entire content is delivery speed.

Two other hypotheses were tested and **rejected** first: inter-sentence pause
length (raising speed and cutting the pause moved the worst clip only 120 → 141
wpm) and punctuation such as em-dashes and ellipses (normalising it changed
122 → 120 wpm).

### How it works now

Pace is expressed as a **target wpm per level** — the thing the descriptors
actually talk about — and the per-clip `speed` is derived from the measured rate
of the voice that clip names:

```
speed = target_wpm[level] / VOICE_WPM[voice]
```

Kokoro's `speed` parameter was verified linear over 0.55–1.60 (measured ratio
0.97–1.09, no clipping), so the correction is valid.

Two further effects make a real clip slower than those rates predict: **chunked
synthesis costs ~13%** (each chunk is spoken with sentence-final prosody, so
joining N chunks is longer than one N-length utterance), and a voice's rate is
**not text-independent** (`bm_george` reads a numeral-heavy news bulletin ~11%
slower than the reference prose). Open-loop that left C1 at 172 wpm against a
195 target. So `render_broadcast_local.py` **closes the loop**: it measures each
rendered clip and rescales the speed by `target/actual`, up to `--max-passes`
times. Almost every clip converges in one correction.

Measured result, verified independently by `scripts/verify_audio_pace.py`:

| level | target | measured | descriptor asks for |
|---|---|---|---|
| A1 | 125 | **124** | slowly and clearly |
| A2 | 135 | **135** | short, clear, simple |
| B1 | 155 | **155** | relatively slowly and clearly |
| B2 | 175 | **175** | normal clear broadcast / lecture |
| C1 | 195 | **189** | native |
| C2 | 205 | **199** | fast native speed |

Reference: careful speech ~120–130 wpm, normal conversation ~150–160, fast
native 200+. The page's speed selector (Slow / Careful / Normal) still lets a
student slow it further from there.

**Turns under 25 words are not paced.** Words-per-minute is meaningless for a
one-word turn (`"And?"`, `"Baba—"`) — it is mostly onset and decay, so it reads
as ~100 wpm however fast it is spoken. Closing the loop on those numbers drove
such clips to maximum speed and made short emotional lines sound rushed, the
opposite of the intended fix. They render open-loop and are excluded from the
aggregates (`MIN_WORDS_FOR_PACE`).

The numbers live in **`scripts/audio_pace.py`**, shared by both render paths.
Re-measure with `scripts/measure_voice_rates.py` if the Kokoro model version
changes — the rates are properties of the model, not of our content.
**Shadowing clips are untouched** — they carry no level-scoped pace requirement
and stay at the default.

---

## What is in there

| level | scripts | clips | words per clip | audio |
|---|---|---|---|---|
| A1 | 10 | 10 | 62–76 | slow, single voice |
| A2 | 12 | 15 | 15–159 | mostly single voice |
| B1 | 14 | 29 | 4–181 | phone-ins, interviews |
| B2 | 16 | 108 | 1–256 | five long drama scenes |
| C1 | 18 | 121 | 1–300 | unsignposted monologues, idiom-heavy scenes |
| C2 | 20 | 182 | 1–427 | panel with overlap, auction, commentary, eulogy |
| **total** | **90** | **465** | | **109 min measurable, 206 MB** |

Clip ids are `{level}-w{week}-bc{index}` — no day component, because extended
listening is **weekly**: all seven days share the same clips.

**Very short clips are expected.** The drama scenes contain real one-word turns
(*"And?"*, *"It's off."*, *"I know."*) which are separate clips because they are
separate speakers. A 4 KB MP3 in the B2 set is correct.

---

## Verifying

```bash
# every manifest entry has a real file
python3 scripts/generate_audio.py ; echo "exit=$?"      # non-zero if any missing

ls site/audio/*-bc*.mp3 | wc -l                          # expect 162
find site/audio -name '*-bc*.mp3' -size 0                # expect nothing
```

Pace check — the one that actually matters after a re-render:

```python
import json, soundfile as sf, statistics, collections
m = json.load(open('scripts/audio-manifest.json'))
per = collections.defaultdict(list)
for k, v in m.items():
    if v.get('kind') != 'broadcast':
        continue
    i = sf.info(f"site/audio/{k}.mp3")
    w = len(v['text'].split())
    if i.duration > 1.5 and w >= 8:          # short interjections skew the median
        per[v['level']].append(w / (i.duration / 60))
for lvl in ('a1', 'a2', 'b1', 'b2'):
    print(lvl, round(statistics.median(per[lvl])), 'wpm')
# expect roughly a1 128 · a2 134 · b1 152 · b2 173
```

Then listen to three before trusting a batch — a beginner script, a news
bulletin, and three consecutive turns of a scene (they should sound like
different people):

```
site/audio/a1-w1-bc0.mp3
site/audio/b2-w9-bc0.mp3
site/audio/b2-w15-bc0.mp3   then bc1, bc2
```

---

## Re-rendering after a script edit

Clip ids come from **position** (level, week, index), **not** from a hash of the
text. So editing a script does **not** change the id, and both renderers will
**skip** the now-stale MP3.

```bash
rm site/audio/b2-w15-bc*.mp3
python3 scripts/generate_audio.py
```

`--regenerate` also exists but re-renders **all 792** clips including the 630
shadowing ones — hours, to fix one line.

> **And bump the service worker.** `site/sw.js` caches `/audio/` **cache-first,
> forever**, under a manually versioned `CACHE_NAME`. A student who has already
> played a clip keeps the old bytes until it changes. If you re-render audio
> students may have heard, bump `CACHE_NAME` in the same commit.

---

## Changing a voice

Each segment names its voice in `content/{level}/broadcast/week*.json`
(`segments[].voice`) in **empire-nexus**. Edit it there, re-run `generate.py` in
empire-dojo to refresh the manifest, delete the affected MP3, re-render.

`--voice X` sets the default for clips that do **not** name one; it does **not**
override a script's own choice.

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

---

## Size, and the decision to make before C1/C2

`site/audio/` is now **176 MB** across 792 files, all committed to git. The 162
new clips added **25 MB**.

C1 and C2 extended listening, if authored, would add **38 more scripts at the
longest word counts in the course** — plausibly another 40–60 MB, and C1/C2
render at full speed so they are shorter per word but there are more words.
**Decide on Git LFS or an external bucket before authoring them**, not after.
