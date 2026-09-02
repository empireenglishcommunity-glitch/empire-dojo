#!/usr/bin/env python3.12
"""Render the extended-listening (broadcast) clips locally with kokoro-onnx.

Same model family as the Kokoro FastAPI server that generate_audio.py talks to
(Kokoro-82M), but run in-process from the ONNX build, so no container and no
localhost:8880 is needed. That is what makes the 465-clip extended-listening set
reproducible on any machine rather than only where the server happens to be up.

    python3.12 -m pip install kokoro-onnx soundfile
    python3.12 scripts/render_broadcast_local.py --model-dir /path/to/kokoro

The model directory must contain kokoro-v1.0.onnx and voices-v1.0.bin.

Reads scripts/audio-manifest.json, renders every entry whose kind ==
"broadcast" in the voice that entry names, and writes site/audio/{id}.mp3.
Existing files are skipped unless --regenerate is given.

Pace comes from scripts/audio_pace.py, which normalises delivery speed per
voice; see that module for why that is not optional.

Long texts are synthesised sentence by sentence and concatenated with a short
pause: a single very long input degrades toward the end, and real speech has
pauses at sentence boundaries, so this sounds closer to a person reading than
one continuous 100-second utterance.
"""
import argparse
import json
import pathlib
import re
import sys
import time

try:
    import numpy as np
    import soundfile as sf
    from kokoro_onnx import Kokoro
except ImportError:
    print("This script needs: python3.12 -m pip install kokoro-onnx soundfile")
    raise SystemExit(1)

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
MANIFEST = SCRIPT_DIR / "audio-manifest.json"
OUT = REPO_ROOT / "site" / "audio"

sys.path.insert(0, str(SCRIPT_DIR))
from audio_pace import (MIN_WORDS_FOR_PACE, RENDER_SPEED_FLOOR,  # noqa: E402
                        SPEED_MAX, SPEED_MIN, VOICE_WPM, pace_report,
                        speed_for_voice, split_pace, target_wpm_for)
from audio_postprocess import postprocess  # noqa: E402

# Sentence-level chunking. Matches each sentence INCLUDING any closing quote,
# the same approach generate.py uses, because Python needs fixed-width
# lookbehind so a plain split on (?<=[.!?])\s+ strands closing quotes.
SENT_RE = re.compile(r'[^.!?]*[.!?]+["\u201d\u2019\']*|[^.!?]+$')
PAUSE_SEC = 0.28          # between sentences
MAX_CHUNK_WORDS = 45      # synthesise in pieces no longer than this
FALLBACK_VOICE = "af_heart"


def sentences(text):
    out = [s.strip() for s in SENT_RE.findall(text) if s.strip()]
    return out or [text.strip()]


def chunks(text):
    """Group sentences into chunks under MAX_CHUNK_WORDS."""
    buf, n, out = [], 0, []
    for s in sentences(text):
        w = len(s.split())
        if buf and n + w > MAX_CHUNK_WORDS:
            out.append(" ".join(buf))
            buf, n = [s], w
        else:
            buf.append(s)
            n += w
    if buf:
        out.append(" ".join(buf))
    return out


def render(kokoro, text, voice, speed):
    pieces, sr = [], None
    for i, chunk in enumerate(chunks(text)):
        samples, sr = kokoro.create(chunk, voice=voice, speed=speed, lang="en-us")
        if i:
            pieces.append(np.zeros(int(sr * PAUSE_SEC), dtype=samples.dtype))
        pieces.append(samples)
    return np.concatenate(pieces), sr


def render_calibrated(kokoro, text, voice, level, tol, max_passes):
    """Render at a PHONEME-SAFE speed, calibrate the RENDERED pace, and return the
    PLAYBACK RATE that brings effective delivery to the level target.

    Why this changed (2026-09-02, single-brand-voice): the old design put the
    whole level slowdown on Kokoro's `speed`. That is safe only while the voice
    is fast enough that the needed speed stays >= RENDER_SPEED_FLOOR. With one
    brand voice (af_heart, 212 wpm) the low levels want speed 0.59-0.82, and
    below ~0.90 Kokoro corrupts her phonemes ("She is a student." -> "as she is
    a student.", ASR-confirmed). So the slowdown is SPLIT (see split_pace):

        render_speed  >= RENDER_SPEED_FLOOR   — synthesised, phoneme-safe
        playback_rate <= 1.0                  — applied by the player, pitch-
                                                corrected, does NOT touch phonemes

    effective_wpm = rendered_wpm * playback_rate, and the pair is chosen so that
    equals the level target. The calibration loop below therefore aims the
    RENDER at target/playback (the pace the file itself must have), never at a
    speed below the floor.

    The per-voice base rates in audio_pace.py are measured on one paragraph read
    in a single call; two effects make a real chunked clip slower than that
    (~13% for sentence-final prosody per chunk, plus text-dependence), so we
    still close the loop on the measured rendered pace rather than trust the
    open-loop speed. Returns the best attempt even if tolerance was never met.
    """
    render_speed, playback = split_pace(level, voice)
    target = target_wpm_for(level)
    # The file itself should read at this pace; after playback slowing it lands
    # on `target`. When playback == 1.0 this is just `target`.
    rendered_target = target / playback if playback else target
    words = len(text.split())
    # Short turns are not measurable; render once, open-loop, at the safe speed.
    if words < MIN_WORDS_FOR_PACE:
        samples, sr = render(kokoro, text, voice, render_speed)
        return dict(err=0.0, samples=samples, sr=sr, speed=render_speed,
                    playback=playback, wpm=words / ((len(samples) / sr) / 60),
                    passes=1, measurable=False)
    best = None
    speed = render_speed
    for attempt in range(1, max_passes + 1):
        samples, sr = render(kokoro, text, voice, speed)
        wpm = words / ((len(samples) / sr) / 60)
        err = abs(wpm - rendered_target) / rendered_target
        if best is None or err < best["err"]:
            best = dict(err=err, samples=samples, sr=sr, speed=speed,
                        playback=playback, wpm=wpm, passes=attempt,
                        measurable=True)
        if err <= tol:
            break
        # Correct toward the rendered_target, but NEVER synthesise below the
        # phoneme-safe floor — the remaining slowdown is already on playback.
        nxt = max(RENDER_SPEED_FLOOR,
                  min(SPEED_MAX, speed * (rendered_target / wpm)))
        if abs(nxt - speed) < 1e-4:      # at the floor/clamp: no more correction
            break
        speed = nxt
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", required=True,
                    help="directory holding kokoro-v1.0.onnx and voices-v1.0.bin")
    ap.add_argument("--only", default=None,
                    help="render only clip ids containing this substring")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--regenerate", action="store_true",
                    help="re-render clips that already exist")
    ap.add_argument("--report", action="store_true",
                    help="print the pace matrix and exit without rendering")
    ap.add_argument("--tolerance", type=float, default=0.06,
                    help="acceptable fractional deviation from the level's "
                         "target wpm (default 0.06)")
    ap.add_argument("--max-passes", type=int, default=3,
                    help="how many times to re-render a clip to hit the target "
                         "(default 3)")
    args = ap.parse_args()

    print("  Delivery pace (target wpm per level, speed per voice)")
    print(pace_report())
    if args.report:
        return 0

    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    todo = {k: v for k, v in manifest.items()
            if v.get("kind") == "broadcast" and (v.get("text") or "").strip()}
    if args.only:
        todo = {k: v for k, v in todo.items() if args.only in k}
    if not args.regenerate:
        todo = {k: v for k, v in todo.items() if not (OUT / f"{k}.mp3").exists()}
    if args.limit:
        todo = dict(list(todo.items())[:args.limit])

    total_words = sum(len(v["text"].split()) for v in todo.values())
    print(f"\n  {len(todo)} clips to render, {total_words:,} words")
    if not todo:
        print("  nothing to do")
        return 0

    model_dir = pathlib.Path(args.model_dir)
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    kokoro = Kokoro(str(model_dir / "kokoro-v1.0.onnx"),
                    str(model_dir / "voices-v1.0.bin"))
    print(f"  model loaded in {time.time() - t0:.1f}s")

    ok, failed, audio_sec, extra_passes, off = 0, [], 0.0, 0, []
    playback_rates = {}          # clip_id -> rate the player must apply
    t0 = time.time()
    for i, (clip_id, meta) in enumerate(sorted(todo.items()), 1):
        try:
            voice = meta.get("voice") or FALLBACK_VOICE
            if voice not in VOICE_WPM:
                print(f"  WARNING {clip_id}: unknown voice {voice!r}, "
                      f"using {FALLBACK_VOICE}")
                voice = FALLBACK_VOICE
            r = render_calibrated(kokoro, meta["text"], voice,
                                  meta.get("level"), args.tolerance,
                                  args.max_passes)
            # Peak-normalise + trim only at WRITE time, after pace calibration
            # has measured duration on the raw samples — so loudness is fixed
            # without disturbing the wpm the calibration loop converged on. The
            # outer-edge trim is a fraction of a second on a multi-second clip,
            # well inside the pace tolerance the verify pass below enforces.
            out_samples = postprocess(r["samples"], r["sr"])
            sf.write(str(OUT / f"{clip_id}.mp3"), out_samples, r["sr"],
                     format="MP3")
            # Record the playback rate this clip must be played at to hit its
            # level's target pace. 1.0 means "play as rendered". The site
            # generator reads this and passes it to KokoroAudio.play(id, text,
            # rate); see audio_pace.split_pace and app.js.
            playback_rates[clip_id] = r.get("playback", 1.0)
            audio_sec += len(r["samples"]) / r["sr"]
            extra_passes += r["passes"] - 1
            ok += 1
            # Effective pace = rendered wpm * playback; the loop calibrated the
            # rendered wpm against target/playback, so compare err on that basis.
            if r.get("measurable", True) and r["err"] > args.tolerance:
                off.append((clip_id, round(r["wpm"] * r.get("playback", 1.0)),
                            target_wpm_for(meta.get("level")), r["speed"]))
            if i % 25 == 0 or i == len(todo):
                el = time.time() - t0
                print(f"  [{i}/{len(todo)}] {clip_id} · {audio_sec/60:.1f} min audio "
                      f"in {el/60:.1f} min ({audio_sec/max(el,1):.1f}x realtime, "
                      f"{extra_passes} corrections)", flush=True)
        except Exception as e:                                  # noqa: BLE001
            print(f"  FAILED {clip_id}: {type(e).__name__}: {e}", flush=True)
            failed.append(clip_id)

    print(f"\n  rendered {ok}, failed {len(failed)}, "
          f"{extra_passes} pace corrections")
    print(f"  {audio_sec/60:.1f} minutes of audio in {(time.time()-t0)/60:.1f} minutes")
    if off:
        print(f"\n  {len(off)} clip(s) Kokoro could not bring within "
              f"{args.tolerance:.0%} of target:")
        for cid, got, want, sp in sorted(off, key=lambda x: x[1]):
            print(f"    {cid:<16}{got:>4} wpm (target {want}, speed {sp:.2f})")
    if failed:
        print(f"  failures: {failed}")
        return 1

    # Verify the pace actually landed. This is the whole point of the module, so
    # measure the result rather than trusting the setting.
    print("\n  Measured pace by level:")
    words, secs, counts, measured, slow = {}, {}, {}, {}, []
    for clip_id, meta in todo.items():
        p = OUT / f"{clip_id}.mp3"
        try:
            dur = sf.info(str(p)).duration
        except Exception:                                       # noqa: BLE001
            continue
        lvl = (meta.get("level") or "?").lower()
        w = len(meta["text"].split())
        counts[lvl] = counts.get(lvl, 0) + 1
        # Aggregate over measurable turns only. Including one-word turns drags
        # the level average down by an amount that reflects how much dialogue a
        # level happens to contain, not how fast it is spoken.
        if w < MIN_WORDS_FOR_PACE:
            continue
        words[lvl] = words.get(lvl, 0) + w
        # Effective seconds the student hears = rendered duration / playback
        # (playback < 1.0 makes the clip take LONGER to play). This keeps the
        # per-level summary honest about delivered pace.
        pb = playback_rates.get(clip_id, 1.0)
        secs[lvl] = secs.get(lvl, 0.0) + (dur / pb if pb else dur)
        measured[lvl] = measured.get(lvl, 0) + 1
        if w >= 60 and dur > 0:
            # EFFECTIVE pace is what the student hears: rendered wpm * playback.
            # The file is rendered fast and slowed at playback, so measuring the
            # bare file would wrongly flag every low-level clip as too fast.
            pb = playback_rates.get(clip_id, 1.0)
            wpm = (w / (dur / 60)) * pb
            if abs(wpm - target_wpm_for(lvl)) / target_wpm_for(lvl) > 0.20:
                slow.append((clip_id, w, round(wpm), target_wpm_for(lvl)))
    # accumulate effective seconds per level so the summary reflects playback too
    print(f"  (effective pace = rendered x playback; over turns of >= "
          f"{MIN_WORDS_FOR_PACE} words; shorter turns are not measurable)")
    print(f"  {'lvl':<5}{'clips':>6}{'measured':>9}{'words':>8}{'min':>8}"
          f"{'wpm':>6}{'target':>8}")
    for lvl in sorted(counts):
        if not secs.get(lvl):
            print(f"  {lvl:<5}{counts[lvl]:>6}{0:>9}{0:>8}{0:>8.1f}"
                  f"{'-':>6}{target_wpm_for(lvl):>8}")
            continue
        got = words[lvl] / (secs[lvl] / 60)
        print(f"  {lvl:<5}{counts[lvl]:>6}{measured.get(lvl, 0):>9}{words[lvl]:>8}"
              f"{secs[lvl]/60:>8.1f}{got:>6.0f}{target_wpm_for(lvl):>8}")
    if slow:
        print(f"\n  {len(slow)} clip(s) more than 20% off their level target:")
        for cid, w, got, want in sorted(slow, key=lambda x: x[2])[:20]:
            print(f"    {cid:<16}{w:>4}w  {got:>4} wpm (target {want})")

    # Persist each clip's playback rate back into the manifest so the site
    # generator can pass it to the player. Only write when something changed, to
    # keep the diff minimal, and only touch clips we actually rendered this run.
    if playback_rates:
        with open(MANIFEST, encoding="utf-8") as f:
            full = json.load(f)
        changed = 0
        for cid, rate in playback_rates.items():
            if cid in full:
                r = round(float(rate), 4)
                # Store only when it differs from the default 1.0, and record it
                # as a number the generator/player can read directly.
                if full[cid].get("playback_rate") != r:
                    if r == 1.0:
                        full[cid].pop("playback_rate", None)
                    else:
                        full[cid]["playback_rate"] = r
                    changed += 1
        if changed:
            with open(MANIFEST, "w", encoding="utf-8") as f:
                json.dump(full, f, ensure_ascii=False, indent=2)
                f.write("\n")
            print(f"\n  wrote playback_rate for {changed} clip(s) -> "
                  f"{MANIFEST.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
