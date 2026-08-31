#!/usr/bin/env python3
"""The site must never invent a streak, a level, or a "today".

WHY THIS EXISTS
---------------
`Gamification._updateStreak()` used to keep its own streak in localStorage and
increment it on every page load. The 🔥 counter in the header — present on 6,303
pages — therefore went up for merely OPENING a page: no exercise, no submission,
no work. It was also per-device, and it rolled over on the UTC date while the
bot's day is Africa/Cairo.

Nothing caught it, and nothing was ever going to: the number rendered, the page
was valid HTML, every audio and clip-id gate passed, and the value was plausible.
A fabricated number is invisible to every check that only asks "did something
render?".

WHAT THIS CHECKS
----------------
1. No streak is read from or written to localStorage.
2. No "today"/date-key is derived from the browser clock in the shipped JS.
   The browser is the one participant that cannot know when the programme's day
   ends — that is `config.TIMEZONE` on the bot, and it has already changed once
   (Asia/Dubai -> Africa/Cairo, 2026-08-31).
3. The streak element is only written from authoritative API data.

WHAT THIS DELIBERATELY ALLOWS
-----------------------------
`Date.now()` for ELAPSED time (timers, cooldown countdowns, SRS queue stamps) is
fine and is used correctly in several places: a duration does not depend on which
calendar day anyone thinks it is. `new Date(iso + 'T00:00:00')` for *formatting* a
date the server already decided is also fine — that parses in local time and is
read back with local getters, which round-trips safely. The failure mode being
guarded against is the browser DECIDING a calendar day, not displaying one.

Exit 0 = clean. Exit 1 = a violation, with the file and line.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

JS_DIR = Path(__file__).resolve().parent.parent / "site" / "js"

# (regex, why it is banned) — matched against non-comment JS source.
BANNED = [
    (
        re.compile(r"""localStorage\.(?:get|set)Item\(\s*['"][^'"]*streak[^'"]*['"]"""),
        "streak read/written from localStorage — the streak is the bot's, not the browser's. "
        "Use ConnectedProgress.data.streak.",
    ),
    (
        re.compile(r"""localStorage\.(?:get|set)Item\(\s*['"][^'"]*last_active[^'"]*['"]"""),
        "last-active date kept in localStorage — this is what let the page decide its own day.",
    ),
    (
        re.compile(r"new Date\(\s*\)\s*\.toISOString\(\s*\)"),
        "`new Date().toISOString()` derives TODAY from the browser's UTC clock. The "
        "programme's day is config.TIMEZONE on the bot (Africa/Cairo since 2026-08-31). "
        "Take the day from the API or do not compute one.",
    ),
    (
        re.compile(r"Date\.now\(\s*\)\s*-\s*86400000"),
        "'yesterday' computed in the browser — same problem as above.",
    ),
]


def strip_comments(src: str) -> str:
    """Remove /* */ and // comments so documentation about the defect does not
    trip the check that forbids the defect. Naive but sufficient: this file only
    needs to avoid false positives on prose, and string literals containing
    these exact patterns do not occur."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"^\s*//.*$", "", src, flags=re.M)
    return src


def main() -> int:
    if not JS_DIR.is_dir():
        print(f"FAIL: {JS_DIR} not found")
        return 1

    violations: list[str] = []
    files = sorted(JS_DIR.glob("*.js"))
    for path in files:
        raw = path.read_text(encoding="utf-8")
        code = strip_comments(raw)
        for pattern, why in BANNED:
            for m in pattern.finditer(code):
                line = code[: m.start()].count("\n") + 1
                violations.append(f"  {path.name}: {m.group(0)!r}\n      why: {why}")

    print(f"verify_no_invented_streak: scanned {len(files)} JS file(s) in site/js/")

    if violations:
        print("\nFAIL — the site is inventing state the bot owns:\n")
        print("\n".join(violations))
        return 1

    # Positive assertion: the streak element must still be driven from API data,
    # otherwise "no violations" could just mean the feature was deleted.
    app = (JS_DIR / "app.js").read_text(encoding="utf-8")
    if "streak-display" not in app:
        print("FAIL: nothing writes #streak-display — the header streak was lost entirely.")
        return 1
    if "ConnectedProgress.data" not in app:
        print("FAIL: #streak-display is not driven from ConnectedProgress.data "
              "(the authoritative /api/progress payload).")
        return 1
    if "empire:progress-loaded" not in app:
        print("FAIL: no listener for empire:progress-loaded — the real streak arrives "
              "after init(), so without it the header would never populate.")
        return 1

    print("PASS: no invented streak, no browser-derived 'today', and #streak-display "
          "is driven from the authoritative API payload.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
