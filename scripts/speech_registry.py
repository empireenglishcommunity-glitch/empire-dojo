#!/usr/bin/env python3
"""Enumerate EVERY utterance the practice site speaks, and assign each a voice.

THE DESIGN, AND WHY IT IS THIS WAY
----------------------------------
The site speaks in two ways:

  1. STATIC  — `TTS.speak('Listen carefully...')` written into the page by the
     generator. 15 call sites, ~4,875 distinct texts.
  2. DYNAMIC — `TTS.speak(word.word)` / `TTS.speak(item.say)` in app.js, reading
     from JSON the generator embeds in the page (`const words=[...]`,
     `const dictationWords=[...]`). The text is not in the source at all, so a
     source scan cannot see it — but it IS fully known at build time.

The obvious fix — rewrite all 25 call sites to pass a clip id — is the wrong
one: it touches every generator function, and missing a single site leaves the
robotic browser voice in production with nothing to detect it.

Instead, `TTS.speak(text)` itself becomes content-addressed: it hashes the text
it was given and plays `{AUDIO_BASE}/sp-<hash>.mp3`. No call site changes at all,
dynamic text works identically to static, and this script's job is simply to
enumerate every text that hash could ever be asked for, so the renderer can
produce it.

The hash MUST match the JS in app.js exactly:
    normalise: collapse all whitespace runs to one space, strip ends
    id       : "sp-" + sha256(utf8 bytes).hexdigest()[:16]

Voice assignment comes from voice_cast.json — one consistent voice per surface,
with `listening` rotating across five American speakers because understanding
different people is the actual listening skill.

Usage:
    speech_registry.py                     # summary
    speech_registry.py --json out.json     # the render manifest
    speech_registry.py --check             # exit 1 if any utterance has no clip
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
AUDIO = SITE / "audio"
# The committed record of which speech clips exist in the R2 bucket. Written by
# .github/workflows/speech-render.yml from an actual bucket listing.
RENDERED_MANIFEST = SCRIPT_DIR / "speech-rendered.json"

sys.path.insert(0, str(SCRIPT_DIR))
from voice_cast import load_cast, validate_cast, voice_for  # noqa: E402

OPEN_CALL = re.compile(r"TTS\.speak\(\s*(['\"])")
# The embedded data arrays that feed the dynamic calls.
EMBEDDED = [
    (re.compile(r"const words\s*=\s*(\[.*?\]);", re.S), "word", "vocab"),
    (re.compile(r"const dictationWords\s*=\s*(\[.*?\]);", re.S), "say", "listening"),
]
UNESCAPE = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"',
            "/": "/", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def normalise(text: str) -> str:
    """Must match the JS `_norm()` in app.js exactly."""
    return " ".join((text or "").split())


def clip_id(voice: str, text: str) -> str:
    """Must match the JS `_clipId()` in app.js exactly.

    The VOICE is part of the identity, deliberately. Hashing the text alone
    collapsed every repeat of a word into one clip — so a word that appears both
    as vocabulary and as a listening dictation item could only ever have ONE
    voice, and the owner's requirement to hear different people quietly did not
    happen (the first run assigned just 8 clips to `listening` for exactly this
    reason). Keying on voice+text costs a few more clips and actually delivers
    the cast.

    Each page declares its own voice in `window.SPEECH_VOICE`, which the
    generator knows because it knows which surface it is emitting.
    """
    key = f"{voice}|{normalise(text)}"
    return "sp-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def page_voice(surface: str, rotation_index: int, cast) -> str:
    """The single voice a page speaks with.

    Listening rotates PER PAGE rather than per item: a student hears a different
    American speaker on different days, which is the pedagogical goal, while a
    page keeps one voice so the JS needs only one `window.SPEECH_VOICE`.
    """
    if surface in ("listening", "broadcast"):
        return voice_for("listening", rotation_index, cast)
    return voice_for(surface, 0, cast)


def read_js_string(src: str, i: int, quote: str):
    """Read a JS string literal, honouring escapes. A regex stops at the first
    quote, so `'I\\'m happy'` truncates to `I\\` — that flaw made one earlier
    count report 297 occurrences of the text `I\\`."""
    out, n = [], len(src)
    while i < n:
        c = src[i]
        if c == "\\":
            if i + 1 >= n:
                return None, i
            nxt = src[i + 1]
            if nxt == "u" and i + 5 < n:
                try:
                    out.append(chr(int(src[i + 2:i + 6], 16))); i += 6; continue
                except ValueError:
                    pass
            out.append(UNESCAPE.get(nxt, nxt)); i += 2; continue
        if c == quote:
            return "".join(out), i + 1
        if c == "\n":
            return None, i
        out.append(c); i += 1
    return None, i


def rotation_index(rel: Path) -> int:
    """A stable per-page index for rotating the listening voices.

    Derived from the path (level/week/day) so the same page always gets the same
    speaker across rebuilds — a voice that changed on every deploy would be
    disorienting, and would also invalidate every cached clip.
    """
    nums = [int(n) for n in re.findall(r"\d+", str(rel))]
    return sum(nums) if nums else 0


def scan(site: Path, cast):
    """Returns {(voice, text): {"surfaces": set, "count": int, "kind": set}}.

    Keyed by (voice, text) because the voice is part of the clip identity — see
    clip_id(). The page's surface decides its voice, so the same word spoken on
    two different surfaces legitimately becomes two clips in two voices.
    """
    found = collections.defaultdict(
        lambda: {"surfaces": set(), "count": 0, "kind": set()})
    pages = 0
    page_voices = {}
    for path in sorted(site.rglob("*.html")):
        rel = path.relative_to(site)
        if rel.parts and rel.parts[0] == "audio":
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        pages += 1
        surface = path.stem
        voice = page_voice(surface, rotation_index(rel), cast)
        page_voices[str(rel)] = voice

        def record(t, kind, surf):
            t = normalise(t)
            if len(t) < 2:
                return
            e = found[(voice, t)]
            e["count"] += 1
            e["surfaces"].add(surf)
            e["kind"].add(kind)

        # --- static literals -------------------------------------------------
        for m in OPEN_CALL.finditer(src):
            text, _ = read_js_string(src, m.end(), m.group(1))
            if text is not None:
                record(text, "static", surface)

        # --- embedded data arrays (the dynamic calls) ------------------------
        for pat, field, dyn_surface in EMBEDDED:
            for m in pat.finditer(src):
                try:
                    rows = json.loads(m.group(1))
                except Exception:
                    continue
                for row in rows:
                    if isinstance(row, dict):
                        record(str(row.get(field, "")), "dynamic", dyn_surface)
    return found, pages, page_voices


def build_registry(found):
    """Key every (voice, text) pair by its clip id."""
    reg = {}
    for (voice, text) in sorted(found):
        meta = found[(voice, text)]
        reg[clip_id(voice, text)] = {
            "text": text,
            "words": len(text.split()),
            "voice": voice,
            "surfaces": sorted(meta["surfaces"]),
            "kind": sorted(meta["kind"]),
            "occurrences": meta["count"],
        }
    return reg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", metavar="PATH")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any utterance has no rendered clip")
    ap.add_argument("--site", default=str(SITE))
    args = ap.parse_args()

    site = Path(args.site)
    cast = load_cast()
    validate_cast(cast)
    found, pages, page_voices = scan(site, cast)
    reg = build_registry(found)

    # Where a rendered speech clip actually LIVES is R2, not site/audio/ —
    # Cloudflare Pages caps a free-plan deployment at 20,000 files and site/ is
    # already at 8,056, so these 9,360 are served from the bucket and never
    # committed. Checking site/audio/ would therefore report all 9,360 as
    # missing forever, and this gate would be permanently red for no reason —
    # the failure mode that trains people to ignore a red tick.
    #
    # scripts/speech-rendered.json is the committed record of what is in the
    # bucket, rebuilt by the render workflow from a real bucket listing. Using
    # it keeps this check credential-free and auditable in git history, and it
    # still falls back to site/audio/ so a locally rendered clip counts.
    rendered = set()
    if RENDERED_MANIFEST.exists():
        try:
            rendered = set(json.loads(
                RENDERED_MANIFEST.read_text()).get("clips", []))
        except (ValueError, OSError) as exc:
            print(f"::warning::could not read {RENDERED_MANIFEST.name}: {exc}")
    missing = [cid for cid in reg
               if cid not in rendered and not (AUDIO / f"{cid}.mp3").exists()]

    if args.check:
        # Characters that Python's str.split() and JavaScript's /\s+/ do NOT
        # agree on. normalise() runs in Python to name the rendered files and in
        # site/js/speech-id.js to name the file the browser asks for, so a text
        # containing any of these would hash differently on the two sides: the
        # clip would exist and still never be found. No current utterance
        # contains one, and this check is what keeps that true — it cannot be
        # caught later, because a missing clip looks identical to an unrendered
        # one. See verify_clip_id_parity.py, which proves the agreement.
        divergent = {
            "\x1c": "FILE SEPARATOR", "\x1d": "GROUP SEPARATOR",
            "\x1e": "RECORD SEPARATOR", "\x1f": "UNIT SEPARATOR",
            "\x85": "NEL", "\ufeff": "BOM / ZWNBSP",
        }
        bad = [(cid, ch, name) for cid, m in reg.items()
               for ch, name in divergent.items() if ch in m["text"]]
        if bad:
            print(f"::error::{len(bad)} utterance(s) contain whitespace that "
                  f"Python and JavaScript normalise DIFFERENTLY, so the browser "
                  f"would compute a different clip id than the renderer used.")
            for cid, ch, name in bad[:10]:
                print(f"  {cid}: contains {name} ({ch!r}) — "
                      f"{reg[cid]['text'][:50]!r}")
            return 1

        if missing:
            print(f"::error::{len(missing)} of {len(reg)} spoken utterances have "
                  f"no rendered clip. The site would fall back to the browser's "
                  f"robotic voice for these. Run the speech render workflow.")
            # NOTE: "surfaces" is a LIST — an utterance can appear on more than
            # one surface. This read "surface" (singular) and raised KeyError on
            # the only branch it exists to serve, so the gate printed a
            # traceback instead of the diagnostic whenever it actually tripped.
            by_surface = collections.Counter(
                s for c in missing for s in reg[c]["surfaces"])
            for s, n in by_surface.most_common():
                print(f"  {s}: {n} missing")
            for c in missing[:5]:
                print(f"  e.g. {c}: {reg[c]['text'][:60]!r}")
            return 1
        print(f"OK: all {len(reg)} spoken utterances have a rendered clip.")
        return 0

    static = sum(1 for v in reg.values() if "static" in v["kind"])
    dynamic = sum(1 for v in reg.values() if "dynamic" in v["kind"])
    words = sum(v["words"] for v in reg.values())

    print("=" * 68)
    print("  SPEECH REGISTRY — every utterance the site speaks")
    print("=" * 68)
    print(f"  pages scanned        : {pages}")
    print(f"  DISTINCT utterances  : {len(reg):,}")
    print(f"    static (in source) : {static:,}")
    print(f"    dynamic (embedded) : {dynamic:,}")
    print(f"  total words          : {words:,}")
    print(f"  already rendered     : {len(reg) - len(missing):,}")
    print(f"  MISSING              : {len(missing):,}")
    print()
    print("  by voice:")
    for v, n in collections.Counter(x["voice"] for x in reg.values()).most_common():
        print(f"    {v:<14} {n:>6}")
    print()
    print("  by surface:")
    surf = collections.Counter()
    for x in reg.values():
        for s in x["surfaces"]:
            surf[s] += 1
    for s, n in surf.most_common():
        print(f"    {s:<14} {n:>6}")

    # Render cost, using the measured 179 wpm from the shipped library.
    mins = words / 179
    print()
    print(f"  speech to render     : {mins:.0f} min ({mins/60:.1f} h)")
    print(f"  at 48 kbps           : {mins*60*48*1000/8/1024/1024:.0f} MB")

    if args.json:
        Path(args.json).write_text(json.dumps(reg, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(f"\n  wrote {len(reg):,} clips -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
