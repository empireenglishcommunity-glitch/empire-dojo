#!/usr/bin/env python3
"""Extract every utterance the site currently speaks with the BROWSER's voice.

WHY THIS EXISTS
---------------
`accent`, `listening`, `vocab`, `grammar`, `reading`, `mediation`, `review` and
the day index do not play an audio file at all. They call `TTS.speak(...)`, which
is `window.speechSynthesis` — the phone's or laptop's own built-in voice. That
voice differs on every device and on most of them it is the robotic one. Only
`shadowing` and `broadcast` play pre-rendered clips.

This script produces the authoritative list of what has to be rendered to remove
the browser voice entirely.

WHY NOT A REGEX
---------------
A naive `TTS\\.speak\\(['"](.*?)['"]` stops at the first quote it sees, so
`TTS.speak('I\\'m happy')` is captured as `I\\` — the text is silently truncated
and one real utterance becomes a bogus short one. A first pass over the site
reported 297 occurrences of the "text" `I\\`, which is how the flaw showed up.

So this walks each JS string literal character by character and honours
backslash escapes, which is exact. The count it produces is the number we render
against; nothing should be rendered from an approximation.

Usage:
    python3.12 scripts/extract_speech.py                 # summary
    python3.12 scripts/extract_speech.py --json out.json  # full manifest
    python3.12 scripts/extract_speech.py --check          # exit 1 if any exist
"""
import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SITE = SCRIPT_DIR.parent / "site"

# Matches the call opening only; the argument is then parsed properly below.
OPEN = re.compile(r"TTS\.speak\(\s*(['\"])")

# JS escape sequences we need to resolve to get the real spoken text.
UNESCAPE = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"',
            "/": "/", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def read_js_string(src: str, i: int, quote: str):
    """Read a JS string literal starting at `i` (just past the opening quote).

    Returns (text, index_after_closing_quote) or (None, i) if unterminated.
    Handles backslash escapes, which is the whole point of not using a regex.
    """
    out = []
    n = len(src)
    while i < n:
        c = src[i]
        if c == "\\":
            if i + 1 >= n:
                return None, i
            nxt = src[i + 1]
            if nxt == "u" and i + 5 < n:
                try:
                    out.append(chr(int(src[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            if nxt == "x" and i + 3 < n:
                try:
                    out.append(chr(int(src[i + 2:i + 4], 16)))
                    i += 4
                    continue
                except ValueError:
                    pass
            out.append(UNESCAPE.get(nxt, nxt))
            i += 2
            continue
        if c == quote:
            return "".join(out), i + 1
        if c == "\n":
            return None, i          # unterminated literal
        out.append(c)
        i += 1
    return None, i


def clip_id(text: str) -> str:
    """Content-addressed id: the same sentence anywhere is ONE clip.

    Position-based ids (level-week-day) would render the same word once per page
    that speaks it. Hashing the text means every duplicate collapses, and editing
    a sentence produces a new id automatically rather than silently reusing a
    stale recording — which is a live gotcha for the existing position-based
    clips (see AUDIO-RENDER-RUNBOOK.md: "editing a script does not change the id,
    and both renderers will skip the now-stale MP3").
    """
    return "sp-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def scan(site: Path):
    found = collections.defaultdict(lambda: {"count": 0, "pages": set(),
                                             "page_types": set()})
    malformed = []
    pages = 0
    for path in sorted(site.rglob("*.html")):
        rel = path.relative_to(site)
        if rel.parts and rel.parts[0] == "audio":
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        pages += 1
        for m in OPEN.finditer(src):
            quote = m.group(1)
            text, _ = read_js_string(src, m.end(), quote)
            if text is None:
                malformed.append(str(rel))
                continue
            text = " ".join(text.split())
            if len(text) < 2:
                continue
            e = found[text]
            e["count"] += 1
            e["pages"].add(str(rel))
            e["page_types"].add(path.stem)
    return found, pages, malformed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", metavar="PATH",
                    help="write the full render manifest here")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any browser-voice call exists (CI gate)")
    ap.add_argument("--site", default=str(SITE))
    args = ap.parse_args()

    site = Path(args.site)
    if not site.is_dir():
        print(f"ERROR: {site} is not a directory", file=sys.stderr)
        return 2

    found, pages, malformed = scan(site)

    if args.check:
        if found:
            total = sum(v["count"] for v in found.values())
            print(f"::error::{total} browser-speech call(s) remain across "
                  f"{len(found)} distinct utterances. The practice site must "
                  f"not use window.speechSynthesis — every spoken line needs a "
                  f"rendered clip. Run scripts/extract_speech.py to list them.")
            by_type = collections.Counter()
            for v in found.values():
                for t in v["page_types"]:
                    by_type[t] += 1
            for t, n in by_type.most_common():
                print(f"  {t}: {n} distinct utterances")
            return 1
        print("OK: no browser-speech calls anywhere in the site.")
        return 0

    by_type = collections.defaultdict(set)
    for text, v in found.items():
        for t in v["page_types"]:
            by_type[t].add(text)

    total_calls = sum(v["count"] for v in found.values())
    words = sorted(len(t.split()) for t in found)

    print("=" * 68)
    print("  UTTERANCES CURRENTLY SPOKEN BY THE BROWSER'S OWN VOICE")
    print("=" * 68)
    print(f"  pages scanned        : {pages}")
    print(f"  total call sites     : {total_calls:,}")
    print(f"  DISTINCT utterances  : {len(found):,}   <- clips to render")
    print(f"  malformed literals   : {len(malformed)}")
    print()
    print(f"  {'page type':<14} {'distinct':>10}")
    for t, texts in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        print(f"  {t:<14} {len(texts):>10}")
    print()
    print(f"  words: min {words[0]} / median {words[len(words)//2]} / "
          f"max {words[-1]} / total {sum(words):,}")
    dupes = sum(1 for v in found.values() if v["count"] > 1)
    print(f"  utterances reused on >1 page: {dupes:,} "
          f"({total_calls/max(len(found),1):.1f}x reuse)")

    if args.json:
        manifest = {
            clip_id(t): {
                "text": t,
                "words": len(t.split()),
                "occurrences": v["count"],
                "page_types": sorted(v["page_types"]),
            }
            for t, v in sorted(found.items())
        }
        Path(args.json).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n  wrote {len(manifest):,} clips -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
