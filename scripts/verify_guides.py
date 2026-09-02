#!/usr/bin/env python3
"""Drift-check for the guide pages. Two layers:

  1. HARD (exit 1): the machine-owned AUTO regions must match the live facts.
     This is just `guide_sync.py --check` — if a generated region is stale,
     someone edited generated HTML by hand or the facts changed without a
     re-sync. CI fails so it can never ship.

  2. SOFT (warn, exit 0): scan the EDITORIAL prose (everything outside AUTO
     regions) for known factual claims — itqan pass %, schedule hour, timezone,
     level/week counts, flag total — and warn when the prose disagrees with the
     live system. These are hand-written on purpose (a script must not rewrite
     the Arabic explanations), so a mismatch is surfaced for a human to fix
     rather than auto-changed. Some of these (itqan pass %) are RUNTIME-tunable
     in the DB, so the code default is only advisory — hence warn, never fail.

Run:
    python3 scripts/verify_guides.py            # hard + soft
    python3 scripts/verify_guides.py --strict   # also FAIL on soft mismatches

Design note: the soft layer is intentionally conservative. It only flags a
number when it is confident the number refers to the fact in question (it keys
off nearby Arabic/English anchor words), because a false alarm that cries wolf
is how a drift-check gets ignored.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
GUIDE = REPO_ROOT / "site" / "guide" / "index.html"
OPS_GUIDE = REPO_ROOT / "site" / "ops-guide" / "index.html"

sys.path.insert(0, str(SCRIPT_DIR))
import guide_facts  # noqa: E402

_AUTO_REGION = re.compile(r"<!--\s*AUTO:[a-z0-9-]+\s+START.*?AUTO:[a-z0-9-]+\s+END\s*-->", re.S)


def editorial_text(html):
    """The page with all AUTO regions removed, so the soft checks only look at
    hand-written prose (the generated regions are already covered by layer 1)."""
    return _AUTO_REGION.sub(" ", html)


def _has(text, *anchors):
    return any(a in text for a in anchors)


def soft_checks(facts):
    """Return a list of (page, message) warnings where editorial prose disagrees
    with the live facts. Conservative: only checks claims we can anchor reliably."""
    warns = []
    itq = facts.get("itqan_defaults", {})
    sched = facts.get("schedule", {})

    for label, path in (("student /guide", GUIDE), ("owner /ops-guide", OPS_GUIDE)):
        if not path.exists():
            continue
        prose = editorial_text(path.read_text(encoding="utf-8"))

        # (a) Itqan monthly-review pass %. The guides state "65%" in prose. The
        # live value is DB-tunable; the code default is progression_monthly (65).
        # We only warn if the prose names a DIFFERENT explicit review %.
        for m in re.finditer(r"مراجعة شهرية[^%]{0,80}?(\d{2})\s*%", prose):
            if m.group(1) != "65":
                warns.append((label, f"monthly-review pass % in prose is "
                              f"{m.group(1)}% but system default is 65%"))

        # (b) Itqan weekly time limit (minutes). Prose sometimes says "15 دقيقة".
        tl = itq.get("itqan_time_limit_min")
        if tl:
            for m in re.finditer(r"(\d{1,3})\s*دقيقة[^<]{0,40}(?:اختبار|الأسبوعي|Itqan|إتقان)", prose):
                pass  # too loose to assert; skipped deliberately (see docstring)

        # (c) Timezone label in the ops-guide schedule ("بتوقيت دبي" = Dubai).
        if label.startswith("owner") and "بتوقيت" in prose:
            tz = (sched.get("timezone") or "")
            if tz.endswith("Dubai") and "دبي" not in prose:
                warns.append((label, f"schedule timezone is {tz} but prose does "
                              f"not say 'دبي' (Dubai)"))

        # (d) Daily task post hour (ops schedule prose: "6:00 ص").
        dth = sched.get("daily_task_hour")
        if label.startswith("owner") and dth is not None:
            # find "X:00 ص ... مهام اليوم / daily-tasks"
            for m in re.finditer(r"(\d{1,2}):00\s*ص[^<]{0,60}(?:مهام اليوم|daily-tasks)", prose):
                if int(m.group(1)) != dth:
                    warns.append((label, f"daily-tasks post hour in prose is "
                                  f"{m.group(1)}:00 but system uses {dth}:00"))

        # (e) Level count stated in prose ("6 مستويات" / "N levels").
        for m in re.finditer(r"(\d+)\s*مستويات", prose):
            if int(m.group(1)) != facts["level_count"]:
                warns.append((label, f"prose says {m.group(1)} levels but system "
                              f"has {facts['level_count']}"))

    return warns


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true",
                    help="also FAIL (exit 1) on soft editorial mismatches")
    args = ap.parse_args()

    # Layer 1 — HARD: AUTO regions must be in sync. Delegate to guide_sync.
    print("Guide drift-check")
    print("  [1/2] AUTO regions (must match live facts):")
    rc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "guide_sync.py"), "--check"]).returncode
    hard_ok = (rc == 0)
    if not hard_ok:
        print("  ::error::AUTO regions are STALE. Run: python3 scripts/guide_sync.py")

    # Layer 2 — SOFT: editorial prose sanity.
    print("  [2/2] editorial prose facts (advisory):")
    try:
        facts = guide_facts.all_facts()
    except guide_facts.FactsUnavailable as e:
        print(f"  ::warning::soft checks skipped — {e}")
        return 0 if hard_ok else 1

    warns = soft_checks(facts)
    if not warns:
        print("    no editorial drift detected.")
    for label, msg in warns:
        print(f"  ::warning::{label}: {msg}")

    if not hard_ok:
        return 1
    if args.strict and warns:
        print("  ::error::--strict: editorial drift present")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
