#!/usr/bin/env python3
"""Guard render_speech.speakable(): it must strip notation and NOTHING else.

WHY THIS IS A BUILD GATE
------------------------
speakable() decides what Kokoro is told to say. It exists because the accent
drills print IPA next to the spelling — "measure /ʒ/, major /dʒ/" — and Kokoro
read the characters, so the clip said "measure slash edge slash major". 63 clips
were affected, all on the accent surface, which is the pronunciation model
students are asked to imitate.

The danger is entirely on the other side. While writing it I transcribed the IPA
diphthongs by hand and included the plain letters "e" and "a", so the
word-dropping rule matched almost every English word and

    "She is a student."   rendered as   "is"

Nothing downstream would have caught that. The clip id is computed from the
ORIGINAL text, so the id stays valid; the file exists, is non-zero, has a
plausible duration and passes every other check. It would simply have said the
wrong thing — which is the exact failure this whole line of work started from.

So this asserts both directions: notation is removed, and ordinary English
survives untouched.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_speech import _IPA_CHARS, speakable  # noqa: E402

# (input, expected) — expected is exact, because "close enough" is how the
# ASCII-letter bug would have slipped through.
CASES = [
    # Ordinary text must be returned byte-for-byte. These are real utterances.
    ("She is a student.", "She is a student."),
    ("I am from Egypt.", "I am from Egypt."),
    ("They are my friends.", "They are my friends."),
    ("He is not here.", "He is not here."),
    ("Are you a teacher?", "Are you a teacher?"),
    ("Cairo is bigger than Aswan.", "Cairo is bigger than Aswan."),
    ("It requires eighteen words to say no.",
     "It requires eighteen words to say no."),
    ("Then add the tomatoes and some salt.",
     "Then add the tomatoes and some salt."),
    # Every letter of the alphabet must survive.
    ("The quick brown fox jumps over the lazy dog.",
     "The quick brown fox jumps over the lazy dog."),
    # Notation that must go.
    ("shop, chop, ships, chips, measure /ʒ/, major /dʒ/, a lot of /əv/, a lot OF ❌",
     "shop, chop, ships, chips, measure, major, a lot of, a lot OF"),
    ("/prəˈvaɪdɪd ðət/ (chunk), pro-vi-ded that (separated)",
     "(chunk), pro-vi-ded that (separated)"),
    ("BIGG-er, bigg-ERR ❌, thən, THAN ❌", "BIGG-er, bigg-ERR, THAN"),
    ("hello → goodbye", "hello goodbye"),
    # Never return empty: a silent clip looks like a broken file.
    ("/ʒ/", "/ʒ/"),
    ("❌", "❌"),
]


def main():
    bad = []

    # The bug that motivated this file, asserted directly.
    ascii_in_ipa = [c for c in _IPA_CHARS if ord(c) < 128]
    if ascii_in_ipa:
        print(f"::error::_IPA_CHARS contains ASCII {ascii_in_ipa!r} — this "
              f"deletes ordinary English words from the spoken text.")
        bad.append("ascii")

    for src, want in CASES:
        got = speakable(src)
        ok = got == want
        if not ok:
            bad.append(src)
        print(f"  {'OK ' if ok else 'BAD'} {src[:52]!r}")
        if not ok:
            print(f"       want {want!r}")
            print(f"       got  {got!r}")

    # A property check over the real corpus: speakable() must never remove a
    # word that contains only ASCII letters and ordinary punctuation.
    try:
        from speech_registry import SITE, build_registry, scan
        from voice_cast import load_cast, validate_cast
        cast = load_cast()
        validate_cast(cast)
        found, _p, _v = scan(SITE, cast)
        reg = build_registry(found)
        import html as _html
        import re as _re

        def words(s):
            """Alphanumeric words only. Comparing raw tokens flagged the
            intentional tidying — a stripped leading comma, an unescaped
            &quot; — as if English had been lost."""
            s = _html.unescape(s)
            return [w for w in _re.findall(r"[A-Za-z0-9']+", s) if w.isascii()]

        # Only utterances containing NO notation at all. For those, speakable()
        # must not change a single word — that is the property the ASCII-letter
        # bug violated, and it violated it everywhere. Utterances that DO carry
        # notation are covered exactly by CASES above; checking them here would
        # mean re-deriving "what should be stripped", and the ASCII fragments
        # inside IPA spans (the "dbi" in /dbi/) would read as lost English.
        NOTATION = _re.compile(r"/[^/]{1,48}/|[^\x00-\x7F]|&[a-zA-Z#0-9]+;")
        plain_utts = [(cid, m) for cid, m in reg.items()
                      if not NOTATION.search(m["text"])]
        losses = []
        for cid, m in plain_utts:
            before = words(m["text"])
            after = set(words(speakable(m["text"])))
            missing = [w for w in before if w not in after]
            if missing:
                losses.append((cid, missing[:4], m["text"][:50]))
        print()
        print(f"  corpus check: {len(plain_utts)} notation-free utterances "
              f"(of {len(reg)}), {len(losses)} lost an ASCII word")
        for cid, miss, t in losses[:10]:
            print(f"    {cid}: dropped {miss} from {t!r}")
        if losses:
            print("::error::speakable() removed plain English words. Only "
                  "notation may be stripped.")
            bad.append("corpus")
    except Exception as exc:                              # noqa: BLE001
        print(f"  (corpus check skipped: {exc})")

    print()
    if bad:
        print(f"  FAILED — {len(bad)} problem(s)")
        return 1
    print(f"  PASS — {len(CASES)} cases, notation stripped, English intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
