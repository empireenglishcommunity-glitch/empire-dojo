#!/usr/bin/env python3
"""Generate all practice platform HTML pages from curriculum data.

Covers all 4 levels (L0-L3, 38 weeks total), reading curriculum content
directly from the EEC-REPO discord-learning-bot's data/ and content/
directories, and writes output into THIS repo (empire-practice), not a
sibling repo.

Path resolution (no more hardcoded /projects/sandbox/... paths):
  - EEC_REPO_DIR env var, if set, points at the EEC-REPO checkout.
  - Otherwise defaults to a sibling directory: ../EEC-REPO relative to
    this script's own location (matches the common local dev layout of
    cloning all org repos into one parent folder).
  - Output is always written into this repo's own root (sibling of this
    script), e.g. <repo>/l1/week3/day2/accent.html.

Usage:
    python3 generate.py                # generate all 4 levels
    python3 generate.py --level l1     # generate a single level
    EEC_REPO_DIR=/path/to/EEC-REPO python3 generate.py
"""
import argparse
import json
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

import os

EEC_REPO_DIR = Path(os.environ.get("EEC_REPO_DIR", SCRIPT_DIR.parent / "EEC-REPO"))
BOT_DIR = EEC_REPO_DIR / "bots" / "discord-learning-bot"
DATA_DIR = BOT_DIR / "data"
CONTENT_DIR = BOT_DIR / "content"
OUTPUT_DIR = SCRIPT_DIR  # this repo's own root

# Single source of truth for how many curriculum weeks each level has —
# must match bots/discord-learning-bot/src/curriculum.py's LEVEL_WEEK_COUNTS.
LEVEL_WEEK_COUNTS = {"l0": 8, "l1": 10, "l2": 12, "l3": 8}

AUDIO_MANIFEST_PATH = OUTPUT_DIR / "audio-manifest.json"


def esc(s):
    """Escape a string for safe inclusion inside a single-quoted JS string literal."""
    if s is None:
        s = ""
    return str(s).replace("\\", "\\\\").replace("'", "\\'").replace('"', "&quot;").replace("\n", " ")


def audio_id(level, week, day, kind):
    """Stable filename-safe id for a pre-generated Kokoro audio clip."""
    return f"{level}-w{week}-d{day}-{kind}"


# ============================================================
#  ACCENT DRILL NORMALIZATION
#
# content/{level}/accent/week{N}_*.json day drills come in three shapes:
#   - normal (days 1-5 typically): isolation, minimal_pairs, word_practice,
#     sentence_practice, record_this
#   - review (usually day 6): mixed_pairs, challenge_sentences, record_this
#   - assessment (usually day 7): test_yourself.passage, scoring_guide
# normalize_drill() maps all three into one consistent shape so the page
# generators don't need to special-case each drill's "type".
# ============================================================

def _flatten_word_practice(wp):
    """word_practice is sometimes a flat list, sometimes a dict of named
    sublists (e.g. {"long_ee": [...], "short_i": [...]})."""
    if isinstance(wp, list):
        return wp
    if isinstance(wp, dict):
        out = []
        for v in wp.values():
            if isinstance(v, list):
                out.extend(v)
        return out
    return []


def normalize_drill(drill):
    """Return a normalized dict: sounds(str), pairs(list of (a,b)),
    words(list), sentences(list of str), primary_text(str), instr_ar(str)."""
    if not isinstance(drill, dict):
        return {"sounds": "Review", "pairs": [], "words": [], "sentences": [],
                "primary_text": "I am practicing English.", "instr_ar": "تمرّن على النطق"}

    drill_type = drill.get("type")
    raw_sounds = drill.get("target_sounds", "Review")
    sounds = ", ".join(raw_sounds) if isinstance(raw_sounds, list) else str(raw_sounds)

    if drill_type == "review":
        pairs = [tuple(p) for p in drill.get("mixed_pairs", []) if isinstance(p, list) and len(p) == 2]
        words = [w for pair in pairs for w in pair]
        sentences = drill.get("challenge_sentences", []) or []
        primary_text = sentences[0] if sentences else drill.get("record_this", "Let's review this week's sounds.")
        instr_ar = "راجع الأصوات دي وكرر الجمل"
        return {"sounds": sounds, "pairs": pairs, "words": words, "sentences": sentences,
                "primary_text": drill.get("record_this", primary_text), "instr_ar": instr_ar}

    if drill_type == "assessment":
        ty = drill.get("test_yourself", {}) if isinstance(drill.get("test_yourself"), dict) else {}
        passage = ty.get("passage", "Please read this passage aloud and record yourself.")
        instr_ar = ty.get("instructions_ar") or "سجّل نفسك وانت تقرأ المقطع ده"
        return {"sounds": sounds, "pairs": [], "words": [], "sentences": [passage],
                "primary_text": passage, "instr_ar": instr_ar}

    # normal drill
    pairs_raw = drill.get("minimal_pairs", []) or []
    pairs = []
    for p in pairs_raw:
        if isinstance(p, dict) and isinstance(p.get("pair"), list) and len(p["pair"]) == 2:
            pairs.append(tuple(p["pair"]))
    words = _flatten_word_practice(drill.get("word_practice"))
    sentences = drill.get("sentence_practice", []) or []
    primary_text = drill.get("record_this") or (sentences[0] if sentences else "I am practicing English.")
    iso = drill.get("isolation", {}) if isinstance(drill.get("isolation"), dict) else {}
    instr_ar = iso.get("instructions_ar") or "اسمع وكرر"
    return {"sounds": sounds, "pairs": pairs, "words": words, "sentences": sentences,
            "primary_text": primary_text, "instr_ar": instr_ar}


# ============================================================
#  PAGE GENERATORS
# ============================================================

def gen_accent(level, week, day, focus, norm):
    sounds = norm["sounds"] or "Review"
    primary = norm["primary_text"]

    pairs_card = ""
    if norm["pairs"]:
        pairs_html = "<br>".join(f"<b>{a}</b> / <b>{b}</b>" for a, b in norm["pairs"][:5])
        pairs_card = f'<div class="card"><h2>📝 Minimal Pairs</h2><div class="transcript">{pairs_html}</div></div>'

    words_card = ""
    if norm["words"]:
        words = norm["words"][:8]
        words_html = " &bull; ".join(f"<b>{w}</b>" for w in words)
        words_card = (f'<div class="card"><h2>🎯 Practice Words</h2><div class="transcript">{words_html}</div>'
                      f'<button class="btn btn-outline btn-sm" onclick="TTS.speak(\'{esc(", ".join(words))}\', 0.6)">🔊 Hear Words</button></div>')

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Accent Week {week} Day {day} | Empire English</title><link rel="stylesheet" href="/css/empire.css"></head><body>
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>🎯 Accent Drill</h1><p class="subtitle">Week {week} • Day {day} • {focus}</p></div>
<div class="arabic-text">{norm["instr_ar"]}</div>
<div class="card"><h2>🔊 Target Sounds: {sounds}</h2>
<button class="btn" onclick="TTS.speak('{esc(primary)}')">▶️ Listen to Model</button>
<div class="speed-control"><label>Speed:</label><select id="speed-select" onchange="TTS.setRate(this.value)"><option value="0.6">Slow</option><option value="0.8" selected>Normal</option><option value="1.0">Fast</option></select></div></div>
{pairs_card}
{words_card}
<div class="card"><h2>🎙️ Say This</h2><div class="transcript"><b>"{primary}"</b></div>
<button class="btn btn-outline" onclick="TTS.speak('{esc(primary)}', 0.7)">🔊 Model</button></div>
<div class="done-section"><label><input type="checkbox" class="checkbox" onchange="if(this.checked)Progress.markDone('{level}',{week},{day},'accent')"> Done ✅</label></div>
<div class="nav" style="margin-top:20px"><a href="index.html">← Today</a><a href="shadowing.html">Shadowing →</a></div></div>
<script src="/js/app.js"></script></body></html>'''


def gen_shadowing(level, week, day, theme, norm, aid):
    passage = norm["primary_text"]
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Shadowing Week {week} Day {day} | Empire English</title><link rel="stylesheet" href="/css/empire.css"></head><body>
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>🎧 Shadowing</h1><p class="subtitle">Week {week} • Day {day} • {theme}</p></div>
<div class="arabic-text">اسمع → كرر 3 مرات → سجل المحاولة الثالثة</div>
<div class="card"><h2>📝 Passage</h2><div class="transcript">{passage}</div>
<button class="btn" onclick="KokoroAudio.play('{aid}','{esc(passage)}')">▶️ Play</button>
<button class="btn btn-outline" onclick="TTS.stop()">⏹️ Stop</button>
<div class="speed-control"><label>Speed:</label><select id="speed-select" onchange="TTS.setRate(this.value)"><option value="0.6">Slow</option><option value="0.75" selected>Normal</option><option value="1.0">Fast</option></select></div>
<p style="color:var(--text-muted);font-size:0.75rem;margin-top:10px">🎙️ Studio-quality audio when available, otherwise your browser's voice.</p></div>
<div class="done-section"><label><input type="checkbox" class="checkbox" onchange="if(this.checked)Progress.markDone('{level}',{week},{day},'shadowing')"> Done ✅</label></div>
<div class="nav" style="margin-top:20px"><a href="accent.html">← Accent</a><a href="listening.html">Listening →</a></div></div>
<script src="/js/app.js"></script></body></html>'''


def gen_listening(level, week, day, theme, day_vocab, all_week_vocab):
    """Grounded listening comprehension: hear a vocabulary word, choose its
    correct Arabic meaning. Distractors are drawn from other words in the
    same week so this scales to every week with zero invented dialogue."""
    import random
    rng = random.Random(f"{level}-{week}-{day}")  # deterministic per page
    pool = [w for w in all_week_vocab if w not in day_vocab] or day_vocab
    questions = []
    targets = day_vocab[:3] if len(day_vocab) >= 3 else day_vocab
    for w in targets:
        distractors = rng.sample(pool, k=min(2, len(pool))) if pool else []
        options = [w] + [d for d in distractors if d.get("word") != w.get("word")]
        rng.shuffle(options)
        correct_idx = options.index(w)
        questions.append((w, options, correct_idx))

    q_html = ""
    for qi, (word, options, correct_idx) in enumerate(questions):
        opts_html = ""
        for i, o in enumerate(options):
            is_correct = "true" if i == correct_idx else "false"
            data_c = " data-correct" if i == correct_idx else ""
            opts_html += f'<div class="option"{data_c} onclick="checkAnswer(this,{is_correct})">{o["arabic"]}</div>'
        q_html += (f'<div class="card"><h2>🔊 Word {qi+1}</h2>'
                   f'<button class="btn btn-sm" onclick="TTS.speak(\'{esc(word["word"])}\', 0.7)">▶️ Play Word</button>'
                   f'<div class="question" style="margin-top:14px"><p>❓ What does this word mean?</p>'
                   f'<div class="options">{opts_html}</div></div></div>')

    if not q_html:
        q_html = '<div class="card"><p>No vocabulary available for this day yet.</p></div>'

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Listening Week {week} Day {day} | Empire English</title><link rel="stylesheet" href="/css/empire.css"></head><body>
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>👂 Listening</h1><p class="subtitle">Week {week} • Day {day} • {theme}</p></div>
<div class="arabic-text">اسمع الكلمة واختار المعنى الصحيح. ممكن تسمع أكتر من مرة.</div>
{q_html}
<div class="done-section"><label><input type="checkbox" class="checkbox" onchange="if(this.checked)Progress.markDone('{level}',{week},{day},'listening')"> Done ✅</label></div>
<div class="nav" style="margin-top:20px"><a href="shadowing.html">← Shadowing</a><a href="vocab.html">Vocab →</a></div></div>
<script src="/js/app.js"></script>
<script>function checkAnswer(el,c){{el.closest('.options').querySelectorAll('.option').forEach(o=>o.style.pointerEvents='none');if(c)el.classList.add('correct');else{{el.classList.add('wrong');el.closest('.options').querySelector('[data-correct]').classList.add('correct')}}}}</script></body></html>'''


def gen_vocab(level, week, day, theme, words):
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Vocabulary Week {week} Day {day} | Empire English</title><link rel="stylesheet" href="/css/empire.css"></head><body>
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>📖 Vocabulary</h1><p class="subtitle">Week {week} • Day {day} • {theme}</p></div>
<div class="arabic-text">اضغط البطاقة لرؤية المعنى. اضغط 🔊 لسماع الكلمة.</div>
<div class="card"><p id="card-counter" style="text-align:center;color:var(--text-muted)">1/{max(len(words),1)}</p>
<div class="flashcard" id="flashcard" onclick="Flashcard.flip()"></div>
<div class="audio-controls" style="justify-content:center">
<button class="btn btn-sm btn-outline" onclick="Flashcard.prev()">←</button>
<button class="btn btn-sm" onclick="Flashcard.hearWord()">🔊</button>
<button class="btn btn-sm btn-outline" onclick="Flashcard.next()">→</button></div></div>
<div class="done-section"><label><input type="checkbox" class="checkbox" onchange="if(this.checked)Progress.markDone('{level}',{week},{day},'vocab')"> Done ✅</label></div>
<div class="nav" style="margin-top:20px"><a href="listening.html">← Listening</a><a href="index.html">Today</a></div></div>
<script src="/js/app.js"></script>
<script>const words={json.dumps(words, ensure_ascii=False)};document.addEventListener('DOMContentLoaded',()=>Flashcard.init(words));</script></body></html>'''


def gen_day_index(level, week, day):
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Week {week} Day {day} | Empire English</title>
<link rel="stylesheet" href="/css/empire.css"></head><body>
<div class="container"><div class="header">
<img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px">
<h1>Week {week} — Day {day}</h1><p class="subtitle">Choose your exercise</p></div>
<div class="arabic-text">اختار التمرين اللي عايز تعمله</div>
<div class="card"><h2>📋 Today's Exercises</h2>
<div class="nav" style="flex-direction:column;align-items:stretch">
<a href="accent.html">🎯 Accent Drill — تدريب النطق</a>
<a href="shadowing.html">🎧 Shadowing — المحاكاة</a>
<a href="listening.html">👂 Listening — الاستماع</a>
<a href="vocab.html">📖 Vocabulary — المفردات</a>
</div></div>
<div class="nav" style="margin-top:20px"><a href="/index.html">← Home</a></div>
<div class="footer">Empire English Community — Common Sense First 🏛️</div>
</div></body></html>'''


# ============================================================
#  GENERATE
# ============================================================

def load_week_accent_data(level, week):
    accent_dir = CONTENT_DIR / level / "accent"
    matches = sorted(accent_dir.glob(f"week{week}_*.json")) + sorted(accent_dir.glob(f"week{week}.json"))
    if not matches:
        return None
    with open(matches[0], encoding="utf-8") as f:
        return json.load(f)


def generate_level(level, audio_manifest):
    max_week = LEVEL_WEEK_COUNTS[level]
    total = 0

    for week in range(1, max_week + 1):
        week_file = DATA_DIR / f"{level}_week{week}.json"
        if not week_file.exists():
            print(f"  [{level}] Skip week {week} (no data)")
            continue
        with open(week_file, encoding="utf-8") as f:
            week_data = json.load(f)

        accent_data = load_week_accent_data(level, week)
        focus = accent_data.get("focus", "Review") if accent_data else "Review"
        theme = week_data.get("theme", "General")
        vocab = week_data.get("vocabulary", [])

        drills_by_day = {}
        if accent_data:
            for d in accent_data.get("daily_drills", []):
                if isinstance(d, dict) and "day" in d:
                    drills_by_day[d["day"]] = d

        for day in range(1, 8):
            day_dir = OUTPUT_DIR / level / f"week{week}" / f"day{day}"
            day_dir.mkdir(parents=True, exist_ok=True)

            day_vocab = vocab[(day - 1) * 8: day * 8] if len(vocab) >= day * 8 else vocab[:8]
            norm = normalize_drill(drills_by_day.get(day))
            shadow_aid = audio_id(level, week, day, "shadow")

            with open(day_dir / "index.html", "w", encoding="utf-8") as f:
                f.write(gen_day_index(level, week, day))
            with open(day_dir / "accent.html", "w", encoding="utf-8") as f:
                f.write(gen_accent(level, week, day, focus, norm))
            with open(day_dir / "shadowing.html", "w", encoding="utf-8") as f:
                f.write(gen_shadowing(level, week, day, theme, norm, shadow_aid))
            with open(day_dir / "listening.html", "w", encoding="utf-8") as f:
                f.write(gen_listening(level, week, day, theme, day_vocab, vocab))
            with open(day_dir / "vocab.html", "w", encoding="utf-8") as f:
                f.write(gen_vocab(level, week, day, theme, day_vocab))

            audio_manifest[shadow_aid] = {
                "level": level, "week": week, "day": day,
                "text": norm["primary_text"],
            }
            total += 5  # index + 4 exercise pages

        print(f"  [{level}] Week {week}: 35 pages ✅")

    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level", choices=["l0", "l1", "l2", "l3"], default=None,
                         help="Generate only this level (default: all 4 levels)")
    args = parser.parse_args()

    if not DATA_DIR.exists():
        raise SystemExit(
            f"ERROR: EEC-REPO data directory not found: {DATA_DIR}\n"
            f"Set EEC_REPO_DIR to the correct path, e.g.:\n"
            f"  EEC_REPO_DIR=/path/to/EEC-REPO python3 generate.py"
        )

    print("Generating Empire English Practice Platform...")
    print(f"  Reading curriculum from: {BOT_DIR}")
    print(f"  Writing pages to:        {OUTPUT_DIR}")

    levels = [args.level] if args.level else ["l0", "l1", "l2", "l3"]
    audio_manifest = {}
    if AUDIO_MANIFEST_PATH.exists():
        try:
            with open(AUDIO_MANIFEST_PATH, encoding="utf-8") as f:
                audio_manifest = json.load(f)
        except (json.JSONDecodeError, OSError):
            audio_manifest = {}

    total = 0
    for level in levels:
        total += generate_level(level, audio_manifest)

    with open(AUDIO_MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(audio_manifest, f, ensure_ascii=False, indent=2)

    print(f"\n  TOTAL: {total} HTML pages generated")
    print(f"  Audio manifest: {AUDIO_MANIFEST_PATH} ({len(audio_manifest)} clips needed)")
    print(f"  Run generate_audio.py against this manifest to produce Kokoro MP3s.")
    print(f"  Platform ready at: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
