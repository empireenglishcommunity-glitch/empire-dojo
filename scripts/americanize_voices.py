#!/usr/bin/env python3
"""Replace every British Kokoro voice with an American one, safely.

Owner decision: the programme is American-English only — no British voices
anywhere. 189 already-shipped clips use bm_george / bm_lewis / bf_emma /
bf_isabella, specified per speaker turn in the broadcast scripts in
empire-nexus.

A blind find-and-replace is NOT safe: the broadcast scenes are multi-speaker, so
if a scene already contains the American voice a British one maps onto, two
different characters collapse into a single voice — and a two-person scene
becomes one person talking to themselves, which is exactly what these clips
exist to avoid. So this detects per-scene collisions and reassigns to a free
American voice instead.

Usage:
    americanize_voices.py --content <path-to-empire-nexus>/bots/discord-learning-bot/content [--apply]

Without --apply it only reports (dry run).
"""
import argparse
import json
from pathlib import Path

# Gender- and character-preserving first choice for each British voice.
PREFERRED = {
    "bm_george": "am_adam",       # UK male authoritative -> US male professional
    "bm_lewis": "am_michael",     # UK male warm          -> US male warm
    "bf_emma": "af_bella",        # UK female clear       -> US female clear
    "bf_isabella": "af_nicole",   # UK female elegant     -> US female mature
}
# Fallbacks, same gender, used when the preferred voice is already taken in that
# scene by a different speaker.
FALLBACKS = {
    "m": ["am_adam", "am_michael"],
    "f": ["af_bella", "af_nicole", "af_sarah", "af_sky", "af_heart"],
}
AMERICAN = set(FALLBACKS["m"]) | set(FALLBACKS["f"])


def gender_of(voice):
    return "m" if voice.startswith(("am_", "bm_")) else "f"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    root = Path(args.content)
    files = sorted(root.glob("*/broadcast/week*.json"))
    if not files:
        print(f"ERROR: no broadcast scripts under {root}")
        return 2

    total_turns = changed = collisions = 0
    files_changed = 0

    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  SKIP {f.name}: {e}")
            continue
        segs = data.get("segments") or []
        if not segs:
            continue

        # Voices already used in this scene by each speaker.
        speaker_voice = {}
        for s in segs:
            v = s.get("voice")
            if v:
                speaker_voice.setdefault(s.get("speaker", ""), v)

        # Which American voices are already claimed in this scene by a speaker
        # whose voice is NOT being remapped.
        claimed = {v for v in speaker_voice.values() if v in AMERICAN}

        # Decide a target voice per SPEAKER (not per turn) so a character keeps
        # one voice for the whole scene.
        remap = {}
        for speaker, v in speaker_voice.items():
            if not v or not v.startswith(("bf_", "bm_")):
                continue
            want = PREFERRED.get(v, "af_heart")
            if want in claimed:
                collisions += 1
                alt = next((c for c in FALLBACKS[gender_of(v)]
                            if c not in claimed), None)
                if alt is None:
                    alt = FALLBACKS[gender_of(v)][0]  # exhausted; reuse
                print(f"  COLLISION {f.parent.parent.name}/{f.stem}: "
                      f"speaker {speaker!r} {v} -> {want} already used; "
                      f"using {alt}")
                want = alt
            remap[speaker] = want
            claimed.add(want)

        if not remap:
            continue

        n = 0
        for s in segs:
            v = s.get("voice")
            if v and v.startswith(("bf_", "bm_")):
                s["voice"] = remap.get(s.get("speaker", ""),
                                       PREFERRED.get(v, "af_heart"))
                n += 1
        total_turns += len(segs)
        changed += n
        files_changed += 1
        lvl = f.parent.parent.name
        print(f"  {lvl}/{f.stem}: {n} turn(s) -> "
              f"{ {k: v for k, v in remap.items()} }")
        if args.apply:
            f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")

    print()
    print(f"  files with British voices : {files_changed}")
    print(f"  turns reassigned          : {changed}")
    print(f"  per-scene collisions fixed: {collisions}")
    print(f"  mode                      : {'APPLIED' if args.apply else 'DRY RUN'}")
    if not args.apply:
        print("\n  Re-run with --apply to write the changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
