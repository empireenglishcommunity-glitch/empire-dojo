#!/usr/bin/env python3
"""Rank every American Kokoro voice by how CLEARLY it speaks.

WHY
---
The cast in voice_cast.json was chosen from the voice descriptions in
generate_audio.py ("warm, conversational", "clear, neutral") — i.e. from
adjectives, not from evidence. A student then reported that the grammar voice
was "annoying" and "his accent not clear", which is not something a description
can settle.

Kokoro ships 9 American male and 11 American female voices; the cast used 2 and
5. This measures all 20 on the same sentences so the choice can be made on
numbers, and re-measured whenever the model changes.

WHAT IT MEASURES
----------------
  exact      share of sentences an ASR transcribes back word-for-word. The
             blunt one: if a machine cannot recover the words, a learner
             listening in a second language has less chance.
  wer        mean word error rate over the same sentences.
  conf       mean ASR confidence (avg_logprob). Closer to 0 is better. This is
             the closest available proxy for "clear" as opposed to "correct" —
             a voice can be transcribed right while still sounding mumbled, and
             this is what separates them.
  wpm        speaking rate at speed 1.0, for reference only. Everything is
             rendered at 1.0 because slowing Kokoro corrupts phonemes.

⚠️ TWO LIMITS OF THIS SCRIPT, both found the hard way on 2026-09-01.

1. IT MEASURES SENTENCES ONLY. SENTENCES below is prose and four-word sentences,
   and the comment there says as much. But 59.4% of the site's 9,360 spoken clips
   are 1-2 WORDS, and the listening surface is 86.8% single words. A voice can be
   strong on prose and poor on isolated words: am_michael ranks 6th of 9 on
   sentences yet 93.1% on words, while am_eric is 3rd on sentences and LAST on
   words (66.7%). Choosing a listening voice from this script's output picked the
   worst available voice for that surface, and a student reported it.
   Pass a word list when the surface is words.

2. IT MUST RENDER THROUGH THE PRODUCTION PATH. render_speech.py imports
   `kokoro_onnx` directly; the VPS also runs a kokoro-fastapi HTTP server on
   8880. They are the same model behind different code and their output differs
   measurably (for one clip: rms 0.110 vs 0.073, duration 0.53s vs 0.55s, and a
   different ASR result). Benchmarking through the HTTP server ranks voices on
   audio no student ever hears. Use --model-dir with kokoro_onnx, as this script
   already does, and never substitute the server for convenience.

ASR is a proxy, not a verdict on beauty. It answers "can the words be recovered
from this voice", which is the part that matters for a listener learning the
language, and it does so consistently across voices.

Usage:
    benchmark_voices.py --model-dir _kok
    benchmark_voices.py --model-dir _kok --gender male --asr small
"""
import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# Deliberately weighted to what students actually hear: the A1 grammar patterns
# Mai was listening to, plus longer prose so a voice cannot win by only doing
# well on four-word sentences.
SENTENCES = [
    "She is a student.",
    "I am from Egypt.",
    "He is not here.",
    "They are my friends.",
    "Are you a teacher?",
    "It is the biggest city.",
    "My brother works in a hospital near the market.",
    "Yesterday I walked to the library and borrowed two books.",
    "The meeting has been postponed until the end of the month.",
    "Although it was raining, she decided to walk home alone.",
]


def wer(ref: str, hyp: str) -> float:
    """Word error rate by Levenshtein distance over words."""
    r, h = ref.split(), hyp.split()
    if not r:
        return 0.0
    d = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1):
        d[i][0] = i
    for j in range(len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                          d[i - 1][j - 1] + (r[i - 1] != h[j - 1]))
    return d[len(r)][len(h)] / len(r)


def norm(s: str) -> str:
    s = s.lower().replace("’", "'")
    s = re.sub(r"[^a-z0-9' ]", " ", s)
    return " ".join(s.split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default="_kok")
    ap.add_argument("--gender", choices=["male", "female", "both"], default="both")
    ap.add_argument("--asr", default="small")
    ap.add_argument("--json", default="_audit/voice_benchmark.json")
    args = ap.parse_args()

    import soundfile as sf
    from faster_whisper import WhisperModel
    from kokoro_onnx import Kokoro

    md = Path(args.model_dir)
    kok = Kokoro(str(md / "kokoro-v1.0.onnx"), str(md / "voices-v1.0.bin"))
    asr = WhisperModel(args.asr, device="cpu", compute_type="int8")

    voices = sorted(v for v in kok.get_voices()
                    if (args.gender in ("both", "male") and v.startswith("am_"))
                    or (args.gender in ("both", "female") and v.startswith("af_")))
    print(f"  {len(voices)} voice(s) x {len(SENTENCES)} sentences, rendered at speed 1.0")
    print()

    rows = []
    tmp = Path("_audit/_bench.wav")
    tmp.parent.mkdir(exist_ok=True)
    for v in voices:
        exact = 0
        wers, confs, secs, words = [], [], 0.0, 0
        for s in SENTENCES:
            x, sr = kok.create(s, voice=v, speed=1.0, lang="en-us")
            sf.write(str(tmp), x, sr)
            segs, _info = asr.transcribe(str(tmp), language="en", beam_size=5)
            segs = list(segs)
            heard = " ".join(g.text.strip() for g in segs).strip()
            if segs:
                confs.append(sum(g.avg_logprob for g in segs) / len(segs))
            if norm(heard) == norm(s):
                exact += 1
            wers.append(wer(norm(s), norm(heard)))
            secs += len(x) / sr
            words += len(s.split())
        rows.append({
            "voice": v,
            "exact": exact / len(SENTENCES),
            "wer": sum(wers) / len(wers),
            "conf": (sum(confs) / len(confs)) if confs else -9.9,
            "wpm": words / (secs / 60),
        })
        r = rows[-1]
        print(f"  {v:<12} exact {r['exact']*100:>5.0f}%   wer {r['wer']:>5.2f}   "
              f"conf {r['conf']:>6.2f}   {r['wpm']:>4.0f} wpm")

    # Rank: recoverable words first, then confidence.
    rows.sort(key=lambda r: (-r["exact"], r["wer"], -r["conf"]))
    print()
    print("  === ranked (best first) ===")
    print(f"  {'#':<4}{'voice':<12}{'exact':>7}{'wer':>7}{'conf':>8}{'wpm':>6}")
    for i, r in enumerate(rows, 1):
        print(f"  {i:<4}{r['voice']:<12}{r['exact']*100:>6.0f}%{r['wer']:>7.2f}"
              f"{r['conf']:>8.2f}{r['wpm']:>6.0f}")
    Path(args.json).write_text(json.dumps(rows, indent=1))
    print(f"\n  -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
