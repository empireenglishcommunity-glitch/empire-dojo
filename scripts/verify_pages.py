#!/usr/bin/env python3
"""Verify all generated HTML pages in site/ are well-formed and free of
unescaped injection-shaped content.

This formalizes the exact manual verification performed during the
2026-07-13 XSS fix (empire-dojo PR #10) into a permanent, automated CI
check. Runs against every HTML file in site/ (currently ~1,330 pages)
and exits non-zero if ANY page:

  1. Fails to parse with Python's html.parser (malformed HTML).
  2. Contains known injection-shaped substrings in raw page content
     OUTSIDE of the file's intentional <script> blocks (e.g. a rogue
     <script tag, javascript: protocol, or event handler attributes
     that aren't part of generate.py's own authored HTML).

This catches:
  - A future curriculum JSON value containing a stray < that breaks HTML
    structure because someone forgot to use esc_html().
  - A regression in generate.py that interpolates raw text where escaped
    text is expected.
  - Accidental XSS vectors in curriculum content (the same class of bug
    that PR #10 found and fixed).

Designed to run in CI (.github/workflows/dojo-verify.yml) with zero
external dependencies — only Python stdlib.
"""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent.parent / "site"

# Substrings that should NEVER appear in the page content OUTSIDE of
# intentional <script> blocks authored by generate.py. If curriculum
# text (which should always be escaped) somehow introduces these, it
# means esc_html() was bypassed.
INJECTION_PATTERNS_RAW = [
    "javascript:",   # JS protocol in href/src
    "onerror=",      # event handler injection (not authored by generate.py)
    "onload=",       # event handler injection (not authored by generate.py)
    "onfocus=",      # event handler injection (not authored by generate.py)
    "onmouseover=",  # event handler injection (not authored by generate.py)
]

# These event handlers ARE legitimately used by generate.py in the
# authored HTML template. We DON'T flag these in the raw scan.
# (onclick= and onchange= are the only ones generate.py uses.)


def strip_script_blocks(html: str) -> str:
    """Remove all content between <script...>...</script> tags.

    This leaves us with ONLY the HTML body/attribute content where
    injection-shaped substrings from curriculum data would land if
    escaping were bypassed. The <script> blocks themselves are authored
    by generate.py (not curriculum data) and legitimately contain JS.
    """
    return re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)


def verify_file(filepath: Path) -> list[str]:
    """Verify one HTML file. Returns a list of error strings (empty = OK)."""
    errors = []

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        return [f"  Cannot read file: {e}"]

    # Phase 1: html.parser structural check — does it parse at all?
    parser = HTMLParser()
    try:
        parser.feed(content)
    except Exception as e:
        errors.append(f"  html.parser raised exception: {e}")

    # Phase 2: injection pattern scan on non-script content
    # Strip <script> blocks so we only check the HTML body/attributes
    body_content = strip_script_blocks(content)
    body_lower = body_content.lower()

    for pattern in INJECTION_PATTERNS_RAW:
        if pattern in body_lower:
            # Find approximate location for the error message
            idx = body_lower.index(pattern)
            snippet = body_content[max(0, idx - 30):idx + len(pattern) + 30]
            errors.append(
                f"  Injection pattern '{pattern}' in non-script content: "
                f"...{snippet!r}..."
            )

    # Phase 3: check for unexpected <script tags in the body
    # After stripping known script blocks, there should be NO remaining
    # <script occurrences. If there are, it means curriculum data
    # injected a rogue <script> tag that html.parser parsed as a real
    # tag (our strip_script_blocks already removed it from the content,
    # so we need to check differently).
    #
    # Better approach: count <script in the original, compare to expected.
    # generate.py produces at most 4 <script tags per page:
    #   1. <script>...has-token no-flash gate check...</script> (in <head>,
    #      always — Darb Phase 0's flash fix; runs before first paint)
    #   2. <script src="/js/app.js"></script>  (always present)
    #   3. <script>...content-gate token validation...</script> (always)
    #   4. ONE page-specific inline <script> (vocab flashcards, or
    #      listening dictation + checkAnswer) — only on those page types.
    # So base pages (accent/shadowing/day-index) have 3; vocab/listening
    # have 4. Anything above 4 is suspicious (possible injection).
    script_count = len(re.findall(r"<script", content, re.IGNORECASE))
    if script_count > 4:
        errors.append(
            f"  Unexpected number of <script> tags: found {script_count} "
            f"(expected at most 4 — possible injection from curriculum data)"
        )

    return errors


def main():
    if not SITE_DIR.exists():
        print(f"ERROR: site/ directory not found at {SITE_DIR}", file=sys.stderr)
        sys.exit(1)

    html_files = sorted(SITE_DIR.rglob("*.html"))
    if not html_files:
        print(f"ERROR: no HTML files found in {SITE_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Verifying {len(html_files)} HTML pages in {SITE_DIR}...")

    total_errors = 0
    failed_files = []

    for filepath in html_files:
        errors = verify_file(filepath)
        if errors:
            rel = filepath.relative_to(SITE_DIR)
            failed_files.append((rel, errors))
            total_errors += len(errors)

    if failed_files:
        print(f"\nFAILED: {len(failed_files)} file(s) with {total_errors} error(s):\n")
        for rel, errors in failed_files[:20]:  # cap output for readability
            print(f"  {rel}:")
            for e in errors[:5]:
                print(f"    {e}")
            if len(errors) > 5:
                print(f"    ... and {len(errors) - 5} more")
        if len(failed_files) > 20:
            print(f"\n  ... and {len(failed_files) - 20} more files")
        print(f"\nTotal: {total_errors} error(s) in {len(failed_files)} file(s)")
        sys.exit(1)
    else:
        print(f"OK: all {len(html_files)} pages passed verification.")
        sys.exit(0)


if __name__ == "__main__":
    main()
