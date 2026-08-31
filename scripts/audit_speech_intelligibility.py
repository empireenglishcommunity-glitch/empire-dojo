#!/usr/bin/env python3
"""Check that rendered speech clips actually SAY what they are supposed to say.

WHY THIS EXISTS
---------------
Every other audio check in this repo verifies properties AROUND the audio: that
a file exists, that it is not zero bytes, that its pace matches the level, that
the clip id the browser computes matches the one Python rendered. None of them
listens. So a clip could be perfectly named, correctly paced and completely
wrong, and nothing would notice.

That is not hypothetical. A student reported that "She is a student." on
a1/week1/day1/grammar sounded wrong. The waveform was clean — no clipping, sane
level, plausible duration — and every existing check passed. Transcribing it
revealed Kokoro had prepended a spurious syllable: the clip says
"as she is a student".

This script closes that gap by running ASR over the rendered clips and comparing
the transcript to the text the clip was rendered FROM. It is a sampling tool,
not a gate: ASR is imperfect, so a mismatch means "a human should listen to
this one", not "this is definitely broken".

Usage:
    audit_speech_intelligibility.py --sample 150
    audit_speech_intelligibility.py --surface grammar --voice am_michael
    audit_speech_intelligibility.py --clips sp-29dd6f3c71e19741 sp-...
"""
import argparse
import collections
import concurrent.futures as cf
import json
import os
import random
import re
import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from speech_registry import SITE, build_registry, scan  # noqa: E402
from voice_cast import load_cast, validate_cast  # noqa: E402

from render_speech import R2_PREFIX  # noqa: E402  (one source of truth)

BASE = f"https://audio.empireenglish.online/{R2_PREFIX}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
CACHE = Path(os.environ.get("SPEECH_AUDIT_CACHE", "_speech_audit_cache"))


def normalise_for_compare(s: str) -> str:
    """Compare words only. ASR punctuation and casing are not the point, and
    holding it to them would bury real defects under noise."""
    s = s.lower().replace("’", "'")
    s = re.sub(r"[^a-z0-9' ]", " ", s)
    return " ".join(s.split())


def fetch(cid: str) -> Path:
    CACHE.mkdir(exist_ok=True)
    p = CACHE / f"{cid}.mp3"
    if p.exists() and p.stat().st_size > 0:
        return p
    req = urllib.request.Request(f"{BASE}/{cid}.mp3", headers={"User-Agent": UA})
    p.write_bytes(urllib.request.urlopen(req, timeout=45).read())
    return p


def registry():
    cast = load_cast()
    validate_cast(cast)
    found, _pages, _voices = scan(SITE, cast)
    return build_registry(found)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=120)
    ap.add_argument("--surface")
    ap.add_argument("--voice")
    ap.add_argument("--clips", nargs="*")
    ap.add_argument("--model", default="small")
    ap.add_argument("--min-words", type=int, default=2,
                    help="single words are unreliable to transcribe in isolation")
    ap.add_argument("--json", help="write the full result here")
    ap.add_argument("--seed", type=int, default=20260831)
    args = ap.parse_args()

    reg = registry()
    if args.clips:
        picked = [c for c in args.clips if c in reg]
    else:
        pool = [c for c, m in reg.items()
                if len(m["text"].split()) >= args.min_words
                and (not args.surface or args.surface in m["surfaces"])
                and (not args.voice or m["voice"] == args.voice)]
        random.Random(args.seed).shuffle(pool)
        # Spread the sample evenly over voices so a fault in one voice cannot
        # hide behind the others.
        by_voice = collections.defaultdict(list)
        for c in pool:
            by_voice[reg[c]["voice"]].append(c)
        picked, i = [], 0
        while len(picked) < min(args.sample, len(pool)):
            added = False
            for v in sorted(by_voice):
                if i < len(by_voice[v]) and len(picked) < args.sample:
                    picked.append(by_voice[v][i])
                    added = True
            if not added:
                break
            i += 1

    print(f"  clips to check: {len(picked)}   model: {args.model}")
    with cf.ThreadPoolExecutor(16) as ex:
        list(ex.map(lambda c: fetch(c), picked))
    print("  downloaded; transcribing...")

    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8")

    results, bad = [], []
    for n, cid in enumerate(picked, 1):
        meta = reg[cid]
        segs, _ = model.transcribe(str(fetch(cid)), language="en", beam_size=5)
        heard = " ".join(s.text.strip() for s in segs).strip()
        exp_n = normalise_for_compare(meta["text"])
        got_n = normalise_for_compare(heard)
        ok = got_n == exp_n
        # Classify the miss so the report is actionable rather than a list.
        kind = "ok"
        if not ok:
            if got_n.endswith(exp_n) and got_n != exp_n:
                kind = "EXTRA AT START"
            elif got_n.startswith(exp_n):
                kind = "extra at end"
            elif exp_n in got_n:
                kind = "extra around"
            elif got_n in exp_n:
                kind = "TRUNCATED"
            else:
                kind = "differs"
        row = {"cid": cid, "voice": meta["voice"],
               "surfaces": meta["surfaces"], "expected": meta["text"],
               "heard": heard, "ok": ok, "kind": kind}
        results.append(row)
        if not ok:
            bad.append(row)
        if n % 25 == 0:
            print(f"    {n}/{len(picked)} checked, {len(bad)} mismatch(es)")

    print()
    print(f"  === {len(results)} clips checked, {len(bad)} mismatch "
          f"({100*len(bad)/max(len(results),1):.1f}%) ===")
    print()
    by_kind = collections.Counter(r["kind"] for r in bad)
    for k, c in by_kind.most_common():
        print(f"    {k:<16} {c}")
    print()
    by_voice = collections.Counter(r["voice"] for r in bad)
    tot_voice = collections.Counter(r["voice"] for r in results)
    print(f"    {'voice':<13}{'checked':>8}{'bad':>6}{'rate':>8}")
    for v in sorted(tot_voice):
        b = by_voice.get(v, 0)
        print(f"    {v:<13}{tot_voice[v]:>8}{b:>6}{100*b/tot_voice[v]:>7.1f}%")
    print()
    for r in bad[:30]:
        print(f"    [{r['kind']}] {r['cid']} ({r['voice']})")
        print(f"        expected: {r['expected'][:70]!r}")
        print(f"        heard:    {r['heard'][:70]!r}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1, ensure_ascii=False))
        print(f"\n  full result -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
