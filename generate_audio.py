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
KOKORO_URL = os.environ.get("KOKORO_URL", "http://localhost:8880")
AUDIO_MANIFEST_PATH = SCRIPT_DIR / "audio-manifest.json"
OUTPUT_DIR = SCRIPT_DIR / "audio"
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


def call_kokoro(text, voice):
    payload = json.dumps({
        "model": "kokoro",
        "input": text,
        "voice": voice,
        "response_format": RESPONSE_FORMAT,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{KOKORO_URL}/v1/audio/speech",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
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

        log(f"GEN   {clip_id} -- \"{text[:60]}{'...' if len(text) > 60 else ''}\"")
        try:
            audio_bytes = call_kokoro(text, args.voice)
            out_path.write_bytes(audio_bytes)
            out_manifest["files"][clip_id] = {
                **meta,
                "voice": args.voice,
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
    print("\n===========================================================\n")


if __name__ == "__main__":
    main()
