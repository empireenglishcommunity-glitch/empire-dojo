#!/usr/bin/env python3
"""Render the listening-test sentences with F5-TTS (MIT), cloning the owner's
voice from the reference WAV.

F5 needs the reference transcript. If none is supplied it auto-transcribes the
reference with Whisper (bundled), which is fine for a clone reference.

Usage: render_f5.py <ref_wav> <out_dir> [ref_text]
Writes <out_dir>/{id}.f5.wav for every sentence.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SENTENCES = HERE.parent / "listening_test_sentences.json"


def main():
    ref = sys.argv[1]
    out = Path(sys.argv[2])
    ref_text = sys.argv[3] if len(sys.argv) > 3 else ""
    out.mkdir(parents=True, exist_ok=True)
    sents = json.loads(SENTENCES.read_text(encoding="utf-8"))["sentences"]

    for s in sents:
        tmp = Path(tempfile.mkdtemp())
        # F5-TTS ships a CLI. --ref_text "" triggers built-in ASR on the ref.
        cmd = [
            "f5-tts_infer-cli",
            "--model", "F5TTS_v1_Base",
            "--ref_audio", ref,
            "--ref_text", ref_text,
            "--gen_text", s["text"],
            "--output_dir", str(tmp),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                print(f"  f5 FAIL {s['id']}: rc={r.returncode} "
                      f"{r.stderr.strip()[-200:]}")
                continue
            # Output filename varies across versions; take the newest wav.
            wavs = sorted(tmp.rglob("*.wav"), key=lambda p: p.stat().st_mtime)
            if not wavs:
                print(f"  f5 FAIL {s['id']}: no wav produced")
                continue
            dest = out / f"{s['id']}.f5.wav"
            dest.write_bytes(wavs[-1].read_bytes())
            print(f"  f5 OK: {s['id']}")
        except subprocess.TimeoutExpired:
            print(f"  f5 FAIL {s['id']}: timeout")
        except Exception as e:
            print(f"  f5 FAIL {s['id']}: {e}")


if __name__ == "__main__":
    main()
