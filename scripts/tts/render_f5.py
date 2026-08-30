#!/usr/bin/env python3
"""Render the listening-test sentences with F5-TTS (MIT), cloning the owner's
voice — loading the model ONCE.

The earlier version shelled out to `f5-tts_infer-cli` per sentence, which
reloaded the 1.4 GB model and re-transcribed the reference on every call — ~20x
the necessary work, and unusable for the 4,875-clip mass render. This uses the
Python API: transcribe the (short) reference once with faster-whisper, load the
model once, then infer all sentences.

Usage: render_f5.py <ref_wav> <out_dir> [ref_text]
Writes <out_dir>/{id}.f5.wav for every sentence.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SENTENCES = HERE.parent / "listening_test_sentences.json"


def main():
    ref = sys.argv[1]
    out = Path(sys.argv[2])
    ref_text = sys.argv[3] if len(sys.argv) > 3 else ""
    out.mkdir(parents=True, exist_ok=True)
    sents = json.loads(SENTENCES.read_text(encoding="utf-8"))["sentences"]

    # Transcribe the reference ONCE. F5 needs the reference transcript; passing
    # it explicitly stops the API re-transcribing on every call.
    if not ref_text:
        try:
            from faster_whisper import WhisperModel
            wm = WhisperModel("base", device="cpu", compute_type="int8")
            segs, _ = wm.transcribe(ref)
            ref_text = " ".join(s.text for s in segs).strip()
            print(f"  reference transcript ({len(ref_text)} chars): "
                  f"{ref_text[:120]}...")
        except Exception as e:
            print(f"  whisper transcribe failed ({e}); F5 will auto-transcribe")
            ref_text = ""

    from f5_tts.api import F5TTS
    f5 = F5TTS()  # loads the model once
    print("  F5 model loaded")

    for s in sents:
        dest = out / f"{s['id']}.f5.wav"
        try:
            f5.infer(ref_file=ref, ref_text=ref_text, gen_text=s["text"],
                     file_wave=str(dest))
            if dest.exists() and dest.stat().st_size > 1000:
                print(f"  f5 OK: {s['id']}")
            else:
                print(f"  f5 FAIL {s['id']}: no/empty output")
        except Exception as e:
            print(f"  f5 FAIL {s['id']}: {e}")


if __name__ == "__main__":
    main()
