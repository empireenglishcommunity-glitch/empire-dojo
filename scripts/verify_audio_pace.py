#!/usr/bin/env python3.12
"""Verify the delivery pace of every rendered extended-listening clip.

Independent of the renderer: reads site/audio/*.mp3 and scripts/audio-manifest.json
and re-derives words-per-minute from the files on disk. Run it after rendering,
and in review, because several CEFR descriptors are claims about delivery speed
and this is the only thing that checks the claim against the artefact:

    A1.R.1  ... when people SPEAK SLOWLY AND CLEARLY
    B1.R2   ... when delivered RELATIVELY SLOWLY AND CLEARLY
    C1.R.1  extended speech at native delivery
    C2.R.1  ... delivered at FAST NATIVE SPEED

Fails (exit 1) if a level's aggregate pace is off its target by more than
--tolerance, or if any measurable clip at C1/C2 is slower than --floor-c. The
second check exists because "fast native speed" is violated by SLOW clips
specifically, and an aggregate can hide them.

    python3.12 -m pip install soundfile
    python3.12 scripts/verify_audio_pace.py
"""
import argparse
import json
import pathlib
import sys

try:
    import soundfile as sf
except ImportError:
    print("This script needs: python3.12 -m pip install soundfile")
    raise SystemExit(1)

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
MANIFEST = SCRIPT_DIR / "audio-manifest.json"
AUDIO = REPO_ROOT / "site" / "audio"

sys.path.insert(0, str(SCRIPT_DIR))
from audio_pace import MIN_WORDS_FOR_PACE, target_wpm_for  # noqa: E402

LEVELS = ("a1", "a2", "b1", "b2", "c1", "c2")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tolerance", type=float, default=0.08,
                    help="allowed deviation of a level's aggregate pace (0.08)")
    ap.add_argument("--floor-c", type=float, default=165.0,
                    help="no measurable C1/C2 clip may be slower than this wpm")
    args = ap.parse_args()

    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)

    words, secs, n_all, n_meas = {}, {}, {}, {}
    missing, slow_c, per_clip = [], [], []
    for cid, meta in sorted(manifest.items()):
        if meta.get("kind") != "broadcast":
            continue
        lvl = (meta.get("level") or "?").lower()
        n_all[lvl] = n_all.get(lvl, 0) + 1
        p = AUDIO / f"{cid}.mp3"
        if not p.exists():
            missing.append(cid)
            continue
        w = len((meta.get("text") or "").split())
        if w < MIN_WORDS_FOR_PACE:
            continue
        dur = sf.info(str(p)).duration
        if dur <= 0:
            continue
        # EFFECTIVE pace is what the student hears. Broadcast clips are rendered
        # at a phoneme-safe speed and slowed at PLAYBACK via audio.playbackRate
        # (see audio_pace.split_pace); a clip with playback_rate 0.65 plays 1/0.65
        # times longer, so its delivered wpm is rendered_wpm * playback_rate.
        # Measuring the bare file would wrongly flag every slowed low-level clip.
        playback = float(meta.get("playback_rate", 1.0)) or 1.0
        eff_dur = dur / playback
        wpm = w / (eff_dur / 60)
        words[lvl] = words.get(lvl, 0) + w
        secs[lvl] = secs.get(lvl, 0.0) + eff_dur
        n_meas[lvl] = n_meas.get(lvl, 0) + 1
        per_clip.append((cid, lvl, w, wpm))
        if lvl in ("c1", "c2") and wpm < args.floor_c:
            slow_c.append((cid, w, wpm))

    print(f"  {'lvl':<5}{'clips':>7}{'measured':>10}{'words':>8}{'minutes':>9}"
          f"{'wpm':>6}{'target':>8}{'drift':>8}")
    bad_levels = []
    for lvl in LEVELS:
        if not secs.get(lvl):
            continue
        got = words[lvl] / (secs[lvl] / 60)
        want = target_wpm_for(lvl)
        drift = (got - want) / want
        flag = "" if abs(drift) <= args.tolerance else "  <== OFF"
        if abs(drift) > args.tolerance:
            bad_levels.append((lvl, got, want))
        print(f"  {lvl:<5}{n_all[lvl]:>7}{n_meas.get(lvl,0):>10}{words[lvl]:>8}"
              f"{secs[lvl]/60:>9.1f}{got:>6.0f}{want:>8}{drift:>+7.0%}{flag}")

    tot_min = sum(secs.values()) / 60
    print(f"\n  {sum(n_all.values())} broadcast clips, "
          f"{tot_min:.0f} min of measurable audio")

    ok = True
    if missing:
        ok = False
        print(f"\n  MISSING AUDIO for {len(missing)} clip(s): {missing[:10]}")
    if bad_levels:
        ok = False
        print(f"\n  LEVELS OFF TARGET by more than {args.tolerance:.0%}:")
        for lvl, got, want in bad_levels:
            print(f"    {lvl}: {got:.0f} wpm against target {want}")
    if slow_c:
        ok = False
        print(f"\n  C1/C2 clips under {args.floor_c:.0f} wpm — these break the "
              f"'native / fast native speed' claim:")
        for cid, w, wpm in sorted(slow_c, key=lambda x: x[2]):
            print(f"    {cid:<16}{w:>4}w  {wpm:>4.0f} wpm")

    if ok:
        print("\n  PASS — every level within tolerance, and no C1/C2 clip "
              "below the native-speed floor.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
