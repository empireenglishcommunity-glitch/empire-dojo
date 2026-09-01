#!/usr/bin/env python3
"""The ear must only ever hear correct English. The screen keeps the contrast.

WHY THIS EXISTS
---------------
Practice-word lists on accent pages deliberately mix a correct model with a WRONG
form marked ❌, plus notation showing bad delivery (`pro-vi-ded that (separated)`,
`as · long · as`). On the page that is good teaching — the student sees both forms
and the ❌ says which to avoid.

Spoken aloud it inverted. `❌` is U+274C, which sits inside the emoji range that
`render_speech.speakable()` already strips, so the marker was removed and **the
error was spoken with no cue that it was an error**. Right and wrong reached the
ear identically labelled. A synthesiser has no way to say "this next one is
wrong."

Most error items also encode wrong STRESS through capitalisation, which TTS
cannot render at all. Measured with Kokoro (am_adam): `BIGG-ist` 22,316 bytes,
`bigg-EST` 20,396, plain `biggest` 13,868 — both hyphenated forms roughly 50%
LONGER than the real word, because the hyphen becomes a pause rather than stress.
So those clips could not demonstrate their own point even in principle.

One case was an outright bug independent of that: `/prəˈvaɪdɪd ðət/ (chunk)` had
its IPA stripped and rendered as the single word **"(chunk)"** — the content
deleted, the label spoken.

WHAT THIS CHECKS — BOTH DIRECTIONS
----------------------------------
Negative: no `TTS.speak(...)` payload anywhere in the generated site contains an
error mark, a middle dot, a parenthetical delivery label, or a syllable split.

Positive: the visible page text still CONTAINS those error forms. Without this
half, the check would be satisfied by deleting the teaching content altogether —
which is the opposite of the intent. The fix was to change the CHANNEL, not to
remove the material.

Exit 0 = clean. Exit 1 = a violation, naming the page and the payload.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"

TTS_CALL = re.compile(r"TTS\.speak\('((?:[^'\\]|\\.)*)'")
ERROR_MARK = "\u274c"      # ❌
MIDDLE_DOT = "\u00b7"      # ·
META_LABEL = re.compile(r"\((?:separated|chunk|compressed|linked|blended|reduced)\)", re.I)

# NO hyphen-split rule here, on purpose. The first version of this check used
# `\b\w+-\w+-\w+` to catch `pro-vi-ded`, and it fired on 31 payloads containing
# `tongue-in-cheek` and `state-of-the-art` — ordinary English compounds that must
# be spoken. Verified across the whole site that every genuine syllable-split demo
# also carries a `(separated)` label or a middle dot, so the rule was redundant
# as well as wrong. A check that fires on correct content gets switched off within
# a month, which is worse than not having it.


def why_unspeakable(payload: str) -> str | None:
    if ERROR_MARK in payload:
        return "error form (❌) — spoken with no cue that it is wrong"
    if META_LABEL.search(payload):
        return "delivery meta-label — a note to the reader, not a word to say"
    if MIDDLE_DOT in payload:
        return "middle dot — demonstrates SEPARATED delivery, i.e. the wrong version"
    return None


def main() -> int:
    if not SITE.is_dir():
        print(f"FAIL: {SITE} not found")
        return 1

    pages = sorted(SITE.rglob("*.html"))
    spoken = 0
    violations: list[str] = []
    pages_displaying_errors = 0

    for page in pages:
        text = page.read_text(encoding="utf-8")
        rel = page.relative_to(SITE)

        payloads = [m.group(1) for m in TTS_CALL.finditer(text)]
        spoken += len(payloads)
        for payload in payloads:
            why = why_unspeakable(payload)
            if why:
                violations.append(f"  {rel}\n      payload: {payload[:110]}\n      why: {why}")

        # Does the VISIBLE text still teach the contrast? Strip the TTS payloads
        # first so a leftover in an onclick cannot be mistaken for page content.
        visible = TTS_CALL.sub("TTS.speak('')", text)
        if ERROR_MARK in visible:
            pages_displaying_errors += 1

    print(f"verify_spoken_is_correct_english: {len(pages)} pages, {spoken} TTS.speak calls")

    if violations:
        print(f"\nFAIL — {len(violations)} spoken payload(s) contain material the ear must not hear:\n")
        print("\n".join(violations[:25]))
        if len(violations) > 25:
            print(f"  ... and {len(violations) - 25} more")
        print("\nThe SCREEN should keep these; only TTS.speak() must drop them. "
              "See generate.spoken_words().")
        return 1

    # The positive half: deleting the content would also make the above pass.
    if pages_displaying_errors == 0:
        print("\nFAIL: no page DISPLAYS an ❌ contrast any more.\n"
              "      The point was to stop SPEAKING the error, not to delete the "
              "teaching material. If the curriculum genuinely dropped these, update "
              "this check deliberately.")
        return 1

    print(f"PASS: nothing unspeakable is spoken, and {pages_displaying_errors} pages "
          f"still display the ❌ contrast on screen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
