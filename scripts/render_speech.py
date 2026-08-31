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

PACE: NORMALISED PER VOICE, NOT LEFT AT speed=1.0
-------------------------------------------------
Kokoro voices differ by 1.84x at speed=1.0 (af_nicole 130 wpm, af_sky 230).
Left uncorrected, the same sentence would be read at wildly different speeds
depending only on which voice the cast assigned to that surface, and af_nicole
pages would feel broken. Every clip is therefore rendered at
    speed = SPEECH_TARGET_WPM / VOICE_WPM[voice]
so all voices deliver at a comparable rate.

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
import json
import os
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
R2_PREFIX = "speech"


def speed_for_voice(voice):
    base = VOICE_WPM.get(voice, FALLBACK_VOICE_WPM)
    return max(SPEED_MIN, min(SPEED_MAX, SPEECH_TARGET_WPM / base))


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
    args = ap.parse_args()

    reg = registry()
    groups, load = shard_of(reg, args.shards)

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
                m["text"], voice=m["voice"],
                speed=round(speed_for_voice(m["voice"]), 4), lang="en-us")
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
        sorted(set(have) | {c for c in todo[:done]}), indent=0))
    print(f"  shard {args.shard}: rendered {done}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
