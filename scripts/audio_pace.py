"""Delivery pace for extended-listening clips, normalised per voice.

WHY THIS MODULE EXISTS
======================
Several CEFR reception descriptors are *about delivery speed*, not just about
comprehension:

    A1.R.1  ... when people SPEAK SLOWLY AND CLEARLY
    B1.R.2  ... when delivered RELATIVELY SLOWLY AND CLEARLY
    C1.R.1  understand extended speech ... (native delivery)
    C2.R.1  ... delivered at FAST NATIVE SPEED

So the rendered pace is not a cosmetic choice. If an A1 clip is delivered at
200 wpm the student fails on delivery speed alone whatever their comprehension,
and if a C2 clip is delivered at 120 wpm the programme is claiming "fast native
speed" over audio that is slower than its own beginner target.

The first attempt at this set one `speed` value per level. That was wrong,
because it assumed every voice speaks at the same rate at speed=1.0. They do
not. Measured on a fixed 53-word reference paragraph:

    af_nicole    130 wpm      am_adam      228 wpm
    am_michael   193 wpm      af_sky       230 wpm
    bm_george    198 wpm      bf_isabella  236 wpm
    bm_lewis     204 wpm      bf_emma      238 wpm
    af_bella     209 wpm
    af_heart     212 wpm
    af_sarah     222 wpm

That is a **1.84x spread**, and af_nicole is a severe outlier. The consequences
were real and visible in the shipped audio:

  * pace was decided by whichever voice a script happened to name;
  * inside a single multi-voice scene one speaker ran at 120 wpm and another at
    210 wpm, which no real panel or argument sounds like;
  * six C1/C2 clips landed at 120-142 wpm -- at or below the A1 target -- on the
    two descriptors whose entire content is delivery speed.

Two hypotheses were tested and rejected before landing on the voice:
  * inter-sentence pause length -- raising speed and cutting the pause moved the
    worst clip only 120 -> 141 wpm while another clip sat at 209 unchanged;
  * punctuation (em-dashes, ellipses) -- normalising it changed 122 -> 120 wpm.

HOW IT WORKS
============
Pace is expressed as a TARGET WPM per level, which is the thing the descriptors
actually talk about, and the per-clip `speed` is derived:

    speed = target_wpm[level] / VOICE_WPM[voice]

Kokoro's `speed` parameter was verified linear over 0.55-1.60 (measured ratio
0.97-1.09, no clipping at any value), so the correction is valid. The largest
correction any voice needs is af_nicole at C2: 205/130 = 1.58.

Reference points for the targets: careful/slow speech 120-130 wpm, normal
conversation 150-160, fast native 200+.

Only `broadcast` (extended listening) clips are paced. Shadowing clips carry no
level-scoped delivery requirement and keep speed 1.0.
"""

# Measured with scripts/measure_voice_rates.py against the reference paragraph
# in that file. Re-run it if the Kokoro model version changes -- these numbers
# are properties of the model, not of the content.
VOICE_WPM = {
    "af_bella": 209.0,
    "af_heart": 212.0,
    "af_nicole": 130.0,
    "af_sarah": 222.0,
    "af_sky": 230.0,
    "am_adam": 228.0,
    "am_michael": 193.0,
    "bf_emma": 238.0,
    "bf_isabella": 236.0,
    "bm_george": 198.0,
    "bm_lewis": 204.0,
}

# What each level's descriptors actually promise.
TARGET_WPM_BY_LEVEL = {
    "a1": 125,   # "slowly and clearly" — careful speech
    "a2": 135,
    "b1": 155,   # "relatively slowly and clearly"
    "b2": 175,   # standard broadcast pace
    "c1": 195,   # native
    "c2": 205,   # "fast native speed"
}

DEFAULT_TARGET_WPM = 175
FALLBACK_VOICE_WPM = 210.0

# Below this many words, words-per-minute is not a meaningful measurement and
# must not be calibrated against. A one-word turn ("And?", "Baba—") is mostly
# onset and decay, so its apparent rate is ~100 wpm however fast it is spoken.
# Closing the loop on those numbers drove such clips to maximum speed and made
# short emotional lines sound rushed -- the opposite of the intended fix. Short
# turns are rendered open-loop at the per-voice speed instead, and excluded from
# the pace report.
MIN_WORDS_FOR_PACE = 25

# Kokoro degrades outside roughly this band; every (level, voice) pair in the
# current content falls inside it, so the clamp is a guard and not a silent
# correction. If it ever binds, pace_report() will say so.
SPEED_MIN = 0.50
SPEED_MAX = 1.60

# PHONEME-SAFE RENDER FLOOR (added 2026-09-02 with the single-brand-voice change).
# Synthesising below this `speed` corrupts Kokoro's phonemes — af_heart at 0.85
# and below inserts a spurious leading syllable ("She is a student." -> "as she
# is a student."), ASR-confirmed across a speed sweep; she is clean at >=0.90.
# So we NEVER synthesise slower than this. When a level's target needs more
# slowing than the floor permits, the remainder is applied at PLAYBACK time via
# audio.playbackRate, which the browser pitch-corrects and which does not touch
# phonemes (the same lever vocab/dictation already use). See split_pace().
RENDER_SPEED_FLOOR = 0.90


def target_wpm_for(level):
    return TARGET_WPM_BY_LEVEL.get((level or "").lower(), DEFAULT_TARGET_WPM)


def speed_for_voice(level, voice):
    """The `speed` value that makes `voice` deliver `level` at its target wpm.

    This is the IDEAL synthesis speed ignoring the phoneme-safety floor; it is
    kept for the pace math and the report. Renderers must use split_pace(),
    which never synthesises below RENDER_SPEED_FLOOR.
    """
    base = VOICE_WPM.get(voice, FALLBACK_VOICE_WPM)
    raw = target_wpm_for(level) / base
    return max(SPEED_MIN, min(SPEED_MAX, raw)), raw


def split_pace(level, voice):
    """Split a level's target pace into a phoneme-safe render speed and a
    playback rate, so voice x level always hits the target WITHOUT corruption.

    total_ratio = target_wpm / voice_wpm  is the overall slowdown wanted.
      * If total_ratio >= RENDER_SPEED_FLOOR (light slowing or speed-up), do it
        all at synthesis: render_speed = clamp(total_ratio), playback = 1.0.
      * If total_ratio <  RENDER_SPEED_FLOOR (heavy slowing, e.g. af_heart at
        A1/A2/B1), synthesise at the floor and put the rest on playback:
            render_speed = RENDER_SPEED_FLOOR
            playback     = total_ratio / RENDER_SPEED_FLOOR   (< 1.0, slower)
    Returns (render_speed, playback_rate). Their product equals the clamped
    total_ratio, i.e. effective wpm == target wpm.
    """
    base = VOICE_WPM.get(voice, FALLBACK_VOICE_WPM)
    total = target_wpm_for(level) / base
    total = max(SPEED_MIN, min(SPEED_MAX, total))
    if total >= RENDER_SPEED_FLOOR:
        return round(total, 4), 1.0
    render_speed = RENDER_SPEED_FLOOR
    playback = total / RENDER_SPEED_FLOOR
    return round(render_speed, 4), round(playback, 4)


def speed_for(meta, default_voice=None):
    """Delivery speed for one manifest entry.

    Only extended-listening clips are paced by level; everything else keeps the
    default, as before.
    """
    if (meta or {}).get("kind") != "broadcast":
        return 1.0
    voice = meta.get("voice") or default_voice
    speed, _ = speed_for_voice(meta.get("level"), voice)
    return round(speed, 4)


def pace_report():
    """Every (level, voice) combination and the speed it will be rendered at.

    Printed by the renderers so the pace decision is visible in the build log
    rather than buried in a constant.
    """
    lines = [f"  {'level':<6}{'target':>7}  " +
             "  ".join(f"{v.split('_')[1][:7]:>7}" for v in sorted(VOICE_WPM))]
    clamped = []
    for level in ("a1", "a2", "b1", "b2", "c1", "c2"):
        cells = []
        for voice in sorted(VOICE_WPM):
            speed, raw = speed_for_voice(level, voice)
            cells.append(f"{speed:>7.2f}")
            if abs(speed - raw) > 1e-6:
                clamped.append((level, voice, raw))
        lines.append(f"  {level:<6}{target_wpm_for(level):>7}  " + "  ".join(cells))
    if clamped:
        lines.append("  CLAMPED (target not reachable for these):")
        for level, voice, raw in clamped:
            lines.append(f"    {level} {voice}: wanted speed {raw:.2f}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(__doc__.strip().split("\n\n")[0])
    print()
    print(pace_report())
