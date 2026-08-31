#!/usr/bin/env python3
"""Render the speech registry (every UI utterance) with Kokoro and push to R2.

WHY R2 AND NOT site/audio/
--------------------------
Cloudflare Pages caps a deployment at 20,000 files on the free plan. site/
already holds 8,056 (6,948 pages + 1,095 broadcast clips), so adding these
9,360 would reach 17,416 — under the cap, but with almost no headroom on a
site that gains pages every week — and it would add ~158 MB to a repo whose
.git is already 326 MB. Cloudflare's own guidance for this case is to serve
static assets from R2, which is also why the bucket exists.

So these clips live at {PUBLIC_BASE}/speech/<clip-id>.mp3 and are NOT committed.
What IS committed is scripts/speech-rendered.json — the list of clip ids that
exist on R2 — so `speech_registry.py --check` can gate on it without needing
R2 credentials, and so the set of rendered clips is auditable in git history.

SHARDING IS BY WORD COUNT, NOT BY SURFACE
-----------------------------------------
The obvious split is one job per surface. It does not work: `accent` is 1,170
clips but 42,199 words (long sentences), an estimated 5.9 h of render against
GitHub's 6 h job cap, while `review` is 297 words and finishes instantly.
Clips are therefore assigned to shards by descending word count, longest
first into whichever shard is currently lightest, which balances total WORDS
per shard — the thing that actually costs time.

PACE: RENDERED AT speed=1.0, AND SLOWED AT PLAYBACK INSTEAD
-----------------------------------------------------------
This originally normalised per voice — speed = SPEECH_TARGET_WPM / VOICE_WPM —
so that Kokoro's 1.84x spread between voices did not make the same sentence fast
on one surface and slow on another. That was a mistake, and a student caught it:
Mai reported that "She is a student." on a1/week1/day1/grammar sounded noisy and
almost mispronounced.

She was right. SLOWING KOKORO DOWN CORRUPTS PHONEMES. Rendering that sentence as
am_michael at speed 0.829 produces a spurious leading syllable — an independent
ASR transcribes the clip as "as she is a student". At speed 1.0 the same voice
and text transcribe cleanly. Measured across 7 voices x 8 short sentences:

    normalised speed (0.70-1.23)    16/56 wrong   (29%)
    speed 1.0                        0/56 wrong   ( 0%)

af_sky at 0.696 was worst at 6/8. af_nicole at 1.231 — the only voice being
sped UP — was clean, which is what identifies slowing as the cause rather than
any departure from 1.0.

Nothing else caught this. The waveforms were clean: no clipping, sane peaks,
plausible durations, correct clip ids, and verify_audio_pace only measures the
level-scoped broadcast clips. Every existing check passed on audio that says the
wrong words, because no check listened. scripts/audit_speech_intelligibility.py
now exists for exactly that.

The rate difference this reintroduces does not need fixing here: each surface
has ONE voice, so delivery is consistent within a page, and the resolver already
applies the per-call-site slowdown with audio.playbackRate (0.7 for vocabulary,
0.6 for dictation), which browsers pitch-correct and which does not touch
phonemes. Slowing at PLAYBACK is safe; slowing at SYNTHESIS is not.

The per-call-site SLOWDOWN is deliberately NOT baked in. Call sites ask for
slower delivery for learners — TTS.speak(word.word, 0.7) for vocabulary,
TTS.speak(item.say, 0.6) for dictation. Baking that into the audio would mean
either a separate clip per rate (multiplying the render) or losing the
pedagogy. Instead the clip is rendered at a neutral rate and the player sets
audio.playbackRate, which browsers pitch-correct. That also keeps `rate` out
of the clip id, so the hash contract with site/js/speech-id.js stays as it is.

Usage:
    render_speech.py --model-dir ./kokoro --shard 0 --shards 12
    render_speech.py --plan --shards 12        # show the split, render nothing
"""
import argparse
import html
import json
import os
import re
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent
RENDERED_MANIFEST = SCRIPT_DIR / "speech-rendered.json"

sys.path.insert(0, str(SCRIPT_DIR))
from audio_pace import SPEED_MAX, SPEED_MIN, VOICE_WPM  # noqa: E402
from speech_registry import SITE, build_registry, scan  # noqa: E402
from voice_cast import load_cast, validate_cast  # noqa: E402

# Normal conversational delivery. These are practice prompts, not the
# level-scoped extended-listening clips (which keep their own per-level targets
# in audio_pace.py), so one neutral target is right here.
SPEECH_TARGET_WPM = 160.0
FALLBACK_VOICE_WPM = 210.0

# Every clip is rendered at exactly this. See the module docstring: any value
# below 1.0 corrupts phonemes in Kokoro, which is what shipped a clip saying
# "as she is a student".
RENDER_SPEED = 1.0

# THE PREFIX IS VERSIONED, and must be bumped whenever the AUDIO for an
# unchanged text changes.
#
# A clip id is sha256(voice|text) — it says nothing about the audio bytes. So
# re-rendering produces different audio at an identical URL, and these objects
# are uploaded with `max-age=31536000, immutable`, plus the service worker
# caches anything ending .mp3 cache-first and never revalidates. Overwriting in
# place would therefore leave existing students on the old, faulty audio for up
# to a year while the bucket looked correct.
#
# v2: rendered at speed 1.0 after per-voice slowing was found to corrupt
#     phonemes (29% of sampled clips mis-spoken).
# v1: initial render, per-voice speed normalisation — DEFECTIVE, superseded.
R2_PREFIX = "speech/v2"


def speed_for_voice(voice):
    """Kept only so the old normalisation is still inspectable and testable.

    NOT used for rendering any more — see RENDER_SPEED and the module docstring.
    """
    base = VOICE_WPM.get(voice, FALLBACK_VOICE_WPM)
    return max(SPEED_MIN, min(SPEED_MAX, SPEECH_TARGET_WPM / base))


# Notation that belongs on the SCREEN and not in the ear. The accent drills show
# IPA next to the spelling so a student can see the sound; Kokoro reads the
# characters, so the clip said "measure slash edge slash major" instead of
# "measure, major". 63 clips were affected, all on the accent surface — which is
# the pronunciation model students are asked to imitate, so it is the worst
# possible place for it.
# Spans may contain spaces — /prəˈvaɪdɪd ðət/ is one unit — so this must not
# stop at whitespace, or the slashes survive and the IPA inside gets mangled
# into "/prvadd t/" instead of removed.
_IPA_SPAN = re.compile(r"/[^/]{1,48}/")
# NON-ASCII ONLY, and asserted below. An earlier version of this set was written
# by transcribing IPA diphthongs by hand and picked up the plain letters "e" and
# "a", so _IPA_WORD matched almost every English word and "She is a student."
# rendered as "is". Any ASCII letter in here silently deletes real speech.
_IPA_CHARS = "ʒʃθðŋæəɪʊɔɑːˈˌɡʧʤʔɜɐʌ"
assert all(ord(c) > 127 for c in _IPA_CHARS), \
    "_IPA_CHARS must contain no ASCII: it would delete ordinary words"
# A whole WORD is dropped if it contains IPA, rather than having the IPA letters
# deleted from it: stripping characters turned "wəz" into "wz" and "thən" into
# "thn", which Kokoro then dutifully tries to pronounce.
_IPA_WORD = re.compile(r"\S*[" + _IPA_CHARS + r"]\S*")
_STRIP_CHARS = re.compile(
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2190-\u21FF]")   # emoji, arrows
_TIDY = [
    (re.compile(r"\(\s*\)"), " "),          # brackets emptied by the above
    (re.compile(r"\s*,\s*,+"), ","),        # commas left adjacent
    (re.compile(r"^[\s,;:.]+"), ""),        # leading punctuation
    (re.compile(r"\s+([,.;:?!])"), r"\1"),  # space before punctuation
    (re.compile(r"\s{2,}"), " "),
]


def speakable(text: str) -> str:
    """What Kokoro should SAY for this text.

    Deliberately separate from the clip id, which hashes the ORIGINAL on-screen
    text — the browser computes the id from what it displays and cannot know
    about this. So the audio can be cleaned without touching the hash contract
    in site/js/speech-id.js, and no clip id changes.
    """
    # HTML entities first. The generator escapes text for the page, and the
    # escaped form reaches the TTS: 57 clips (43 reading, 14 mediation) carried
    # 126 instances of &quot;, so a student heard the entity read out where a
    # quotation mark should have been silent. Unescaping is safe here because
    # this string is only ever spoken, never inserted into HTML.
    out = html.unescape(text or "")
    out = _IPA_SPAN.sub(" ", out)
    out = _IPA_WORD.sub(" ", out)
    out = _STRIP_CHARS.sub("", out)
    for pat, rep in _TIDY:
        out = pat.sub(rep, out)
    out = out.strip(" ,;:")
    # If stripping removed effectively everything, keep the original rather than
    # render silence — a clip that says the wrong thing is still better than a
    # clip that says nothing and looks like a broken file.
    return out if len(out.split()) >= 1 else (text or "")


def registry():
    cast = load_cast()
    validate_cast(cast)
    found, _pages, _voices = scan(SITE, cast)
    return build_registry(found)


def shard_of(reg, shards):
    """Balance shards by total WORDS. Longest clip first into the lightest
    shard — a greedy fit, which is enough for a spread this smooth and is
    deterministic, so a re-run puts every clip in the same shard."""
    load = [0] * shards
    out = [[] for _ in range(shards)]
    for cid in sorted(reg, key=lambda c: (-reg[c]["words"], c)):
        i = load.index(min(load))
        out[i].append(cid)
        load[i] += max(reg[cid]["words"], 1)
    return out, load


def r2_client():
    import boto3
    from botocore.config import Config

    def e(n):
        v = os.environ.get(n, "").strip()   # secrets arrive with trailing \n
        if not v:
            sys.exit(f"::error::missing required env {n}")
        return v

    return boto3.client(
        "s3",
        endpoint_url=f"https://{e('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
        aws_access_key_id=e("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=e("R2_SECRET_ACCESS_KEY"),
        region_name="auto", config=Config(signature_version="s3v4"))


def already_on_r2(s3, bucket):
    """Every speech clip id currently in the bucket, so a re-run resumes rather
    than re-rendering. list_objects_v2 is paginated at 1,000 keys — missing that
    would silently re-render everything past the first page."""
    have, token = set(), None
    while True:
        kw = dict(Bucket=bucket, Prefix=f"{R2_PREFIX}/")
        if token:
            kw["ContinuationToken"] = token
        r = s3.list_objects_v2(**kw)
        for o in r.get("Contents", []):
            name = o["Key"].split("/")[-1]
            if name.endswith(".mp3") and o["Size"] > 0:
                have.add(name[:-4])
        if not r.get("IsTruncated"):
            return have
        token = r.get("NextContinuationToken")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--bucket", default=os.environ.get("AUDIO_BUCKET", "empire-audio"))
    ap.add_argument("--plan", action="store_true", help="show the split only")
    ap.add_argument("--limit", type=int, help="render at most N clips (throughput probe)")
    ap.add_argument("--ids", nargs="*",
                    help="re-render exactly these clip ids, ignoring what is "
                         "already in the bucket. For fixing specific clips "
                         "without a full --regenerate pass.")
    args = ap.parse_args()

    reg = registry()
    groups, load = shard_of(reg, args.shards)

    if args.ids:
        todo = [c for c in args.ids if c in reg]
        missing = [c for c in args.ids if c not in reg]
        if missing:
            print(f"  ::warning::{len(missing)} id(s) are not in the registry, "
                  f"skipped: {missing[:5]}")
        print(f"  targeted re-render of {len(todo)} clip(s)")
        return _render(todo, reg, args)

    if args.plan:
        print(f"  {'shard':>6}{'clips':>8}{'words':>9}{'est min audio':>15}")
        for i, (g, w) in enumerate(zip(groups, load)):
            print(f"  {i:>6}{len(g):>8}{w:>9}{w / 150:>15.0f}")
        print(f"\n  total {len(reg)} clips, {sum(load)} words, "
              f"{sum(load)/150:.0f} min of audio")
        return 0

    mine = groups[args.shard]
    print(f"  shard {args.shard} of {args.shards}: {len(mine)} clips, "
          f"{load[args.shard]} words")

    s3 = r2_client()
    have = already_on_r2(s3, args.bucket)
    print(f"  already on R2: {len(have)} clip(s)")
    todo = [c for c in mine if c not in have]
    if args.limit:
        todo = todo[:args.limit]
    print(f"  to render: {len(todo)}")
    if not todo:
        print("  nothing to do")
        return 0

    return _render(todo, reg, args, have=have)


def _render(todo, reg, args, have=None):
    """Synthesise and upload `todo`. Shared by the sharded path and --ids."""
    have = have if have is not None else set()
    if not todo:
        print("  nothing to do")
        return 0
    s3 = r2_client()

    import numpy as np  # noqa: F401  (kokoro returns numpy arrays)
    import soundfile as sf
    from kokoro_onnx import Kokoro
    md = Path(args.model_dir)
    kokoro = Kokoro(str(md / "kokoro-v1.0.onnx"), str(md / "voices-v1.0.bin"))

    out_dir = Path("speech_out")
    out_dir.mkdir(exist_ok=True)
    done, failed, t0, audio_sec = 0, 0, time.time(), 0.0
    for n, cid in enumerate(todo, 1):
        m = reg[cid]
        try:
            samples, sr = kokoro.create(
                speakable(m["text"]), voice=m["voice"],
                speed=RENDER_SPEED, lang="en-us")
            p = out_dir / f"{cid}.mp3"
            sf.write(str(p), samples, sr)
            s3.put_object(Bucket=args.bucket, Key=f"{R2_PREFIX}/{cid}.mp3",
                          Body=p.read_bytes(), ContentType="audio/mpeg",
                          # Immutable: the id IS the hash of voice+text, so a
                          # changed text is a different object. Safe to cache
                          # hard, unlike the position-named broadcast clips.
                          CacheControl="public, max-age=31536000, immutable")
            p.unlink()
            audio_sec += len(samples) / sr
            done += 1
        except Exception as exc:                       # noqa: BLE001
            failed += 1
            print(f"    FAILED {cid} ({m['voice']}): {exc}")
            if failed > 25:
                print("::error::too many failures — stopping")
                break
        if n % 100 == 0 or n == len(todo):
            el = time.time() - t0
            print(f"    [{n}/{len(todo)}] {done} ok, {failed} failed, "
                  f"{el/60:.1f} min elapsed, "
                  f"{audio_sec/60:.1f} min audio "
                  f"({audio_sec/el if el else 0:.2f}x realtime)")

    Path(f"shard-{args.shard}.json").write_text(json.dumps(
        sorted(set(have) | set(todo[:done])), indent=0))
    print(f"  shard {args.shard}: rendered {done}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
