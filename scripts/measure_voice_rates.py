#!/usr/bin/env python3.12
"""Measure the intrinsic speaking rate of each Kokoro voice, in words per minute.

These numbers are properties of the MODEL, not of our content, and they are the
input to the per-voice pace correction in scripts/audio_pace.py. Re-run this if
the Kokoro model version changes, then paste the table into VOICE_WPM there.

Why it exists: at a fixed speed=1.0 the eleven voices do not speak at the same
rate. The spread measured on Kokoro v1.0 is 1.84x (af_nicole 130 wpm, bf_emma
238 wpm). Before this was known, pace was set per level only, so the delivery
speed of a clip was decided by whichever voice its script happened to name --
and several C1/C2 clips shipped at or below the A1 target on descriptors whose
entire content is delivery speed.

Runs against a local kokoro-onnx build so it needs no server:

    python3.12 -m pip install kokoro-onnx soundfile
    python3.12 scripts/measure_voice_rates.py --model-dir /path/to/kokoro

The directory must contain kokoro-v1.0.onnx and voices-v1.0.bin.
"""
import argparse
import json
import pathlib
import sys
import tempfile

try:
    import soundfile as sf
    from kokoro_onnx import Kokoro
except ImportError:
    print("This script needs: python3.12 -m pip install kokoro-onnx soundfile")
    raise SystemExit(1)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from audio_pace import VOICE_WPM  # noqa: E402

# Deliberately ordinary prose: mixed sentence lengths, one contraction, one
# subordinate clause, no dashes or ellipses -- nothing that would bias one voice
# over another. Do not change it without re-measuring every voice, or the
# numbers stop being comparable to the ones recorded in audio_pace.py.
REFERENCE = (
    "The meeting was moved to Thursday because the room had already been "
    "booked. I told them I would bring the figures with me, and I did. "
    "Nobody had read the appendix, which was the only part that mattered. "
    "We agreed to look at it again in the spring, and then we went home."
)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", required=True,
                    help="directory holding kokoro-v1.0.onnx and voices-v1.0.bin")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON suitable for pasting into audio_pace.py")
    args = ap.parse_args()

    model_dir = pathlib.Path(args.model_dir)
    kokoro = Kokoro(str(model_dir / "kokoro-v1.0.onnx"),
                    str(model_dir / "voices-v1.0.bin"))
    words = len(REFERENCE.split())
    measured = {}
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="voice-rates-"))

    print(f"  reference: {words} words\n")
    print(f"  {'voice':<14}{'sec':>7}{'wpm':>7}{'recorded':>10}{'drift':>8}")
    for voice in sorted(VOICE_WPM):
        samples, sr = kokoro.create(REFERENCE, voice=voice, speed=1.0,
                                    lang="en-us")
        p = scratch / f"{voice}.mp3"
        sf.write(str(p), samples, sr, format="MP3")
        dur = sf.info(str(p)).duration
        wpm = words / (dur / 60)
        measured[voice] = round(wpm, 1)
        old = VOICE_WPM[voice]
        print(f"  {voice:<14}{dur:>7.1f}{wpm:>7.0f}{old:>10.0f}"
              f"{(wpm - old) / old * 100:>7.0f}%")

    lo, hi = min(measured.values()), max(measured.values())
    print(f"\n  slowest {lo:.0f}, fastest {hi:.0f} — spread {hi / lo:.2f}x")
    drift = {v: measured[v] for v in measured
             if abs(measured[v] - VOICE_WPM[v]) / VOICE_WPM[v] > 0.05}
    if drift:
        print("\n  WARNING: these voices drifted >5% from the recorded rates in")
        print("  audio_pace.py. Update VOICE_WPM and re-render broadcast audio:")
        for v, w in sorted(drift.items()):
            print(f"    {v}: {VOICE_WPM[v]} -> {w}")
    else:
        print("\n  All voices within 5% of the rates recorded in audio_pace.py.")
    if args.json:
        print()
        print(json.dumps(measured, indent=4, sort_keys=True))
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
