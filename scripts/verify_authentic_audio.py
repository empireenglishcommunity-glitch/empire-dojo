#!/usr/bin/env python3.12
"""Verify the authentic (human-recorded) scene audio behind the film reservations.

WHY THIS EXISTS
===============
Two CEFR descriptors name FILMS — `B2.R.2` ("the majority of films in standard
dialect") and `C1.R.2` ("follow films employing a considerable degree of slang").
Kokoro TTS delivers the words, the slang and the ellipsis, but not what a real
actor does with a line: no overlapping speech, no regional accent, no emotional
prosody. Both descriptors therefore carry a stated reservation in the coverage
ledger.

The debt is paid by recording the eleven drama scenes with real voices. Closure is
declarative: record the scene, add its id to
`empire-nexus/bots/discord-learning-bot/content/cefr/authentic_audio.json`, and
the ledger drops that reservation automatically.

Nothing can automatically prove a recording features human actors. What this
script DOES prove is the realistic failure mode: a scene declared authentic whose
file was never actually replaced.

    python3.12 scripts/verify_authentic_audio.py

Checks, for every scene listed as authentic:
  1. `site/audio/{scene}-scene.mp3` exists;
  2. it is not implausibly small (a truncated or silent upload);
  3. it is NOT byte-identical to any of our own TTS renders for that scene
     (`scripts/tts-audio-baseline.json`) — i.e. a TTS clip renamed, not replaced.

Exit 0 = every declared scene holds up. Exit 1 = a declaration is not backed by a
real file, which means the ledger is about to drop a reservation it should keep.
"""
import argparse
import hashlib
import json
import os
import pathlib
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
AUDIO_DIR = REPO_ROOT / "site" / "audio"
BASELINE = SCRIPT_DIR / "tts-audio-baseline.json"

# empire-nexus is a sibling checkout unless told otherwise (same convention as
# generate.py, whose env var name is kept for compatibility).
NEXUS = pathlib.Path(os.environ.get("EEC_REPO_DIR", REPO_ROOT.parent / "empire-nexus"))
MANIFEST = (NEXUS / "bots" / "discord-learning-bot" / "content" / "cefr"
            / "authentic_audio.json")

# A real recorded scene is ~1-3 minutes of speech. Anything under this is a
# truncated upload, a silent file, or a placeholder.
MIN_BYTES = 40_000


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(MANIFEST),
                    help="path to authentic_audio.json")
    args = ap.parse_args()

    manifest_path = pathlib.Path(args.manifest)
    if not manifest_path.exists():
        print(f"  manifest not found: {manifest_path}")
        print("  (nothing declared authentic — reservations stay open, which is fine)")
        return 0
    try:
        declared = [str(s).strip().lower()
                    for s in (json.loads(manifest_path.read_text(encoding="utf-8"))
                              .get("scenes") or []) if s]
    except ValueError as e:
        print(f"  MANIFEST IS NOT VALID JSON: {e}")
        print("  The ledger treats an unreadable manifest as 'nothing authentic',")
        print("  so reservations stay open — but fix this, it is silently inert.")
        return 1

    if not declared:
        print("  No scenes declared authentic yet.")
        print("  Both film reservations (B2.R.2, C1.R.2) remain open — correctly so.")
        return 0

    baseline = {}
    if BASELINE.exists():
        baseline = json.loads(BASELINE.read_text(encoding="utf-8")).get("scenes") or {}

    print(f"  {len(declared)} scene(s) declared authentic\n")
    failures = []
    for scene in declared:
        path = AUDIO_DIR / f"{scene}-scene.mp3"
        if not path.exists():
            failures.append(f"{scene}: {path.name} does not exist — the scene is "
                            f"declared authentic but was never recorded/uploaded")
            print(f"  FAIL  {scene:<10} missing {path.name}")
            continue
        size = path.stat().st_size
        if size < MIN_BYTES:
            failures.append(f"{scene}: {path.name} is only {size:,} bytes — "
                            f"truncated, silent, or a placeholder")
            print(f"  FAIL  {scene:<10} {size:,} bytes (too small)")
            continue
        digest = _sha256(path)
        tts_sums = set(baseline.get(scene) or [])
        if digest in tts_sums:
            failures.append(f"{scene}: {path.name} is byte-identical to one of our "
                            f"own TTS renders — renamed, not replaced")
            print(f"  FAIL  {scene:<10} identical to a TTS clip")
            continue
        print(f"  ok    {scene:<10} {size/1024:,.0f} KB")

    if failures:
        print(f"\n  {len(failures)} problem(s):")
        for f in failures:
            print(f"    - {f}")
        print("\n  The coverage ledger closes a reservation purely on the manifest,")
        print("  so a declaration that is not backed by a real file would drop an")
        print("  honest caveat. Fix the file or remove the scene from the manifest.")
        return 1

    print("\n  PASS — every declared scene is backed by a real, distinct audio file.")
    print("  (This proves the file was replaced. It cannot prove human actors —")
    print("   that part is the owner's declaration, by design.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
