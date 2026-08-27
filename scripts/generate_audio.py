#!/usr/bin/env python3
"""Generate Kokoro TTS audio clips for the practice platform's shadowing pages.

Reads audio-manifest.json (produced by generate.py) and calls a self-hosted
Kokoro TTS server to synthesize one MP3 per shadowing passage, matching the
exact API pattern already proven in production for the placement assessment
app (empireenglishcommunity-glitch/zai-placement-test, scripts/generate-listening-audio.ts).

This script does NOT deploy Kokoro itself — it expects the container to
already be running (the assessment app already runs one on the Hetzner
server at localhost:8880). If you're setting this up somewhere new, deploy
Kokoro first:

    mkdir -p /opt/kokoro-tts && cd /opt/kokoro-tts
    cat > docker-compose.yml <<'EOF'
    services:
      kokoro-tts:
        image: ghcr.io/remsky/kokoro-fastapi:latest-cpu
        container_name: kokoro-tts
        restart: unless-stopped
        ports:
          - "127.0.0.1:8880:8880"
        environment:
          - KOKORO_PORT=8880
          - KOKORO_DEFAULT_VOICE=af_heart
    EOF
    docker compose up -d

Usage:
    python3 generate_audio.py                    # generate missing clips only
    python3 generate_audio.py --regenerate        # regenerate every clip
    python3 generate_audio.py --voice am_adam     # use a specific voice
    python3 generate_audio.py --list-voices
    KOKORO_URL=http://77.42.43.250:8880 python3 generate_audio.py   # remote

Output:
    audio/{id}.mp3          e.g. audio/l1-w3-d2-shadow.mp3
    audio/manifest.json     metadata (voice, duration, generated date)
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent  # empire-dojo/ (parent of scripts/)
KOKORO_URL = os.environ.get("KOKORO_URL", "http://localhost:8880")
AUDIO_MANIFEST_PATH = SCRIPT_DIR / "audio-manifest.json"
OUTPUT_DIR = REPO_ROOT / "site" / "audio"  # deployed site lives here, NOT in scripts/
DEFAULT_VOICE = "af_heart"
RESPONSE_FORMAT = "mp3"

VOICES = [
    ("af_heart", "Female, warm, professional (DEFAULT)"),
    ("af_bella", "Female, clear, neutral"),
    ("af_nicole", "Female, calm, mature"),
    ("af_sarah", "Female, bright, energetic"),
    ("af_sky", "Female, young, friendly"),
    ("am_adam", "Male, professional, neutral"),
    ("am_michael", "Male, warm, conversational"),
    ("bf_emma", "British Female, clear, professional"),
    ("bf_isabella", "British Female, elegant"),
    ("bm_george", "British Male, authoritative"),
    ("bm_lewis", "British Male, warm"),
]
# VOICES is a list of (id, description) pairs, so membership tests need the ids
# on their own -- `voice not in VOICES` would be true for every real voice.
VOICE_IDS = {v for v, _ in VOICES}


def log(msg):
    print(f"  {msg}")


def log_header(msg):
    print(f"\n  --- {msg} {'-' * max(0, 50 - len(msg))}")


def list_voices():
    print("\n===========================================================")
    print("  KOKORO TTS -- Available Voices")
    print("===========================================================\n")
    for vid, desc in VOICES:
        marker = "*" if vid == DEFAULT_VOICE else " "
        print(f"  {marker} {vid:<14} -- {desc}")
    print("\n  Usage: python3 generate_audio.py --voice am_adam\n")


# Seconds to wait for one synthesis. Kokoro on CPU is roughly real-time, so the
# ceiling has to scale with how much speech is being asked for. The old fixed 60s
# was already close to the limit for the longest shadowing passage (244 words,
# ~100s of audio), and Phase 11D's extended-listening clips are deliberately
# long. A timeout is NOT a harmless retry here: the clip is simply never written,
# generate_audio.py exits 0 anyway, and the page silently degrades to the
# browser's robot voice for a full minute of listening comprehension.
REQUEST_TIMEOUT_BASE = 120
REQUEST_TIMEOUT_PER_WORD = 1.5
REQUEST_TIMEOUT_MAX = 900


def request_timeout_for(text):
    """A generous, length-aware socket timeout for one synthesis request."""
    words = len((text or "").split())
    return min(REQUEST_TIMEOUT_MAX,
               REQUEST_TIMEOUT_BASE + int(words * REQUEST_TIMEOUT_PER_WORD))


# PACE PER LEVEL, NORMALISED PER VOICE. See scripts/audio_pace.py for the full
# reasoning and the measured per-voice rates.
#
# This used to be a single `speed` per level, which assumed all eleven Kokoro
# voices speak at the same rate at speed=1.0. They do not -- there is a 1.84x
# spread, and af_nicole (130 wpm) is a severe outlier against bf_emma (238 wpm).
# The result was that delivery pace was decided by whichever voice a script
# named: six C1/C2 clips shipped at 120-142 wpm, at or below the A1 target, on
# the two descriptors (C1.R.1, C2.R.1) whose entire content is delivery speed.
#
# Pace is now expressed as a target wpm per level -- which is what the
# descriptors actually talk about -- and the per-clip speed is derived from the
# measured rate of the voice that clip names.
from audio_pace import pace_report, speed_for, target_wpm_for  # noqa: E402,F401


def call_kokoro(text, voice, speed=1.0):
    payload = json.dumps({
        "model": "kokoro",
        "input": text,
        "voice": voice,
        "response_format": RESPONSE_FORMAT,
        "speed": speed,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{KOKORO_URL}/v1/audio/speech",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=request_timeout_for(text)) as resp:
        return resp.read()


def check_health(voice):
    try:
        call_kokoro("test", voice)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--regenerate", action="store_true", help="Regenerate ALL clips, even ones that already exist")
    parser.add_argument("--voice", default=DEFAULT_VOICE, help="Kokoro voice id (default: af_heart)")
    parser.add_argument("--list-voices", action="store_true", help="Show available voices and exit")
    args = parser.parse_args()

    if args.list_voices:
        list_voices()
        return

    print("===========================================================")
    print("  EMPIRE ENGLISH -- Practice Platform Audio Generator")
    print("===========================================================")

    log_header("Configuration")
    log(f"Kokoro URL: {KOKORO_URL}")
    log(f"Voice:      {args.voice}")
    log(f"Output:     {OUTPUT_DIR}")
    log(f"Mode:       {'REGENERATE ALL' if args.regenerate else 'Generate missing only'}")

    # Print the pace matrix. This is the decision most likely to be wrong and
    # least likely to be noticed -- a clip at the wrong pace sounds fine in
    # isolation and silently breaks a delivery-speed descriptor.
    log_header("Delivery pace (target wpm per level / speed per voice)")
    print(pace_report())

    log_header("Checking Kokoro TTS")
    if not check_health(args.voice):
        print(f"\n  ERROR: Cannot connect to Kokoro TTS at {KOKORO_URL}")
        print("  Make sure Kokoro is running, e.g.:")
        print("    cd /opt/kokoro-tts && docker compose up -d")
        print("  Or set KOKORO_URL to point at the right host.\n")
        sys.exit(1)
    log("Kokoro TTS is responsive")

    log_header("Loading Manifest")
    if not AUDIO_MANIFEST_PATH.exists():
        print(f"\n  ERROR: {AUDIO_MANIFEST_PATH} not found. Run generate.py first.\n")
        sys.exit(1)
    with open(AUDIO_MANIFEST_PATH, encoding="utf-8") as f:
        needed = json.load(f)
    log(f"Found {len(needed)} clips needed")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    log_header("Generating Audio")
    out_manifest = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "voice": args.voice,
        "model": "kokoro-82m",
        "format": RESPONSE_FORMAT,
        "kokoro_url": KOKORO_URL,
        "total_clips": len(needed),
        "files": {},
    }

    generated = 0
    skipped = 0
    failed = 0

    for clip_id, meta in needed.items():
        out_path = OUTPUT_DIR / f"{clip_id}.mp3"

        if not args.regenerate and out_path.exists():
            size = out_path.stat().st_size
            log(f"SKIP  {clip_id}.mp3 (exists, {size} bytes)")
            out_manifest["files"][clip_id] = {**meta, "file_size_bytes": size, "generated_at": "previously generated"}
            skipped += 1
            continue

        text = meta.get("text", "")
        if not text.strip():
            log(f"SKIP  {clip_id} (no text)")
            continue

        # PER-CLIP VOICE (Phase 11D). --voice remains the default for every clip
        # that does not name one, so all 630 shadowing clips are unaffected. But
        # an extended-listening script is a list of speaker turns, and a
        # two-person scene rendered in one voice is one person talking to
        # themselves -- which cannot teach "the majority of films in standard
        # dialect". A manifest entry may therefore pin its own voice, and
        # `--voice` must not override it.
        voice = meta.get("voice") or args.voice
        if voice not in VOICE_IDS:
            print(f"  WARNING: {clip_id} names unknown voice {voice!r}; "
                  f"falling back to {args.voice}")
            voice = args.voice

        # Pace off the RESOLVED voice, not meta's: if the manifest named an
        # unknown voice we fell back above, and pacing against the name we
        # rejected would reintroduce the very mismatch this corrects.
        speed = speed_for({**meta, "voice": voice})
        log(f"GEN   {clip_id} [{voice} @{speed}] -- "
            f"\"{text[:55]}{'...' if len(text) > 55 else ''}\"")
        try:
            audio_bytes = call_kokoro(text, voice, speed)
            out_path.write_bytes(audio_bytes)
            out_manifest["files"][clip_id] = {
                **meta,
                "voice": voice,
                "speed": speed,
                "file_size_bytes": len(audio_bytes),
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            log(f"  Saved: {clip_id}.mp3 ({len(audio_bytes) / 1024:.1f} KB)")
            generated += 1
            time.sleep(1)  # brief pause to avoid overloading CPU-only inference
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            print(f"  FAILED: {clip_id} -- {e}")
            failed += 1

    manifest_path = OUTPUT_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(out_manifest, f, ensure_ascii=False, indent=2)

    log_header("Complete")
    log(f"Generated: {generated}")
    log(f"Skipped:   {skipped}")
    log(f"Failed:    {failed}")
    log(f"Manifest:  {manifest_path}")

    # CONSISTENCY CHECK. Previously this script exited 0 even when clips had
    # failed, so a timed-out synthesis was invisible: the MP3 was simply absent,
    # the page fell back to the browser's robot voice, and nothing anywhere
    # said so. For a minute of listening comprehension that is not a graceful
    # degradation, it is a silent quality collapse -- so missing and empty
    # clips are now reported by id and the exit code is non-zero.
    missing, empty = [], []
    for clip_id, meta in needed.items():
        if not (meta.get("text") or "").strip():
            continue
        path = OUTPUT_DIR / f"{clip_id}.mp3"
        if not path.exists():
            missing.append(clip_id)
        elif path.stat().st_size == 0:
            empty.append(clip_id)

    if missing or empty:
        log_header("INCOMPLETE")
        if missing:
            print(f"  {len(missing)} clip(s) have NO mp3 on disk:")
            for clip_id in missing[:20]:
                print(f"    - {clip_id}")
            if len(missing) > 20:
                print(f"    ... and {len(missing) - 20} more")
        if empty:
            print(f"  {len(empty)} clip(s) are zero bytes: {', '.join(empty[:20])}")
        print("\n  Pages for these clips will fall back to the browser voice.")
        print("  Re-run this script to fill the gaps.\n")
        print("===========================================================\n")
        sys.exit(1)

    log("Every clip in the manifest has a non-empty mp3 on disk")
    print("\n===========================================================\n")


if __name__ == "__main__":
    main()
