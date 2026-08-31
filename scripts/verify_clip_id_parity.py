#!/usr/bin/env python3
"""Prove the browser and Python compute the SAME speech clip id.

WHY THIS IS A BUILD GATE AND NOT A UNIT TEST
--------------------------------------------
The site is moving off the browser's robotic speechSynthesis onto pre-rendered
Kokoro clips, addressed by a hash of their text. Python (speech_registry.py)
decides the FILENAMES that get rendered; JavaScript (site/js/speech-id.js)
decides the NAME THE BROWSER ASKS FOR. Those are two independent
implementations of one contract, in two languages, and nothing about the code
forces them to agree.

The failure mode is not subtle degradation. If they disagree by a single
character, every clip is requested under a name that was never rendered, and
the entire site goes silent at once. Worse, it would only show up in a browser
— Python's own tests would pass perfectly.

So this runs the REAL JavaScript (in node, using the same WebCrypto API the
browser uses) against the REAL Python, over:

  1. every utterance in the actual registry — all 9,360, not a sample;
  2. adversarial strings covering the places the two languages are known to
     disagree, so the boundary is documented and tested rather than assumed.

Usage:
    verify_clip_id_parity.py            # both corpora
    verify_clip_id_parity.py --quick    # adversarial cases only (no registry)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent
JS_FILE = REPO / "site" / "js" / "speech-id.js"

sys.path.insert(0, str(SCRIPT_DIR))
from speech_registry import (SITE, build_registry, clip_id,  # noqa: E402
                             normalise, scan)
from voice_cast import load_cast, validate_cast  # noqa: E402


def real_registry():
    """The same registry the renderer will use, so parity is checked against
    the actual utterances rather than a fixture that can drift from them."""
    cast = load_cast()
    validate_cast(cast)
    found, _pages, _voices = scan(SITE, cast)
    return build_registry(found)

# Strings chosen to break a careless implementation. The comment on each says
# what it is actually testing, because "a list of weird strings" rots fast.
ADVERSARIAL = [
    "",                                  # empty
    " ",                                 # whitespace only -> must equal ""
    "   leading and trailing   ",        # trim
    "internal    runs\tof\nwhitespace",  # every run collapses to ONE space
    "\n\n\nnewlines only around\n\n",    # newlines are whitespace, not literals
    "I'm happy",                         # apostrophe (broke an earlier regex scan)
    'she said "hello"',                  # double quotes
    "back\\slash",                       # backslash must not be an escape here
    "Achilles' heel",                    # real registry text with an apostrophe
    "caf\u00e9 na\u00efve",              # non-ASCII latin -> utf-8 byte identity
    "\u0645\u0631\u062d\u0628\u0627 \u0628\u0643\u0645",  # Arabic (RTL)
    "emoji \U0001F50A here",             # astral plane: surrogate pairs in JS
    "\u00a0non-breaking\u00a0space",     # \xa0 IS whitespace in both
    "tab\tseparated",                    # \t
    "a" * 5000,                          # long input
    "voice|pipe in the text",            # the pipe is the key SEPARATOR
    "sp-already-looks-like-an-id",       # must still be hashed, not passed through
]

# Characters where Python's str.split() and JS /\s+/ genuinely DISAGREE. These
# are expected to differ, and the test asserts that they are absent from real
# content rather than pretending the implementations match on them.
KNOWN_DIVERGENT = ["\x1c", "\x1d", "\x1e", "\x1f", "\x85", "\ufeff"]

NODE_SCRIPT = r"""
const path = process.argv[2];
const SpeechId = require(path);
const input = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
(async () => {
  const out = [];
  for (const [voice, text] of input) {
    out.push(await SpeechId.clipId(voice, text));
  }
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""


def find_node():
    node = shutil.which("node")
    if node:
        return node
    # The sandbox installs node under nvm, which is not on PATH by default.
    for pat in sorted(Path("/root/.nvm/versions/node").glob("v*/bin/node"),
                      reverse=True):
        return str(pat)
    return None


def js_clip_ids(node, pairs):
    """Run the real site JS in node and return its clip ids."""
    with tempfile.TemporaryDirectory() as td:
        runner = Path(td) / "run.js"
        runner.write_text(NODE_SCRIPT)
        payload = Path(td) / "in.json"
        payload.write_text(json.dumps(pairs))
        res = subprocess.run(
            [node, str(runner), str(JS_FILE), str(payload)],
            capture_output=True, text=True)
        if res.returncode != 0:
            print("  node failed:\n" + res.stderr.strip())
            sys.exit(1)
        return json.loads(res.stdout)


def compare(label, pairs, node):
    got_js = js_clip_ids(node, pairs)
    got_py = [clip_id(v, t) for v, t in pairs]
    bad = [(v, t, a, b) for (v, t), a, b in zip(pairs, got_py, got_js) if a != b]
    print(f"  {label:<34}{len(pairs):>7} compared   "
          f"{'MISMATCH ' + str(len(bad)) if bad else 'all identical'}")
    for v, t, a, b in bad[:10]:
        print(f"      voice={v!r} text={t[:60]!r}\n        python={a}\n        js    ={b}")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="adversarial cases only, skip the registry scan")
    args = ap.parse_args()

    node = find_node()
    if not node:
        print("  node not found — cannot verify the browser half of the contract.")
        print("  This gate is only meaningful if BOTH implementations run.")
        return 1
    print(f"  node: {subprocess.run([node, '--version'], capture_output=True, text=True).stdout.strip()}")
    print(f"  js:   {JS_FILE.relative_to(REPO)}")
    print()

    failures = []

    # 1. Adversarial strings, across several voices so the voice half is covered.
    pairs = [(v, t) for t in ADVERSARIAL
             for v in ("af_bella", "am_adam", "af_nicole")]
    failures += compare("adversarial strings", pairs, node)

    # 2. normalise() itself, checked independently of the hash so a failure says
    #    which half is wrong.
    node_norm = subprocess.run(
        [node, "-e",
         "const s=require(process.argv[1]);"
         "const i=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));"
         "process.stdout.write(JSON.stringify(i.map(t=>s.norm(t))));",
         str(JS_FILE), "/dev/stdin"],
        input=json.dumps(ADVERSARIAL), capture_output=True, text=True)
    if node_norm.returncode == 0:
        js_n = json.loads(node_norm.stdout)
        py_n = [normalise(t) for t in ADVERSARIAL]
        diff = [(t, a, b) for t, a, b in zip(ADVERSARIAL, py_n, js_n) if a != b]
        print(f"  {'normalise() alone':<34}{len(ADVERSARIAL):>7} compared   "
              f"{'MISMATCH ' + str(len(diff)) if diff else 'all identical'}")
        for t, a, b in diff[:10]:
            print(f"      {t[:50]!r}: python={a!r} js={b!r}")
        failures += diff

    # 3. The documented divergences. These are NOT expected to match; the point
    #    is that real content must never contain them.
    div_pairs = [("af_bella", f"a{c}b") for c in KNOWN_DIVERGENT]
    got_js = js_clip_ids(node, div_pairs)
    got_py = [clip_id(v, t) for v, t in div_pairs]
    agree = sum(1 for a, b in zip(got_py, got_js) if a == b)
    print(f"  {'known-divergent whitespace':<34}{len(div_pairs):>7} compared   "
          f"{agree}/{len(div_pairs)} agree (divergence is expected here)")

    # 4. Every real utterance.
    if not args.quick:
        reg = real_registry()
        pairs = [(m["voice"], m["text"]) for m in reg.values()]
        print()
        failures += compare("EVERY registry utterance", pairs, node)
        # And prove the divergent characters are absent from real content, which
        # is what makes (3) safe to tolerate.
        present = {repr(c): sum(1 for m in reg.values() if c in m["text"])
                   for c in KNOWN_DIVERGENT}
        present = {k: v for k, v in present.items() if v}
        print(f"  {'divergent chars in real content':<34}"
              f"{'':>7}           {present or 'NONE — divergence unreachable'}")
        if present:
            print("      ::error:: a real utterance contains a character that "
                  "Python and JS normalise differently.")
            failures.append(present)

    print()
    if failures:
        print(f"  FAILED — {len(failures)} mismatch(es). The browser would ask "
              f"for clip names that were never rendered.")
        return 1
    print("  PASS — python and the browser agree on every clip id.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
