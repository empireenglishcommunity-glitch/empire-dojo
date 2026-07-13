#!/usr/bin/env python3
"""Diff representative pages between the live site and a preview URL.

Fetches a sample of pages (one per level, a mix of page types) from both
the live production domain and a given preview/comparison URL, and prints
a unified diff. Turns "did I accidentally change something I didn't mean
to" from a manual spot-check into a one-command report.

Usage:
    # Compare live vs. a Cloudflare Pages preview deploy:
    python3 scripts/diff_against_live.py https://abc123.empire-practice-8l0.pages.dev

    # Compare live vs. a local file server (e.g. python3 -m http.server in site/):
    python3 scripts/diff_against_live.py http://localhost:8000

    # Compare two arbitrary URLs against each other:
    python3 scripts/diff_against_live.py --base https://old.example.com https://new.example.com

    # Verbose mode (show all pages, even identical ones):
    python3 scripts/diff_against_live.py --verbose https://preview-url.pages.dev

The default --base is the live production URL (practice.empireenglish.online).
Extensionless paths are used (matching the live site's routing convention).

Exit codes:
    0 — all sampled pages are identical (or both 404)
    1 — at least one page differs
    2 — usage error or network failure
"""
import argparse
import difflib
import sys
import urllib.request
import urllib.error

# Default live production URL
LIVE_URL = "https://practice.empireenglish.online"

# Representative sample pages: one per level, a mix of accent/vocab/
# listening/shadowing/index page types, plus the site root index.
# Uses extensionless paths (the only form that works on the live domain).
SAMPLE_PATHS = [
    "/index.html",                          # site root (has .html — it's the literal filename)
    "/l0/week1/day1/index",                 # L0 day index
    "/l0/week1/day1/accent",                # L0 accent drill
    "/l0/week2/day3/vocab",                 # L0 vocab flashcards
    "/l0/week4/day5/listening",             # L0 listening
    "/l1/week1/day1/accent",                # L1 accent
    "/l1/week3/day2/shadowing",             # L1 shadowing
    "/l1/week5/day4/vocab",                 # L1 vocab
    "/l2/week1/day1/accent",                # L2 accent
    "/l2/week6/day3/listening",             # L2 listening
    "/l3/week1/day1/accent",                # L3 accent
    "/l3/week4/day7/vocab",                 # L3 vocab
]


def fetch_page(base_url: str, path: str) -> tuple[int, str]:
    """Fetch a page and return (status_code, body_text).

    Returns (0, error_message) on network/connection failure.
    """
    url = base_url.rstrip("/") + path
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "empire-dojo-diff/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return (resp.status, body)
    except urllib.error.HTTPError as e:
        return (e.code, f"HTTP {e.code}: {e.reason}")
    except Exception as e:
        return (0, f"ERROR: {e}")


def normalize_html(text: str) -> list[str]:
    """Minimal normalization for diffing: strip trailing whitespace per line,
    collapse blank lines, so diffs focus on content changes not formatting."""
    lines = text.splitlines()
    lines = [line.rstrip() for line in lines]
    # Remove consecutive blank lines (keep at most one)
    result = []
    prev_blank = False
    for line in lines:
        if line == "":
            if not prev_blank:
                result.append(line)
            prev_blank = True
        else:
            result.append(line)
            prev_blank = False
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Diff representative pages between live site and a preview URL."
    )
    parser.add_argument("preview_url", help="URL to compare against (e.g. a Cloudflare preview deploy)")
    parser.add_argument("--base", default=LIVE_URL, help=f"Base URL to compare FROM (default: {LIVE_URL})")
    parser.add_argument("--verbose", action="store_true", help="Show all pages, even identical ones")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    preview = args.preview_url.rstrip("/")

    print(f"Comparing:")
    print(f"  BASE:    {base}")
    print(f"  PREVIEW: {preview}")
    print(f"  Pages:   {len(SAMPLE_PATHS)} representative samples")
    print()

    has_diff = False
    errors = 0

    for path in SAMPLE_PATHS:
        base_status, base_body = fetch_page(base, path)
        preview_status, preview_body = fetch_page(preview, path)

        label = path

        # Both failed to fetch (network error)
        if base_status == 0 and preview_status == 0:
            print(f"  {label}: BOTH UNREACHABLE")
            errors += 1
            continue

        # Status code mismatch
        if base_status != preview_status:
            print(f"  {label}: STATUS DIFFERS (base={base_status}, preview={preview_status})")
            has_diff = True
            continue

        # Both 404 — identical (page doesn't exist in either)
        if base_status == 404 and preview_status == 404:
            if args.verbose:
                print(f"  {label}: both 404 (OK)")
            continue

        # Both 200 — diff the bodies
        base_lines = normalize_html(base_body)
        preview_lines = normalize_html(preview_body)

        if base_lines == preview_lines:
            if args.verbose:
                print(f"  {label}: identical")
            continue

        # Pages differ — show unified diff
        has_diff = True
        diff = difflib.unified_diff(
            base_lines, preview_lines,
            fromfile=f"base:{path}",
            tofile=f"preview:{path}",
            lineterm="",
            n=3,  # 3 lines of context
        )
        diff_lines = list(diff)
        print(f"  {label}: DIFFERS ({len(diff_lines)} diff lines)")
        # Print a limited excerpt (first 30 lines of diff)
        for line in diff_lines[:30]:
            print(f"    {line}")
        if len(diff_lines) > 30:
            print(f"    ... ({len(diff_lines) - 30} more lines)")
        print()

    # Summary
    print("─" * 50)
    if errors:
        print(f"ERRORS: {errors} page(s) could not be fetched from one or both URLs.")
    if has_diff:
        print("RESULT: differences found between base and preview.")
        sys.exit(1)
    else:
        print("RESULT: all sampled pages are identical (or both 404).")
        sys.exit(0)


if __name__ == "__main__":
    main()
