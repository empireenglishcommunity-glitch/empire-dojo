#!/usr/bin/env python3
"""The voice cast: which Kokoro voice speaks which surface, and the guard that
keeps the programme American-only.

Owner decisions this encodes:
  1. Kokoro everywhere — the browser's speechSynthesis (the robotic voice that
     differed on every student's device) is removed from the site entirely.
  2. A MIX of voices, assigned per surface, so the site sounds like a team of
     teachers instead of one narrator. The assignment is CONSISTENT: the grammar
     teacher always sounds like the grammar teacher, which is what lets a student
     recognise "their" teachers.
  3. AMERICAN ACCENT ONLY. Kokoro ships 4 British voices (bf_emma, bf_isabella,
     bm_george, bm_lewis) and 189 already-shipped clips used them. They are
     forbidden here and `validate_cast()` fails the build if one appears, so this
     cannot regress silently.

Listening is the one surface that deliberately rotates voices: comprehension of
several different speakers is the skill, so one voice would undertrain it.
"""
import json
from pathlib import Path

CAST_FILE = Path(__file__).resolve().parent / "voice_cast.json"

FORBIDDEN_PREFIXES = ("bf_", "bm_")   # British — not used in this programme
ALLOWED_PREFIXES = ("af_", "am_")     # American female / male


def load_cast(path=CAST_FILE):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_cast(cast=None):
    """Raise ValueError if any voice is British or malformed.

    Called by the generator and by CI. A British voice reaching a student is a
    content error, not a style preference: the programme teaches American
    English, and a student imitating a British model on the accent drill is
    being taught the wrong target.
    """
    cast = cast or load_cast()
    problems = []

    voices = [(f"cast.{k}", v["voice"]) for k, v in cast["cast"].items()]
    voices += [(f"listening_rotation[{i}]", v)
               for i, v in enumerate(cast["listening_rotation"]["voices"])]
    voices.append(("default", cast["default"]))

    for where, v in voices:
        if v.startswith(FORBIDDEN_PREFIXES):
            problems.append(f"{where}: {v!r} is a BRITISH voice — this "
                            f"programme is American-English only")
        elif not v.startswith(ALLOWED_PREFIXES):
            problems.append(f"{where}: {v!r} is not a recognised Kokoro voice "
                            f"(expected af_* or am_*)")

    known = set(cast["_american_voices_available"])
    for where, v in voices:
        if v.startswith(ALLOWED_PREFIXES) and v not in known:
            problems.append(f"{where}: {v!r} is not in "
                            f"_american_voices_available")

    if problems:
        raise ValueError("voice cast is invalid:\n  - " + "\n  - ".join(problems))
    return True


def voice_for(surface, index=0, cast=None):
    """The voice for a surface. `index` rotates the listening voices so a
    student hears several different American speakers."""
    cast = cast or load_cast()
    if surface == "listening":
        pool = cast["listening_rotation"]["voices"]
        return pool[index % len(pool)]
    entry = cast["cast"].get(surface)
    return entry["voice"] if entry else cast["default"]


def summary(cast=None):
    cast = cast or load_cast()
    lines = ["  surface        voice         role"]
    for k, v in cast["cast"].items():
        lines.append(f"  {k:<14} {v['voice']:<13} {v['role']}")
    lines.append(f"  listening      (rotates)     "
                 f"{', '.join(cast['listening_rotation']['voices'])}")
    return "\n".join(lines)


if __name__ == "__main__":
    c = load_cast()
    validate_cast(c)
    print("VOICE CAST — American English only\n")
    print(summary(c))
    print("\n  validation: PASSED (no British voices)")
    used = {v["voice"] for v in c["cast"].values()} | \
           set(c["listening_rotation"]["voices"])
    print(f"  distinct voices in use: {len(used)} of "
          f"{len(c['_american_voices_available'])} American voices")
    print(f"  {sorted(used)}")
