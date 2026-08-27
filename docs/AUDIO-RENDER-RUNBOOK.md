# Audio render runbook

**Status: all 162 extended-listening clips are rendered and committed.**
`site/audio/` holds 792 MP3s — 630 shadowing + 162 extended listening — and
nothing in the manifest is missing. This document is now (a) the record of how
they were made and why the pace was chosen, and (b) the procedure for
re-rendering after a script edit or authoring a new level.

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

### B. Local `kokoro-onnx`, no server (how these 162 were actually made)

The build environment has no Kokoro container, so the clips were rendered
in-process from the ONNX build of the same model (Kokoro-82M):

```bash
pip install kokoro-onnx soundfile
mkdir -p kokoro && cd kokoro
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx   # 311 MB
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin     # 27 MB
```

Then a short script reads the manifest and writes `site/audio/{id}.mp3`. It ran
at **3.4× real time** on CPU: 57.8 minutes of audio in 17 minutes. `libsndfile
1.2.2` writes MP3 directly, so no ffmpeg is needed.

Useful to know because it means **no server is required to fix audio** — any
machine with Python and 340 MB of disk can do it.

---

## Pace is set per level, and this is not cosmetic

Kokoro at `speed=1.0` delivers **190–200 wpm**, which is *fast native pace*. The
first render pass came out at A1 202, A2 190, B1 191, B2 186 wpm — and that
**invalidates the exercise** rather than merely making it harder:

- `A1.R.1` — *"…when people **speak slowly and clearly**"*
- `A2.R.2` — *"short, **clear**, simple messages and announcements"*
- `B1.R.2` — *"…when delivered **relatively slowly and clearly**"*

A beginner given 200 wpm fails on delivery speed alone, whatever their
comprehension. So:

| level | `speed` | measured median | descriptor asks for |
|---|---|---|---|
| A1 | 0.65 | **128 wpm** | slowly and clearly |
| A2 | 0.72 | **134 wpm** | short, clear, simple |
| B1 | 0.80 | **152 wpm** | relatively slowly and clearly |
| B2 | 0.90 | **173 wpm** | normal clear broadcast / lecture |
| C1 / C2 | 1.00 | — | native speed, which is the point at those levels |

Reference: careful speech ~120–130 wpm, normal conversation ~150–160, fast
native 200+. The page's speed selector (Slow / Careful / Normal) still lets a
student slow it further from there.

`SPEED_BY_LEVEL` lives in `scripts/generate_audio.py`, so both render paths agree.
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
| **total** | **52** | **162** | | **57.8 min, 25 MB** |

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
