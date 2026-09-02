#!/usr/bin/env python3
"""Post-process Kokoro's raw ONNX output so it matches what students should hear.

WHY THIS EXISTS
---------------
Kokoro's website and the kokoro-fastapi server sound noticeably better than the
clips this project shipped, on the SAME model and text. The gap was never the
voice — it is that production renders the RAW float samples straight from
`kokoro_onnx` and writes them to MP3, while kokoro-fastapi post-processes every
chunk before encoding (see api/src/services/audio.py in remsky/Kokoro-FastAPI).

Two problems this caused, both measured on real clips:

1. INCONSISTENT LOUDNESS. The raw model output peaks wherever it happens to
   land — af_heart saying "pound" peaks at 0.378 (~ -8.5 dBFS) while am_adam
   saying "pound" peaks at 0.979 (almost full scale). Same programme, one clip
   thin and one nearly clipping. Students raise the volume for the quiet ones
   and then the loud ones are harsh, and the quiet ones surface the model's
   noise floor — which is exactly the "reads bad on my page" report.

2. RAGGED SILENCE. The model leaves 150-250 ms of dead air at each end. On a
   single-word vocabulary drill (86.8% of the listening surface is one word)
   that lag is audible and makes the clip feel slow and disconnected from the
   tap that triggered it.

WHAT IT DOES (in order)
-----------------------
1. Peak-normalise to TARGET_PEAK. This is the fix that equalises loudness across
   voices and clips. It scales, it does not compress, so dynamics within a clip
   are untouched — only the clip-to-clip level is made consistent.
2. Trim leading/trailing silence below SILENCE_DB, keeping a small PAD_MS so the
   word never starts abruptly. Mirrors kokoro-fastapi's find_first_last_non_silent.
3. Hard-clip to [-1, 1] as a safety net so no rounding can overflow when
   libsndfile converts to int16 — the overflow that speaches issue #599
   documents as audible distortion on loud phonemes.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
- It does NOT change speed. Slowing Kokoro corrupts phonemes (render_speech.py's
  docstring documents a student catching exactly that); pace is a playback-time
  concern via audio.playbackRate, not a synthesis-time one.
- It does NOT touch pitch or apply EQ/compression. The goal is to deliver the
  model's own voice at a consistent, full level — not to re-voice it.

The processing is deterministic: identical input samples give identical output,
so a re-render is reproducible and the clip id (sha256 of voice|text) still means
one thing. Because the AUDIO changes for an unchanged text, any caller that
caches by clip id MUST bump its cache-busting prefix when it adopts this — see
R2_PREFIX in render_speech.py.
"""
import numpy as np

SAMPLE_RATE = 24000        # Kokoro-82M native rate; asserted by callers
TARGET_PEAK = 0.95         # -0.45 dBFS: full and consistent, with headroom
SILENCE_DB = -45.0         # below this, relative to the normalised peak, is silence
PAD_MS = 50                # keep this much silence at each end after trimming


def postprocess(samples, sample_rate=SAMPLE_RATE, target_peak=TARGET_PEAK,
                silence_db=SILENCE_DB, pad_ms=PAD_MS):
    """Peak-normalise, trim silence with a small pad, and safety-clip.

    Args:
        samples: 1-D float array from kokoro_onnx (values roughly in [-1, 1]).
        sample_rate: samples per second, for converting PAD_MS to samples.
    Returns:
        A float32 array, same sample rate, ready for sf.write(..., format="MP3").
        Returns the input unchanged (as float32) if it is empty or pure silence,
        so a bad clip is never turned into a zero-length file.
    """
    x = np.asarray(samples, dtype=np.float32).flatten()
    if x.size == 0:
        return x

    # 1) Peak-normalise. Equalises loudness across clips and voices.
    peak = float(np.max(np.abs(x)))
    if peak > 1e-6:
        x = x * (target_peak / peak)
    else:
        return x                      # pure silence: nothing to normalise or trim

    # 2) Trim silence, keeping PAD_MS at each end. Threshold is relative to the
    #    peak we just normalised to, so it behaves the same for every clip.
    threshold = target_peak * (10.0 ** (silence_db / 20.0))
    non_silent = np.where(np.abs(x) > threshold)[0]
    if non_silent.size:
        pad = int(pad_ms * sample_rate / 1000)
        start = max(int(non_silent[0]) - pad, 0)
        end = min(int(non_silent[-1]) + pad, len(x))
        x = x[start:end]

    # 3) Safety clip so int16 conversion in libsndfile cannot overflow.
    return np.clip(x, -1.0, 1.0).astype(np.float32)
