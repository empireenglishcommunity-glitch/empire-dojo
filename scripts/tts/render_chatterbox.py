#!/usr/bin/env python3
"""Render the listening-test sentences with Chatterbox (Resemble AI, MIT),
cloning the owner's voice from the reference WAV.

Chatterbox needs no reference transcript — just the audio prompt.

Usage: render_chatterbox.py <ref_wav> <out_dir>
Writes <out_dir>/{id}.chatterbox.wav for every sentence.
"""
import json
import sys
from pathlib import Path

import torchaudio
from chatterbox.tts import ChatterboxTTS

HERE = Path(__file__).resolve().parent
SENTENCES = HERE.parent / "listening_test_sentences.json"


def main():
    ref, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    model = ChatterboxTTS.from_pretrained(device="cpu")
    sents = json.loads(SENTENCES.read_text(encoding="utf-8"))["sentences"]
    for s in sents:
        try:
            wav = model.generate(s["text"], audio_prompt_path=ref)
            torchaudio.save(str(out / f"{s['id']}.chatterbox.wav"), wav, model.sr)
            print(f"  chatterbox OK: {s['id']}")
        except Exception as e:
            print(f"  chatterbox FAIL {s['id']}: {e}")


if __name__ == "__main__":
    main()
