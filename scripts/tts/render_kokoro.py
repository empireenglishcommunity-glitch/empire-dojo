#!/usr/bin/env python3
"""Render the listening-test sentences with Kokoro (native voice, af_heart).

Kokoro is the incumbent engine and the baseline the owner compares the cloned
voices against. Uses the local ONNX build (no server needed), same as
render_broadcast_local.py.

Usage: render_kokoro.py <out_dir>
Writes <out_dir>/{id}.kokoro.wav for every sentence.
"""
import json
import sys
from pathlib import Path

import soundfile as sf
from kokoro_onnx import Kokoro

HERE = Path(__file__).resolve().parent
SENTENCES = HERE.parent / "listening_test_sentences.json"
MODEL = HERE / "kokoro-v1.0.onnx"
VOICES = HERE / "voices-v1.0.bin"


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    kok = Kokoro(str(MODEL), str(VOICES))
    sents = json.loads(SENTENCES.read_text(encoding="utf-8"))["sentences"]
    for s in sents:
        try:
            samples, sr = kok.create(s["text"], voice="af_heart", speed=1.0,
                                     lang="en-us")
            sf.write(str(out / f"{s['id']}.kokoro.wav"), samples, sr)
            print(f"  kokoro OK: {s['id']}")
        except Exception as e:
            print(f"  kokoro FAIL {s['id']}: {e}")


if __name__ == "__main__":
    main()
