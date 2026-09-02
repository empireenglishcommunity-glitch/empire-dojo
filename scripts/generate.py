#!/usr/bin/env python3
"""Generate all practice platform HTML pages from curriculum data.

Covers all 4 levels (L0-L3, 38 weeks total), reading curriculum content
directly from the empire-nexus discord-learning-bot's data/ and content/
directories, and writes output into THIS repo (empire-dojo), not a
sibling repo.

Path resolution (no more hardcoded /projects/sandbox/... paths):
  - EEC_REPO_DIR env var, if set, points at the empire-nexus checkout.
    (Env var name kept as EEC_REPO_DIR for backward compatibility with
    existing deploy scripts/CI — it points at empire-nexus, formerly
    named EEC-REPO.)
  - Otherwise defaults to a sibling directory: ../empire-nexus relative
    to this script's own location (matches the common local dev layout
    of cloning all org repos into one parent folder).
  - Output is always written into this repo's site/ directory (a sibling
    of this scripts/ directory), e.g. <repo>/site/l1/week3/day2/accent.html.
    This keeps build tooling (this script, generate_audio.py, the audio
    manifest) physically outside of whatever directory gets deployed as
    the live website, so they can never be served as public assets no
    matter how the deploy step is configured.

Usage:
    python3 generate.py                # generate all 4 levels
    python3 generate.py --level l1     # generate a single level
    EEC_REPO_DIR=/path/to/empire-nexus python3 generate.py
"""
import argparse
import json
import random
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent  # empire-dojo/ (parent of scripts/)

import os
import sys

sys.path.insert(0, str(SCRIPT_DIR))
from audio_pace import split_pace  # noqa: E402  (per-level broadcast pace)

# empire-nexus (formerly EEC-REPO) is a sibling of THIS repo (empire-dojo/),
# i.e. REPO_ROOT.parent / "empire-nexus" -- not SCRIPT_DIR.parent, since
# SCRIPT_DIR is empire-dojo/scripts/, one level deeper than the repo root.
EEC_REPO_DIR = Path(os.environ.get("EEC_REPO_DIR", REPO_ROOT.parent / "empire-nexus"))
BOT_DIR = EEC_REPO_DIR / "bots" / "discord-learning-bot"
DATA_DIR = BOT_DIR / "data"
CONTENT_DIR = BOT_DIR / "content"
OUTPUT_DIR = REPO_ROOT / "site"  # deployed site lives here, NOT in scripts/

# Single source of truth for how many curriculum weeks each level has —
# must match bots/discord-learning-bot/src/curriculum.py's LEVEL_WEEK_COUNTS.
LEVEL_WEEK_COUNTS = {}  # legacy L0–L3 retired; CEFR-only now

# CEFR levels (Mi'yar) — must match curriculum.py's CEFR_WEEK_COUNTS. Generated
# additively alongside the legacy levels; a CEFR level with no data files on
# disk yet (e.g. b1–c2 today) is skipped gracefully in generate_level().
CEFR_WEEK_COUNTS = {"a1": 10, "a2": 12, "b1": 14, "b2": 16, "c1": 18, "c2": 20}

# Everything the generator knows how to build. Legacy + CEFR keys coexist so
# the static site can serve both /l0/… (legacy, pre-migration) and /a1/…
# (CEFR) paths during and after the migration.
ALL_WEEK_COUNTS = {**LEVEL_WEEK_COUNTS, **CEFR_WEEK_COUNTS}

# The manifest is build metadata, not a site asset — keep it in scripts/,
# never in site/, so it's never deployed as a public file.
AUDIO_MANIFEST_PATH = SCRIPT_DIR / "audio-manifest.json"


def esc(s):
    """Escape a string for safe inclusion inside a single-quoted JS string literal
    (used for onclick="TTS.speak('...')" attributes etc.)."""
    if s is None:
        s = ""
    return str(s).replace("\\", "\\\\").replace("'", "\\'").replace('"', "&quot;").replace("\n", " ")


# ── What the ear is allowed to hear ─────────────────────────────────────────
#
# Practice-word lists deliberately mix a correct model with a WRONG form marked
# ❌, plus notation showing bad delivery. On the page that is good teaching: the
# student sees both and the ❌ says which to avoid.
#
# Spoken aloud it inverts. `❌` is U+274C, inside the emoji range render_speech's
# speakable() already strips, so the marker is removed and THE ERROR IS SPOKEN
# WITH NO CUE THAT IT IS AN ERROR — right and wrong arrive identically labelled.
# A synthesiser has no way to say "this next one is wrong."
#
# Worse, most error items encode wrong STRESS through capitalisation, which TTS
# cannot render at all. Measured with Kokoro (am_adam): `BIGG-ist` 22,316 bytes,
# `bigg-EST` 20,396, plain `biggest` 13,868 — both hyphenated forms ~50% LONGER
# than the real word, because the hyphen becomes a pause. Neither demonstrates
# stress; they just sound chopped. So the ❌ clip could not teach its own point
# even in principle.
#
# Rule: the SCREEN teaches the contrast, the EAR only ever hears correct English.
# Audited 2026-08-31 across 630 accent pages — 53 buttons, 108 items, 0 buttons
# left with nothing to say.
#
# Deliberately NOT attempted: "repairing" a ✅ stress respelling by removing its
# hyphen. `BIGG-ist` -> "biggest" happens to work, but `HOTT-ist` -> "hottist"
# is not a word and Kokoro would guess at it. Dropping errors is safe; rewriting
# correct content to sound better is a different decision and not this one.
_SPOKEN_ERROR_MARK = "\u274c"          # ❌
_SPOKEN_MIDDLE_DOT = "\u00b7"          # · — used to show separated delivery
_SPOKEN_META_LABEL = re.compile(
    r"\((?:separated|chunk|compressed|linked|blended|reduced)\)", re.I)
#
# There is deliberately NO "hyphen-split syllables" rule. The obvious one,
# `\b\w+-\w+-\w+` for `pro-vi-ded`, also matches ordinary English compounds —
# it fired on `tongue-in-cheek` and `state-of-the-art` in 31 real payloads, and
# would have silently deleted them from the audio. Checked across the whole site:
# every genuine syllable-split demo ALSO carries a `(separated)` label or a
# middle dot, so the rule was redundant as well as harmful. This is the same
# shape as the IPA character set that once included plain "e" and "a" and
# reduced "She is a student." to "is": an over-broad rule deletes real speech
# and looks like it is working.


def _not_speakable(item):
    """Why this practice item must not be spoken, or None if it is fine."""
    s = (item or "").strip()
    if _SPOKEN_ERROR_MARK in s:
        return "error form"
    if _SPOKEN_META_LABEL.search(s):
        # e.g. "/prəˈvaɪdɪd ðət/ (chunk)" — speakable() strips the IPA and leaves
        # only "(chunk)", so the student hears the label and none of the content.
        return "meta-label"
    if _SPOKEN_MIDDLE_DOT in s:
        return "separated delivery"
    return None


def spoken_words(words):
    """The subset of a practice-word list that should be SPOKEN.

    Display keeps the full list — callers must pass the unfiltered list to the
    visible markup and this result only to TTS.speak(). Returns [] if nothing
    survives, and the caller then omits the button rather than shipping one that
    speaks silence.
    """
    return [w for w in (words or []) if _not_speakable(w) is None]


def esc_html(s):
    """Escape a string for safe inclusion as HTML body/attribute text.

    Found via adversarial-input stress testing: curriculum JSON text
    (theme, accent focus, transcripts, listening-quiz answer options) was
    being interpolated directly into generated HTML with NO escaping at
    all -- only esc() existed, and that escapes for a *JS string literal*
    context (onclick="TTS.speak('...')"), not for HTML body/attribute
    context. Proven exploitable, not just theoretical: a crafted
    <img src=x onerror=...> in a vocabulary word's "arabic" field
    survived all the way into Flashcard.render()'s innerHTML call in
    app.js and would execute in a real browser; a crafted </script> in
    the same field broke out of vocab.html's <script> block early
    (browsers scan for the literal "</script" regardless of JS-string
    quoting, per the HTML spec -- json.dumps()'s escaping doesn't help
    here since it escapes for JSON syntax, not for HTML/script-tag
    context). Today's real curriculum content is hand-authored and
    committed to the repo (no bot command lets anyone submit curriculum
    text), so this isn't externally attacker-controlled right now -- but
    it's still a real defect: today's actual content already contains
    apostrophes and ampersands ("don't", "it's", "Salt & Pepper"), and
    escaping untrusted-shaped text correctly is simply correct practice
    for a static-site generator, independent of today's trust level.
    """
    if s is None:
        s = ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def safe_json_for_script_tag(data):
    """json.dumps() a value for embedding inside a <script>...</script> tag.

    Escaping "</" as "<\\/" prevents any string value containing a
    literal "</script" from prematurely closing the script block --
    standard mitigation for this well-known HTML/JS embedding issue.
    Valid JS: a string may contain an escaped forward slash, and "<\\/"
    parses identically to "</" once the JS engine reads the string, so
    this changes nothing about the resulting data structure.
    """
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def audio_id(level, week, day, kind):
    """Stable filename-safe id for a pre-generated Kokoro audio clip."""
    return f"{level}-w{week}-d{day}-{kind}"


def bl(en, ar):
    """Bilingual UI label helper. Every fixed piece of UI chrome (button
    text, nav links, section headers, instructions) is shown in English
    AND Arabic simultaneously, rather than behind a toggle -- our
    students are Arabic speakers, some still beginners, so relying on a
    click to reveal the Arabic label defeats the point. The Arabic
    portion is wrapped in a properly lang/dir-tagged span (not just a
    CSS class) so it renders correctly in Cairo/RTL and is identified
    as Arabic to screen readers and translation tools, without flipping
    the direction of the whole page (which stays LTR overall, since the
    bulk of on-page content -- the actual English target words/
    sentences students are learning -- reads left-to-right)."""
    return f'{en} <span class="ar-inline" lang="ar" dir="rtl">/ {ar}</span>'


def bl_attr(en, ar):
    """Plain-text bilingual label for HTML ATTRIBUTE contexts (placeholder,
    title, aria-label, value) where markup is invalid.

    bl() returns a <span>, which is only valid in element BODY content.
    Embedding bl() inside an attribute (e.g. placeholder="{bl(...)}")
    terminates the attribute at the span's first double-quote and leaks
    the rest of the markup into the UI as literal text -- seen live on
    2026-08-29 as `your answer <span class` and `... j/ جوابك" style=...>`
    inside the grammar and mediation input placeholders. Attributes get
    plain text only: this returns 'en / ar' escaped for safe attribute use.
    """
    return esc_html(f"{en} / {ar}")


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

def bottom_nav(active):
    """Generate the fixed bottom navigation bar for mobile (Sahel S1).
    `active` is one of: 'accent', 'shadowing', 'listening', 'vocab',
    'speaking', 'grammar'.
    First item is always Home (the personal calendar) so the student is
    one tap from home on any exercise page — no more back-back-back.

    NOTE: 'grammar' is deliberately NOT given its own item here. The bar
    already holds Home + 5 exercises; each item is min-width:60px, so a
    7th would overflow a 375px-wide phone. Grammar is reached from the
    day menu and its own page-nav instead. Passing active='grammar'
    simply highlights nothing, which is correct."""
    links = '<a href="/"><span class="nav-icon">🏠</span>Home</a>'
    items = [
        ('accent', '🎯', 'Accent'),
        ('shadowing', '🎧', 'Shadow'),
        ('listening', '👂', 'Listen'),
        ('vocab', '📖', 'Vocab'),
        ('speaking', '🎙️', 'Speak'),
    ]
    for page, icon, label in items:
        cls = ' class="active"' if page == active else ''
        links += f'<a href="{page}.html"{cls}><span class="nav-icon">{icon}</span>{label}</a>'
    return f'<nav class="bottom-nav" id="bottom-nav">{links}</nav>'


def swipe_hint():
    """Show swipe hint on mobile (hidden on desktop via CSS)."""
    return f'<div class="swipe-hint">← {bl("Swipe to navigate", "اسحب للتنقل")} →</div>'


def pwa_head():
    """PWA meta tags for generated pages (Sahel S4)."""
    return ('<link rel="manifest" href="/manifest.json">'
            '<meta name="theme-color" content="#D4AF37">'
            '<meta name="apple-mobile-web-app-capable" content="yes">'
            '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
            '<meta name="apple-mobile-web-app-title" content="Empire English">'
            '<link rel="apple-touch-icon" href="/logo.png">'
            '<meta name="robots" content="noindex, nofollow">'
            '<script src="/js/status.js"></script>')


def copyright_footer():
    """Hissar P0: copyright notice on every practice page."""
    return ('<div style="text-align:center;padding:20px 0;color:var(--text-muted);font-size:0.7rem;border-top:1px solid var(--border);margin-top:30px">'
            '© 2026 Empire English Community. All rights reserved. '
            '<span lang="ar" dir="rtl">هذا المحتوى ملكية خاصة ومحمي بحقوق الطبع والنشر.</span>'
            '</div>')


def watermark_comment():
    """Hissar P0: invisible HTML watermark for leak tracing."""
    return '<!-- Empire English Community | Proprietary Content | Unauthorized reproduction prohibited -->'


def content_gate_css():
    """Darb Phase 3: the edge middleware now handles gating — no need for
    client-side CSS/JS gate anymore. Kept as an empty function so all
    call sites in the page templates don't need changing."""
    return ''


def content_gate_overlay():
    """Darb Phase 3: edge gate replaces the client-side overlay.
    Returns empty — the middleware serves gate.html for unauthorized
    requests, so pages never even reach the browser without a session."""
    return ''


def content_gate_js():
    """Darb Phase 3: edge gate replaces the client-side JS validation.
    Returns empty — no more per-page token checking needed."""
    return ''


def gamification_bar():
    """Persistent top bar showing streak + daily progress (Sahel S5)."""
    return ('<div class="gamification-bar">'
            '<span class="streak" id="streak-display">🔥 0</span>'
            '<span id="pronunciation-stat" style="display:none;color:var(--accent);font-size:0.8rem;font-weight:600"></span>'
            '<div class="progress-bar" id="daily-progress"></div>'
            '<span id="tasks-done" style="color:var(--text-secondary);font-size:0.8rem">✅ 0/4</span>'
            '</div>')

def gen_accent(level, week, day, focus, norm, phoneme_focus=None):
    sounds = esc_html(norm["sounds"] or "Review")
    focus = esc_html(focus)
    primary = norm["primary_text"]
    instr_ar = esc_html(norm["instr_ar"])

    # The week file's own `phoneme_focus` statement. It is NOT the same text as
    # the accent file's `focus` (they differ in all 90 weeks -- this one is the
    # fuller description of what the week is training), and it had no
    # student-facing surface anywhere: it was only ever referenced inside an
    # ai_engine prompt template. Shown here so no authored field is kept
    # without reaching the student.
    phoneme_card = ""
    if phoneme_focus:
        phoneme_card = (f'<div class="card" style="border-left:3px solid var(--accent)">'
                        f'<h2>🎧 {bl("This week\'s sound focus", "تركيز الأسبوع الصوتي")}</h2>'
                        f'<p style="line-height:1.7">{esc_html(phoneme_focus)}</p></div>')

    pairs_card = ""
    if norm["pairs"]:
        pairs_html = "<br>".join(f"<b>{esc_html(a)}</b> / <b>{esc_html(b)}</b>" for a, b in norm["pairs"][:5])
        pairs_card = f'<div class="card"><h2>📝 {bl("Minimal Pairs", "أزواج التمييز")}</h2><div class="transcript">{pairs_html}</div></div>'

    words_card = ""
    if norm["words"]:
        words = norm["words"][:8]
        # DISPLAY: the full authored list, including the ❌ contrasts — that is the
        # teaching. SPEECH: correct forms only (see spoken_words above). The two
        # deliberately differ, and the button is omitted entirely rather than
        # rendered mute if nothing survives filtering.
        words_html = " &bull; ".join(f"<b>{esc_html(w)}</b>" for w in words)
        say = spoken_words(words)
        hear_btn = ""
        if say:
            hear_btn = (f'<button class="btn btn-outline btn-sm" '
                        f'onclick="TTS.speak(\'{esc(", ".join(say))}\', 0.6)">'
                        f'🔊 {bl("Hear Words", "استمع للكلمات")}</button>')
        words_card = (f'<div class="card"><h2>🎯 {bl("Practice Words", "كلمات للتمرين")}</h2><div class="transcript">{words_html}</div>'
                      f'{hear_btn}</div>')

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Accent Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>🎯 Accent Drill</h1><p class="subtitle">Week {week} • Day {day} • {focus}</p></div>
{gamification_bar()}
<div class="arabic-text" lang="ar" dir="rtl">{instr_ar}</div>
{phoneme_card}
<div class="card"><h2>🔊 {bl("Target Sounds", "الأصوات المستهدفة")}: {sounds}</h2>
<button class="btn" onclick="TTS.speak('{esc(primary)}')">▶️ {bl("Listen to Model", "استمع للنموذج")}</button>
<div class="speed-control"><label>{bl("Speed", "السرعة")}:</label><select id="speed-select" onchange="TTS.setRate(this.value)"><option value="0.6">Slow / بطيء</option><option value="0.8" selected>Normal / عادي</option><option value="1.0">Fast / سريع</option></select></div></div>
{pairs_card}
{words_card}
<div class="card"><h2>🎙️ {bl("Say This", "قول ده")}</h2><div class="transcript"><b>"{esc_html(primary)}"</b></div>
<button class="btn btn-outline" onclick="TTS.speak('{esc(primary)}', 0.7)">🔊 {bl("Model", "نموذج")}</button></div>
<div class="card recorder-card"><h2>🎙️ {bl("Record Yourself", "سجّل نفسك")}</h2>
<div class="arabic-text" lang="ar" dir="rtl" style="margin-bottom:16px">سجّل نفسك وانت بتقول الجملة. بعدين قارن صوتك بالنموذج.</div>
<div class="recorder-controls" id="recorder-controls">
<button class="btn btn-danger recorder-btn" id="rec-start" onclick="RecorderUI.start()">⏺️ {bl("Record", "سجّل")}</button>
<button class="btn btn-outline recorder-btn" id="rec-stop" onclick="RecorderUI.stop()" style="display:none">⏹️ {bl("Stop", "قف")}</button>
<span class="rec-timer" id="rec-timer">0:00</span>
<div class="rec-indicator" id="rec-indicator"></div>
</div>
<div class="recorder-playback" id="recorder-playback" style="display:none">
<div class="card" style="background:rgba(46,204,113,0.05);border-color:var(--success);padding:16px;margin:12px 0">
<p style="color:var(--success);font-weight:600;font-size:0.9rem">🎯 {bl("Compare & Rate", "قارن وقيّم")}</p>
<p style="color:var(--text-secondary);font-size:0.8rem;margin-top:6px">{bl("Listen to both, then rate yourself:", "اسمع الاتنين وقيّم نفسك:")}</p>
</div>
<div class="ab-comparison">
<button class="btn btn-outline btn-sm" onclick="TTS.speak('{esc(primary)}', 0.7)">🔊 {bl("Listen to Model", "استمع للنموذج")}</button>
<button class="btn btn-sm" id="play-mine" onclick="RecorderUI.playMine()">🎧 {bl("Listen to Yours", "استمع لتسجيلك")}</button>
</div>
<div class="recorder-actions" style="margin-top:12px">
<button class="btn btn-outline btn-sm" onclick="RecorderUI.start()">🔄 {bl("Re-record", "سجّل تاني")}</button>
<a class="btn btn-outline btn-sm" id="rec-download" download="my-accent-recording.webm">💾 {bl("Download", "حمّل")}</a>
</div></div></div>
<div class="done-section" id="record-required-note"><p style="color:var(--text-secondary);font-size:0.9rem;line-height:1.6">🎙️ {bl("This is a recording task", "دي مهمة تسجيل")}: {bl("record yourself above, then tap", "سجّل نفسك فوق، بعدين اضغط")} <b>{bl("Send to Discord", "أرسل للديسكورد")}</b> {bl("to complete it (it posts to #showcase and marks your day).", "عشان تكمّلها (هتترفع في #showcase وتتحسب في يومك).")}</p></div>
{swipe_hint()}
<div class="nav page-nav" style="margin-top:20px"><a href="/">🏠 {bl("Home", "الرئيسية")}</a><a href="index.html">📋 {bl("Today's menu", "قائمة اليوم")}</a><a href="shadowing.html">{bl("Shadowing", "المحاكاة")} →</a></div></div>
{bottom_nav('accent')}
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


def gen_shadowing(level, week, day, theme, norm, aid):
    passage = norm["primary_text"]
    theme = esc_html(theme)
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Shadowing Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>🎧 Shadowing</h1><p class="subtitle">Week {week} • Day {day} • {theme}</p></div>
{gamification_bar()}
<div class="arabic-text" lang="ar" dir="rtl">اسمع → كرر 3 مرات → سجل المحاولة الثالثة</div>
<div class="card"><h2>📝 {bl("Passage", "المقطع")}</h2><div class="transcript">{esc_html(passage)}</div>
<button class="btn" onclick="KokoroAudio.play('{aid}','{esc(passage)}')">▶️ {bl("Play", "شغل")}</button>
<button class="btn btn-outline" onclick="KokoroAudio.stop()">⏹️ {bl("Stop", "قف")}</button>
<div class="speed-control"><label>{bl("Speed", "السرعة")}:</label><select id="speed-select" onchange="KokoroAudio.setRate(this.value)"><option value="0.6">Slow / بطيء</option><option value="0.75" selected>Normal / عادي</option><option value="1.0">Fast / سريع</option></select></div>
<p style="color:var(--text-muted);font-size:0.75rem;margin-top:10px">🎙️ {bl("Studio-quality audio when available, otherwise your browser's voice.", "صوت استوديو لما يكون متاح، وإلا صوت المتصفح.")}</p></div>
<div class="card recorder-card"><h2>🎙️ {bl("Record Your Shadow", "سجّل محاكاتك")}</h2>
<div class="arabic-text" lang="ar" dir="rtl" style="margin-bottom:16px">اسمع النموذج 3 مرات، وسجّل المحاولة الثالثة.</div>
<div class="recorder-controls" id="recorder-controls">
<button class="btn btn-danger recorder-btn" id="rec-start" onclick="RecorderUI.start()">⏺️ {bl("Record", "سجّل")}</button>
<button class="btn btn-sm" onclick="ShadowRecord.start('{aid}','{esc(passage)}')">⏺️▶️ {bl("Shadow & Record", "حاكي وسجّل")}</button>
<button class="btn btn-outline recorder-btn" id="rec-stop" onclick="RecorderUI.stop()" style="display:none">⏹️ {bl("Stop", "قف")}</button>
<span class="rec-timer" id="rec-timer">0:00</span>
<div class="rec-indicator" id="rec-indicator"></div>
</div>
<div class="recorder-playback" id="recorder-playback" style="display:none">
<div class="ab-comparison">
<button class="btn btn-outline btn-sm" onclick="KokoroAudio.play('{aid}','{esc(passage)}')">🔊 {bl("Listen to Model", "استمع للنموذج")}</button>
<button class="btn btn-sm" id="play-mine" onclick="RecorderUI.playMine()">🎧 {bl("Listen to Yours", "استمع لتسجيلك")}</button>
</div>
<div class="recorder-actions" style="margin-top:12px">
<button class="btn btn-outline btn-sm" onclick="RecorderUI.start()">🔄 {bl("Re-record", "سجّل تاني")}</button>
<a class="btn btn-outline btn-sm" id="rec-download" download="my-shadow-recording.webm">💾 {bl("Download", "حمّل")}</a>
</div></div></div>
<div class="done-section" id="record-required-note"><p style="color:var(--text-secondary);font-size:0.9rem;line-height:1.6">🎙️ {bl("This is a recording task", "دي مهمة تسجيل")}: {bl("record yourself above, then tap", "سجّل نفسك فوق، بعدين اضغط")} <b>{bl("Send to Discord", "أرسل للديسكورد")}</b> {bl("to complete it (it posts to #showcase and marks your day).", "عشان تكمّلها (هتترفع في #showcase وتتحسب في يومك).")}</p></div>
{swipe_hint()}
<div class="nav page-nav" style="margin-top:20px"><a href="/">🏠 {bl("Home", "الرئيسية")}</a><a href="accent.html">← {bl("Accent", "النطق")}</a><a href="listening.html">{bl("Listening", "الاستماع")} →</a></div></div>
{bottom_nav('shadowing')}
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


def gen_speaking(level, week, day, theme, mission):
    """Enhancement E1: Speaking as a 5th practice exercise. Free-speech
    recording task (no model audio) — record → Send to Discord → posts to
    #showcase + marks the speaking daily task. Same recorder + gate +
    watermark + nav as the other pages."""
    theme = esc_html(theme)
    if mission:
        prompt = esc_html(mission.get("prompt", ""))
        mtype = esc_html(str(mission.get("type", "free_talk")).replace("_", " ").title())
        target = int(mission.get("target_seconds", 60) or 60)
    else:
        prompt = "Talk in English about today's topic for a full minute."
        mtype = "Free Talk"
        target = 60
    target_label = bl(f"Target: {target} seconds", f"الهدف: {target} ثانية")
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Speaking Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>🎙️ Speaking</h1><p class="subtitle">Week {week} • Day {day} • {mtype}</p></div>
{gamification_bar()}
<div class="arabic-text" lang="ar" dir="rtl">اقرأ المهمة، فكّر شوية، وبعدين سجّل نفسك وأنت بتتكلم بالإنجليزي.</div>
<div class="card" style="border-left:3px solid var(--accent)"><h2>🗣️ {bl("Your Mission", "مهمتك")}</h2>
<div class="transcript" style="font-size:1.15rem;line-height:1.7">{prompt}</div>
<p style="color:var(--accent-light);margin-top:10px">⏱️ {target_label}</p></div>
<div class="card recorder-card"><h2>🎙️ {bl("Record Yourself", "سجّل نفسك")}</h2>
<div class="arabic-text" lang="ar" dir="rtl" style="margin-bottom:16px">اتكلم بطلاقة قدر ما تقدر — مش لازم يكون مثالي، المهم تتكلم.</div>
<div class="recorder-controls" id="recorder-controls">
<button class="btn btn-danger recorder-btn" id="rec-start" onclick="RecorderUI.start()">⏺️ {bl("Record", "سجّل")}</button>
<button class="btn btn-outline recorder-btn" id="rec-stop" onclick="RecorderUI.stop()" style="display:none">⏹️ {bl("Stop", "قف")}</button>
<span class="rec-timer" id="rec-timer">0:00</span>
<div class="rec-indicator" id="rec-indicator"></div>
</div>
<div class="recorder-playback" id="recorder-playback" style="display:none">
<div class="recorder-actions">
<button class="btn btn-sm" id="play-mine" onclick="RecorderUI.playMine()">🎧 {bl("Listen to Yours", "استمع لتسجيلك")}</button>
<button class="btn btn-outline btn-sm" onclick="RecorderUI.start()">🔄 {bl("Re-record", "سجّل تاني")}</button>
<a class="btn btn-outline btn-sm" id="rec-download" download="my-speaking-recording.webm">💾 {bl("Download", "حمّل")}</a>
</div></div></div>
<div class="done-section" id="record-required-note"><p style="color:var(--text-secondary);font-size:0.9rem;line-height:1.6">🎙️ {bl("This is a recording task", "دي مهمة تسجيل")}: {bl("record yourself above, then tap", "سجّل نفسك فوق، بعدين اضغط")} <b>{bl("Send to Discord", "أرسل للديسكورد")}</b> {bl("to complete it (it posts to #showcase and marks your day).", "عشان تكمّلها (هتترفع في #showcase وتتحسب في يومك).")}</p></div>
{swipe_hint()}
<div class="nav page-nav" style="margin-top:20px"><a href="/">🏠 {bl("Home", "الرئيسية")}</a><a href="vocab.html">← {bl("Vocab", "المفردات")}</a><a href="index.html">📋 {bl("Today's menu", "قائمة اليوم")}</a></div></div>
{bottom_nav('speaking')}
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


def build_review_items(level, week, weeks_vocab, weeks_grammar):
    """Phase 11C: build the WEEKLY REVIEW quiz — retrieval practice.

    Why this exists: until now "done" meant a student had been EXPOSED to the
    content (they clicked through it). Nothing ever asked them to recall it
    later without the answer in front of them. Exposure is not retention, and
    a course that only measures exposure cannot honestly claim a student
    "knows" a level.

    So this is deliberately RETRIEVAL, not re-reading:
      * items are weighted towards EARLIER weeks (spaced retrieval), because
        recalling week 2's words in week 6 is what actually builds durable
        memory -- re-reading week 6 does not;
      * both directions are tested (EN->AR and AR->EN), so a student cannot
        pass by recognising word shapes in one direction only;
      * grammar items come from a PREVIOUS week's pattern, so the pattern has
        to be remembered rather than copied off today's grammar page.

    Built entirely from already-authored content, so it works for all 90 weeks
    and all six levels the moment it ships -- no new authoring, nothing to
    keep in sync.

    Deterministic: seeded by (level, week) so the quiz is identical on every
    visit and every rebuild. A quiz that reshuffled on refresh would let a
    student reroll until they got easy items.

    `weeks_vocab`  = {week: [word dicts]} for THIS level, all weeks so far.
    `weeks_grammar` = {week: grammar dict} likewise.
    """
    rng = random.Random(f"{level}-{week}-review")

    current = list(weeks_vocab.get(week) or [])
    prior_weeks = [w for w in range(1, week) if weeks_vocab.get(w)]
    prior = [(w, item) for w in prior_weeks for item in weeks_vocab[w]]

    # Distractor pool: every word of the level we have seen up to now, so
    # wrong options are always plausible same-level words, never nonsense.
    pool = [it for w in range(1, week + 1) for it in (weeks_vocab.get(w) or [])]

    def _opts(correct, key):
        """3 options for `key` ('arabic' or 'word'), correct one included."""
        want = (correct.get(key) or "").strip()
        others, seen = [], {want.lower()}
        for cand in rng.sample(pool, k=min(len(pool), 40)):
            v = (cand.get(key) or "").strip()
            if v and v.lower() not in seen:
                seen.add(v.lower())
                others.append(v)
            if len(others) == 2:
                break
        options = [want] + others
        rng.shuffle(options)
        return options, options.index(want)

    items = []

    def _add_vocab(entry, src_week, direction):
        word = (entry.get("word") or "").strip()
        arabic = (entry.get("arabic") or "").strip()
        if not word or not arabic:
            return
        if direction == "en2ar":
            options, answer = _opts(entry, "arabic")
            if len(options) < 3:
                return
            items.append({"type": "vocab_en2ar", "week": src_week, "prompt": word,
                          "speak": word, "options": options, "answer": answer})
        else:
            options, answer = _opts(entry, "word")
            if len(options) < 3:
                return
            items.append({"type": "vocab_ar2en", "week": src_week, "prompt": arabic,
                          "speak": "", "options": options, "answer": answer})

    # 4 from EARLIER weeks (the spaced-retrieval core), 4 from this week
    # (consolidation). Week 1 has no history, so it takes all 8 from itself
    # rather than shipping a visibly thinner quiz than every other week.
    spaced = rng.sample(prior, k=min(4, len(prior))) if prior else []
    for i, (src_week, entry) in enumerate(spaced):
        _add_vocab(entry, src_week, "ar2en" if i % 2 else "en2ar")

    current_wanted = 8 - len(spaced)
    for i, entry in enumerate(rng.sample(current, k=min(current_wanted, len(current)))):
        _add_vocab(entry, week, "en2ar" if i % 2 else "ar2en")

    # 2 grammar recall items, preferring a PREVIOUS week's pattern so the
    # answer is not sitting on today's grammar page.
    g_weeks = [w for w in ([w for w in range(1, week)] or [week])
               if weeks_grammar.get(w) and (weeks_grammar[w].get("practice_fill_blank"))]
    if not g_weeks and weeks_grammar.get(week, {}).get("practice_fill_blank"):
        g_weeks = [week]
    if g_weeks:
        gw = rng.choice(g_weeks)
        gitems = [p for p in weeks_grammar[gw]["practice_fill_blank"]
                  if p.get("sentence") and p.get("answer")]
        answers_pool = [str(p["answer"]) for p in gitems]
        for p in rng.sample(gitems, k=min(2, len(gitems))):
            correct = str(p["answer"])
            wrong = [a for a in dict.fromkeys(answers_pool) if a.lower() != correct.lower()]
            options = [correct] + rng.sample(wrong, k=min(2, len(wrong)))
            if len(options) < 2:
                continue
            rng.shuffle(options)
            items.append({"type": "grammar", "week": gw, "prompt": p["sentence"],
                          "speak": "", "options": options,
                          "answer": options.index(correct)})
    return items


def gen_review(level, week, day, theme, items):
    """The weekly review quiz page (Phase 11C).

    Pass mark is 80%: below that the page tells the student exactly which
    weeks to revisit rather than just showing a low score, because the point
    of retrieval practice is to redirect study, not to grade.
    """
    theme = esc_html(theme)
    if not items:
        return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Review Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>🧠 Review</h1><p class="subtitle">Week {week} • Day {day}</p></div>
<div class="card"><p>{bl("No review items for this week yet.", "لا توجد أسئلة مراجعة للأسبوع ده بعد.")}</p></div>
<div class="nav page-nav" style="margin-top:20px"><a href="/">🏠 {bl("Home", "الرئيسية")}</a><a href="index.html">📋 {bl("Today's menu", "قائمة اليوم")}</a></div></div>
{bottom_nav('review')}
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''

    LABEL = {"vocab_en2ar": bl("What does this word mean?", "الكلمة دي معناها إيه؟"),
             "vocab_ar2en": bl("Which English word is this?", "دي أنهي كلمة إنجليزي؟"),
             "grammar": bl("Complete the sentence", "كمّل الجملة")}

    q_html = ""
    for qi, it in enumerate(items):
        opts = "".join(
            f'<div class="option" data-qi="{qi}" data-oi="{oi}"'
            f' onclick="Review.pick({qi},{oi})">{esc_html(o)}</div>'
            for oi, o in enumerate(it["options"]))
        speak = ""
        if it.get("speak"):
            speak = (f'<button class="btn btn-sm btn-outline" style="padding:2px 8px"'
                     f' onclick="TTS.speak(\'{esc(it["speak"])}\', 0.75)">🔊</button>')
        from_week = (bl(f"from week {it['week']}", f"من أسبوع {it['week']}")
                     if it["week"] != week else bl("this week", "الأسبوع ده"))
        q_html += (f'<div class="card"><h2>{qi+1}. {LABEL.get(it["type"], "")}</h2>'
                   f'<p style="color:var(--text-muted);font-size:0.8rem;margin:0 0 8px">🗓️ {from_week}</p>'
                   f'<div class="transcript" style="font-size:1.1rem">{esc_html(it["prompt"])} {speak}</div>'
                   f'<div class="options" data-qi="{qi}" style="margin-top:10px">{opts}</div>'
                   f'<div class="q-feedback" data-qi="{qi}" style="margin-top:8px"></div></div>')

    answers_json = safe_json_for_script_tag([int(i["answer"]) for i in items])
    weeks_json = safe_json_for_script_tag([int(i["week"]) for i in items])

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Review Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>🧠 Review</h1><p class="subtitle">Week {week} • Day {day} • {theme}</p></div>
{gamification_bar()}
<div class="card" style="padding:10px 14px"><p style="color:var(--accent);font-weight:600;margin:0">🔁 {bl("Weekly retrieval practice", "مراجعة أسبوعية")}</p>
<p style="color:var(--text-secondary);font-size:0.85rem;margin:4px 0 0">{bl("Most questions come from EARLIER weeks. Remembering old words is what makes them stay.", "أغلب الأسئلة من أسابيع قديمة. إنك تفتكر الكلمات القديمة هو اللي يثبتها.")}</p></div>
<div id="review-score" class="card" style="display:none"></div>
{q_html}
<div class="done-section" data-exercise="review"><div id="done-status" class="done-status" style="color:var(--text-secondary);font-size:0.85rem">{bl("Completes when you answer every question.", "بيتقفل لما تجاوب على كل الأسئلة.")}</div><input type="checkbox" class="checkbox" style="display:none" onchange="if(this.checked)Progress.markDone('{level}',{week},{day},'review')"><button class="btn btn-sm btn-outline done-fallback" style="margin-top:8px">✔️ {bl("I've finished — mark done", "خلصت — علّم تم")}</button></div>
{swipe_hint()}
<div class="nav page-nav" style="margin-top:20px"><a href="/">🏠 {bl("Home", "الرئيسية")}</a><a href="index.html">📋 {bl("Today's menu", "قائمة اليوم")}</a><a href="vocab.html">📖 {bl("Vocab", "المفردات")} →</a></div></div>
{bottom_nav('review')}
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>
<script>
const reviewAnswers={answers_json};
const reviewWeeks={weeks_json};
const Review={{
  _done:new Set(), _wrongWeeks:[],
  pick(qi,oi){{
    const box=document.querySelector('.options[data-qi="'+qi+'"]');
    const fb=document.querySelector('.q-feedback[data-qi="'+qi+'"]');
    if(!box||box.dataset.answered)return;
    box.dataset.answered='1';
    const correct=reviewAnswers[qi];
    box.querySelectorAll('.option').forEach(el=>{{
      el.style.pointerEvents='none';
      const i=parseInt(el.dataset.oi,10);
      if(i===correct)el.classList.add('correct');
      else if(i===oi)el.classList.add('wrong');
    }});
    const ok=(oi===correct);
    if(!ok)this._wrongWeeks.push(reviewWeeks[qi]);
    if(fb)fb.innerHTML=ok
      ?'<span style="color:var(--success);font-weight:600">✅ '+{json.dumps(bl("Correct", "صح"))}+'</span>'
      :'<span style="color:var(--danger)">❌</span>';
    this._done.add(qi);
    if(this._done.size>=reviewAnswers.length)this._finish();
  }},
  _finish(){{
    const total=reviewAnswers.length;
    const wrong=this._wrongWeeks.length, score=total-wrong;
    const pct=Math.round(score/total*100);
    const box=document.getElementById('review-score');
    if(box){{
      let msg;
      if(pct>=80){{
        msg='<p style="color:var(--success);font-weight:600">'+{json.dumps(bl("Strong recall — keep going.", "ذاكرتك قوية — كمّل."))}+'</p>';
      }} else {{
        const weeks=[...new Set(this._wrongWeeks)].sort((a,b)=>a-b).join(', ');
        msg='<p style="color:var(--danger);font-weight:600">'+{json.dumps(bl("Revisit these weeks:", "ارجع للأسابيع دي:"))}+' '+weeks+'</p>';
      }}
      box.innerHTML='<h2>🏆 '+score+'/'+total+' ('+pct+'%)</h2>'+msg;
      box.style.display='block';
      box.scrollIntoView({{behavior:'smooth',block:'center'}});
    }}
    if(window.ExerciseComplete)window.ExerciseComplete();
  }}
}};
</script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


def gen_mediation(level, week, day, theme, mediation):
    """Phase 11B: MEDIATION — the fourth CEFR mode, previously absent entirely.

    Mediation is relaying/explaining/summarising for someone else. Nothing in
    the 7 daily tasks asked a student to do it, so every level's `.M.`
    descriptors were taught by no week.

    It is graded by a KEY-POINTS CHECKLIST rather than by machine-marking free
    text, because that is genuinely how mediation is assessed: did the
    essential information get across? The student writes their relay, then
    reveals the model answer and confirms each fact they conveyed. That is
    honest self-assessment against explicit criteria -- not a fake auto-grade.

    A1.M.2 (signal understanding / ask for help with a single word or short
    phrase) is delivered as the "signal phrases" card, each playable.
    """
    theme = esc_html(theme)
    if not mediation:
        return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Mediation Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>🤝 Mediation</h1><p class="subtitle">Week {week} • Day {day}</p></div>
<div class="card"><p>{bl("The mediation task for this week is not published yet.", "مهمة الوساطة للأسبوع ده لسه مش منشورة.")}</p></div>
<div class="nav page-nav" style="margin-top:20px"><a href="/">🏠 {bl("Home", "الرئيسية")}</a><a href="index.html">📋 {bl("Today's menu", "قائمة اليوم")}</a></div></div>
{bottom_nav('mediation')}
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''

    title = esc_html(mediation.get("title", ""))
    title_ar = esc_html(mediation.get("title_ar", ""))
    scen = mediation.get("scenario") or {}
    task = mediation.get("task") or {}
    model = mediation.get("model_answer") or {}
    source = mediation.get("source", "")

    points = [p for p in (mediation.get("key_points") or []) if p.get("en")]
    points_html = ""
    for pi, p in enumerate(points):
        points_html += (
            f'<label style="display:flex;gap:10px;align-items:flex-start;padding:8px 0;'
            f'border-bottom:1px solid var(--border);cursor:pointer">'
            f'<input type="checkbox" class="kp-check" data-kp="{pi}"'
            f' onchange="Mediation.tick()" style="margin-top:5px">'
            f'<span><span>{esc_html(p["en"])}</span>'
            + (f'<br><span class="arabic-text" lang="ar" dir="rtl">{esc_html(p.get("ar",""))}</span>'
               if p.get("ar") else '')
            + '</span></label>')

    signals = [s for s in (mediation.get("signal_phrases") or []) if s.get("en")]
    signals_html = ""
    for s in signals:
        signals_html += (
            f'<div style="padding:8px 0;border-bottom:1px solid var(--border)">'
            f'<b>{esc_html(s["en"])}</b>'
            f' <button class="btn btn-sm btn-outline" style="padding:2px 8px"'
            f' onclick="TTS.speak(\'{esc(s["en"])}\', 0.7)">🔊</button>'
            + (f'<br><span class="arabic-text" lang="ar" dir="rtl">{esc_html(s.get("ar",""))}</span>'
               if s.get("ar") else '')
            + '</div>')

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Mediation Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>🤝 Mediation</h1><p class="subtitle">Week {week} • Day {day} • {theme}</p></div>
{gamification_bar()}
<div class="card" style="padding:10px 14px"><p style="color:var(--accent);font-weight:600;margin:0">📅 {bl("This week's mediation task", "مهمة الوساطة للأسبوع")}</p>
<p style="color:var(--text-secondary);font-size:0.85rem;margin:4px 0 0">{bl("Mediation means helping someone else understand. This is real life, not a test.", "الوساطة معناها إنك تساعد حد تاني يفهم. دي حياة حقيقية، مش امتحان.")}</p></div>
<div class="card"><h2 style="margin:0">{title}</h2>
{f'<p class="arabic-text" lang="ar" dir="rtl" style="margin-top:6px">{title_ar}</p>' if title_ar else ''}</div>
<div class="card"><h2>👥 {bl("The situation", "الموقف")}</h2>
<p style="line-height:1.7">{esc_html(scen.get("en",""))}</p>
{f'<p class="arabic-text" lang="ar" dir="rtl" style="margin-top:8px">{esc_html(scen.get("ar",""))}</p>' if scen.get("ar") else ''}</div>
<div class="card" style="border-left:3px solid var(--accent)"><h2>📨 {bl("What you heard / read", "اللي سمعته أو قريته")}</h2>
<div class="transcript" style="font-size:1.05rem;line-height:1.8">{esc_html(source)}</div>
<button class="btn btn-sm" style="margin-top:10px" onclick="TTS.speak('{esc(source)}', 0.75)">🔊 {bl("Listen", "استمع")}</button></div>
<div class="card"><h2>🎯 {bl("Your job", "مهمتك")}</h2>
<p style="line-height:1.7">{esc_html(task.get("en",""))}</p>
{f'<p class="arabic-text" lang="ar" dir="rtl" style="margin-top:8px">{esc_html(task.get("ar",""))}</p>' if task.get("ar") else ''}
<textarea id="mediation-answer" class="quiz-input" rows="4" style="width:100%;margin-top:12px;resize:vertical" placeholder="{bl_attr("Write what you would say...", "اكتب اللي هتقوله...")}"></textarea>
<button class="btn btn-sm" style="margin-top:10px" onclick="Mediation.reveal()">👀 {bl("Show the model answer", "وريني الإجابة النموذجية")}</button></div>
<div class="card" id="model-card" style="display:none;border-left:3px solid var(--success)"><h2>✅ {bl("A good answer", "إجابة كويسة")}</h2>
<p style="line-height:1.8">{esc_html(model.get("en",""))}</p>
{f'<p class="arabic-text" lang="ar" dir="rtl" style="margin-top:8px">{esc_html(model.get("ar",""))}</p>' if model.get("ar") else ''}
<button class="btn btn-sm btn-outline" style="margin-top:10px" onclick="TTS.speak('{esc(model.get("en",""))}', 0.75)">🔊 {bl("Listen", "استمع")}</button></div>
<div class="card"><h2>📋 {bl("Did you pass on everything?", "نقلت كل حاجة؟")}</h2>
<p style="color:var(--text-secondary);font-size:0.9rem">{bl("Tick each fact you passed on. Mediation succeeds when the other person gets the important information.", "علّم على كل معلومة نقلتها. الوساطة تنجح لما الشخص التاني يفهم المعلومة المهمة.")}</p>
{points_html}
<p id="kp-progress" style="margin-top:10px;color:var(--text-secondary);font-size:0.9rem">0/{len(points)}</p></div>
<div class="card"><h2>🙋 {bl("If you do not understand", "لو مش فاهم")}</h2>
<p style="color:var(--text-secondary);font-size:0.9rem">{bl("Use one short phrase — and a gesture is fine. Asking for help is a skill, not a failure.", "استخدم جملة قصيرة — والإشارة مقبولة. إنك تطلب مساعدة دي مهارة، مش فشل.")}</p>
{signals_html}</div>
<div class="done-section" data-exercise="mediation"><div id="done-status" class="done-status" style="color:var(--text-secondary);font-size:0.85rem">{bl("Completes when you tick every fact you passed on.", "بيتقفل لما تعلّم على كل المعلومات اللي نقلتها.")}</div><input type="checkbox" class="checkbox" style="display:none" onchange="if(this.checked)Progress.markDone('{level}',{week},{day},'mediation')"><button class="btn btn-sm btn-outline done-fallback" style="margin-top:8px">✔️ {bl("I've finished — mark done", "خلصت — علّم تم")}</button></div>
{swipe_hint()}
<div class="nav page-nav" style="margin-top:20px"><a href="/">🏠 {bl("Home", "الرئيسية")}</a><a href="index.html">📋 {bl("Today's menu", "قائمة اليوم")}</a><a href="reading.html">📖 {bl("Reading", "القراءة")} →</a></div></div>
{bottom_nav('mediation')}
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>
<script>
const Mediation={{
  _total:{len(points)},
  reveal(){{ const c=document.getElementById('model-card'); if(c)c.style.display='block'; }},
  tick(){{
    const done=document.querySelectorAll('.kp-check:checked').length;
    const p=document.getElementById('kp-progress');
    if(p)p.textContent=done+'/'+this._total;
    if(this._total>0&&done>=this._total&&window.ExerciseComplete)window.ExerciseComplete();
  }}
}};
</script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


def gen_reading(level, week, day, theme, reading):
    """Phase 11B: READING — the CEFR mode that had no task at all.

    The 7 daily tasks covered listening, speaking, writing, interaction and the
    enabling skills, but nothing ever asked a student to READ. That is why
    A1-B2 each carried reading descriptors (.R.) that no week taught.

    One authored passage per week (weekly, like grammar), rolled out level by
    level behind the owner approval gate -- so a level with no authored
    passages renders an honest "coming soon", never another level's text.

    Completion is by genuine engagement: the comprehension questions must all
    be answered before the exercise auto-completes.
    """
    theme = esc_html(theme)
    if not reading:
        return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Reading Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>📖 Reading</h1><p class="subtitle">Week {week} • Day {day}</p></div>
<div class="card"><p>{bl("The reading passage for this week is not published yet.", "نص القراءة للأسبوع ده لسه مش منشور.")}</p></div>
<div class="nav page-nav" style="margin-top:20px"><a href="/">🏠 {bl("Home", "الرئيسية")}</a><a href="index.html">📋 {bl("Today's menu", "قائمة اليوم")}</a></div></div>
{bottom_nav('reading')}
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''

    title = esc_html(reading.get("title", ""))
    title_ar = esc_html(reading.get("title_ar", ""))
    gist_ar = esc_html(reading.get("gist_ar", ""))
    word_count = int(reading.get("word_count") or 0)
    # Render the passage as sentence-level blocks. A1.R.4 is literally "can
    # understand very short, simple texts A SINGLE PHRASE AT A TIME", so each
    # sentence is individually readable/playable rather than one dense wall.
    # Split AFTER any closing quote so dialogue stays intact: splitting on
    # (?<=[.!?])\s+ alone tore '"Good morning, Omar. How are you?"' apart at
    # the full stop and left the closing quote stranded on the next block.
    # Match each sentence INCLUDING any closing quote. A plain
    # re.split(r'(?<=[.!?])\s+') tore '"Good morning, Omar. How are you?"'
    # apart at the full stop and stranded the closing quote on the next
    # block. (A lookbehind can't express "optional quote" -- Python requires
    # fixed-width lookbehind -- hence findall.)
    _text = reading.get("text", "")
    sentences = [s.strip() for s in
                 re.findall(r'[^.!?]*[.!?]+[\"\u201d\u2019\']*', _text) if s.strip()]
    _matched = "".join(sentences)
    if len(_matched.replace(" ", "")) < len(_text.replace(" ", "")):
        # Trailing fragment with no final punctuation — never drop text.
        sentences.append(_text[len(_matched):].strip())
    sentences = [s for s in sentences if s]
    passage = ""
    for s in sentences:
        passage += (f'<p style="margin:8px 0;line-height:1.9;font-size:1.05rem">{esc_html(s)}'
                    f' <button class="btn btn-sm btn-outline" style="padding:2px 8px"'
                    f' onclick="TTS.speak(\'{esc(s)}\', 0.75)">🔊</button></p>')

    glossary = ""
    gitems = [g for g in (reading.get("glossary") or []) if g.get("word")]
    if gitems:
        rows = "".join(
            f'<div style="padding:6px 0;border-bottom:1px solid var(--border)">'
            f'<b>{esc_html(g["word"])}</b>'
            f'<span class="arabic-text" lang="ar" dir="rtl" style="margin-inline-start:10px">{esc_html(g.get("ar",""))}</span>'
            f'</div>' for g in gitems)
        glossary = (f'<div class="card"><h2>📕 {bl("Words to help you", "كلمات تساعدك")}</h2>{rows}</div>')

    questions = [q for q in (reading.get("questions") or [])
                 if q.get("q") and q.get("options")]
    q_html = ""
    for qi, q in enumerate(questions):
        opts = "".join(
            f'<div class="option" data-qi="{qi}" data-oi="{oi}"'
            f' onclick="ReadingQuiz.pick({qi},{oi})">{esc_html(o)}</div>'
            for oi, o in enumerate(q["options"]))
        q_html += (f'<div class="card"><h2>❓ {bl("Question", "سؤال")} {qi+1}</h2>'
                   f'<p style="line-height:1.7">{esc_html(q["q"])}</p>'
                   + (f'<p class="arabic-text" lang="ar" dir="rtl" style="margin:6px 0">{esc_html(q.get("q_ar",""))}</p>'
                      if q.get("q_ar") else '')
                   + f'<div class="options" data-qi="{qi}">{opts}</div>'
                   f'<div class="q-feedback" data-qi="{qi}" style="margin-top:8px"></div></div>')

    answers_json = safe_json_for_script_tag([int(q.get("answer", 0)) for q in questions])
    done_hint = (bl("Completes automatically when you answer every question.",
                    "بيتقفل تلقائيًا لما تجاوب على كل الأسئلة.")
                 if questions else
                 bl("Read the passage, then mark it done.", "اقرا النص وبعدين علّمه تم."))

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Reading Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>📖 Reading</h1><p class="subtitle">Week {week} • Day {day} • {theme}</p></div>
{gamification_bar()}
<div class="card" style="padding:10px 14px"><p style="color:var(--accent);font-weight:600;margin:0">📅 {bl("This week's passage", "نص الأسبوع")} · {word_count} {bl("words", "كلمة")}</p>
<p style="color:var(--text-secondary);font-size:0.85rem;margin:4px 0 0">{bl("One passage per week — read it again each day to get faster.", "نص واحد كل أسبوع — اقراه كل يوم عشان تبقى أسرع.")}</p></div>
<div class="card"><h2 style="margin:0">{title}</h2>
{f'<p class="arabic-text" lang="ar" dir="rtl" style="margin-top:6px">{title_ar}</p>' if title_ar else ''}</div>
{f'<div class="arabic-text" lang="ar" dir="rtl">{gist_ar}</div>' if gist_ar else ''}
<div class="card"><h2>📄 {bl("Read", "اقرا")}</h2>{passage}
<button class="btn btn-sm" onclick="ReadingQuiz.playAll()">🔊 {bl("Listen to the whole passage", "استمع للنص كله")}</button></div>
{glossary}
{q_html}
<div class="done-section" data-exercise="reading"><div id="done-status" class="done-status" style="color:var(--text-secondary);font-size:0.85rem">{done_hint}</div><input type="checkbox" class="checkbox" style="display:none" onchange="if(this.checked)Progress.markDone('{level}',{week},{day},'reading')"><button class="btn btn-sm btn-outline done-fallback" style="margin-top:8px">✔️ {bl("I've finished — mark done", "خلصت — علّم تم")}</button></div>
{swipe_hint()}
<div class="nav page-nav" style="margin-top:20px"><a href="/">🏠 {bl("Home", "الرئيسية")}</a><a href="index.html">📋 {bl("Today's menu", "قائمة اليوم")}</a><a href="grammar.html">📐 {bl("Grammar", "القواعد")} →</a></div></div>
{bottom_nav('reading')}
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>
<script>
const readingAnswers={answers_json};
const readingText={safe_json_for_script_tag(reading.get("text", ""))};
const ReadingQuiz={{
  _answered:new Set(),
  playAll(){{ if(window.TTS) TTS.speak(readingText, 0.75); }},
  pick(qi,oi){{
    const box=document.querySelector('.options[data-qi="'+qi+'"]');
    const fb=document.querySelector('.q-feedback[data-qi="'+qi+'"]');
    if(!box||box.dataset.answered)return;
    box.dataset.answered='1';
    const correct=readingAnswers[qi];
    box.querySelectorAll('.option').forEach(el=>{{
      el.style.pointerEvents='none';
      const i=parseInt(el.dataset.oi,10);
      if(i===correct)el.classList.add('correct');
      else if(i===oi)el.classList.add('wrong');
    }});
    if(fb)fb.innerHTML=(oi===correct)
      ?'<span style="color:var(--success);font-weight:600">✅ '+{json.dumps(bl("Correct", "صح"))}+'</span>'
      :'<span style="color:var(--danger)">❌ '+{json.dumps(bl("Look at the text again", "بصّ على النص تاني"))}+'</span>';
    this._answered.add(qi);
    if(this._answered.size>=readingAnswers.length&&window.ExerciseComplete)window.ExerciseComplete();
  }}
}};
</script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


def gen_grammar(level, week, day, theme, grammar, grammar_point=None):
    """Phase 11A-3: the WEEKLY grammar pattern as a real, tracked exercise.

    The curriculum authors one rich bilingual pattern per week in
    content/{level}/grammar/weekN.json -- 90 patterns carrying 1,208
    sub-items (formula, formula_visual, when_to_use, the
    why_arabic_speakers_struggle contrast, 5 examples, 3 common_errors,
    5 practice_fill_blank, quick_rule, mnemonic, connect_to_speaking).

    Before this page, NONE of it was practisable: grammar reached students
    only as a passive Wednesday #cheat-sheets post -- no page, no exercise,
    no completion, no mastery. A student could "finish" a level having never
    practised a single grammar point.

    It is WEEKLY, not daily: the same pattern is the target all week (the
    page states this plainly), and completion is tracked per day so
    re-practising still levels the tier. It is deliberately NOT one of the
    calendar's required exercises -- see database.WEEKLY_EXERCISES.
    """
    theme = esc_html(theme)
    if not grammar:
        # Honest empty state -- never fabricate a pattern.
        return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Grammar Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>📐 Grammar</h1><p class="subtitle">Week {week} • Day {day}</p></div>
<div class="card"><p>{bl("No grammar pattern is authored for this week yet.", "لا يوجد نمط قواعد لهذا الأسبوع بعد.")}</p></div>
<div class="nav page-nav" style="margin-top:20px"><a href="/">🏠 {bl("Home", "الرئيسية")}</a><a href="index.html">📋 {bl("Today's menu", "قائمة اليوم")}</a></div></div>
{bottom_nav('grammar')}
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''

    name = esc_html(grammar.get("pattern_name", ""))
    name_ar = esc_html(grammar.get("pattern_name_ar", ""))
    formula = esc_html(grammar.get("formula", ""))
    formula_visual = esc_html(grammar.get("formula_visual", ""))
    when_to_use = esc_html(grammar.get("when_to_use", ""))
    when_to_use_ar = esc_html(grammar.get("when_to_use_ar", ""))
    why_struggle = esc_html(grammar.get("why_arabic_speakers_struggle", ""))
    quick_rule = esc_html(grammar.get("quick_rule", ""))
    quick_rule_ar = esc_html(grammar.get("quick_rule_ar", ""))
    mnemonic = esc_html(grammar.get("mnemonic", ""))
    connect = esc_html(grammar.get("connect_to_speaking", ""))

    # --- The week file's own grammar_point gloss ---
    # A short bilingual summary authored alongside the pattern. It had no
    # student-facing surface at all (the title merely echoes grammar_pattern
    # in 73 of 90 weeks, but the en/ar gloss is unique authored text). Shown
    # so no authored field is kept without reaching the student.
    point_card = ""
    if isinstance(grammar_point, dict):
        p_en = esc_html(grammar_point.get("en", ""))
        p_ar = esc_html(grammar_point.get("ar", ""))
        if p_en or p_ar:
            point_card = (f'<div class="card"><h2>🔎 {bl("In short", "بإيجاز")}</h2>'
                          + (f'<p style="line-height:1.7">{p_en}</p>' if p_en else '')
                          + (f'<p class="arabic-text" lang="ar" dir="rtl" style="margin-top:8px">{p_ar}</p>' if p_ar else '')
                          + '</div>')

    # --- Formula / quick rule ---
    formula_card = f'<div class="card" style="border-left:3px solid var(--accent)"><h2>🧩 {bl("The Pattern", "النمط")}</h2>'
    if formula:
        formula_card += f'<div class="transcript" style="font-size:1.2rem;line-height:1.7"><b>{formula}</b></div>'
    if formula_visual:
        formula_card += f'<p style="color:var(--accent-light);margin:10px 0;font-family:monospace">{formula_visual}</p>'
    if quick_rule:
        formula_card += f'<p style="margin-top:12px">⚡ {quick_rule}</p>'
    if quick_rule_ar:
        formula_card += f'<p class="arabic-text" lang="ar" dir="rtl" style="margin-top:6px">{quick_rule_ar}</p>'
    formula_card += '</div>'

    # --- When to use ---
    use_card = ""
    if when_to_use or when_to_use_ar:
        use_card = f'<div class="card"><h2>📍 {bl("When to use it", "امتى تستخدمه")}</h2>'
        if when_to_use:
            use_card += f'<p style="line-height:1.7">{when_to_use}</p>'
        if when_to_use_ar:
            use_card += f'<p class="arabic-text" lang="ar" dir="rtl" style="margin-top:8px">{when_to_use_ar}</p>'
        use_card += '</div>'

    # --- Why Arabic speakers struggle (the L1-contrast that makes this
    #     curriculum specific to its students, previously never shown) ---
    struggle_card = ""
    if why_struggle:
        struggle_card = (f'<div class="card" style="border-left:3px solid var(--danger)">'
                         f'<h2>⚠️ {bl("Why this is tricky for Arabic speakers", "ليه دي صعبة على العربي")}</h2>'
                         f'<p style="line-height:1.7">{why_struggle}</p></div>')

    # --- Examples (with TTS) ---
    ex_html = ""
    for ex in (grammar.get("examples") or []):
        en = esc_html(ex.get("en", ""))
        ar = esc_html(ex.get("ar", ""))
        structure = esc_html(ex.get("structure", ""))
        if not en:
            continue
        ex_html += (f'<div style="padding:12px 0;border-bottom:1px solid var(--border)">'
                    f'<p style="font-size:1.05rem;line-height:1.6">{en}'
                    f' <button class="btn btn-sm btn-outline" style="margin-inline-start:8px"'
                    f' onclick="TTS.speak(\'{esc(ex.get("en", ""))}\', 0.75)">🔊</button></p>'
                    + (f'<p class="arabic-text" lang="ar" dir="rtl" style="margin-top:4px">{ar}</p>' if ar else '')
                    + (f'<p style="color:var(--text-muted);font-size:0.85rem;font-family:monospace;margin-top:4px">{structure}</p>' if structure else '')
                    + '</div>')
    examples_card = (f'<div class="card"><h2>💡 {bl("Examples", "أمثلة")}</h2>{ex_html}</div>') if ex_html else ""

    # --- Common errors ---
    err_html = ""
    for er in (grammar.get("common_errors") or []):
        wrong = esc_html(er.get("wrong", ""))
        correct = esc_html(er.get("correct", ""))
        expl = esc_html(er.get("explanation", ""))
        if not (wrong or correct):
            continue
        err_html += (f'<div style="padding:12px 0;border-bottom:1px solid var(--border)">'
                     f'<p style="color:var(--danger)">❌ <s>{wrong}</s></p>'
                     f'<p style="color:var(--success)">✅ {correct}</p>'
                     + (f'<p style="color:var(--text-secondary);font-size:0.9rem;margin-top:4px">{expl}</p>' if expl else '')
                     + '</div>')
    errors_card = (f'<div class="card"><h2>🚫 {bl("Common mistakes", "أخطاء شائعة")}</h2>{err_html}</div>') if err_html else ""

    # --- Practice: fill in the blank (this is what makes it an EXERCISE
    #     rather than another cheat sheet, and what auto-completes it) ---
    practice = [p for p in (grammar.get("practice_fill_blank") or [])
                if p.get("sentence") and p.get("answer")]
    practice_card = ""
    if practice:
        rows = ""
        for i, p in enumerate(practice):
            rows += (f'<div class="question" data-gi="{i}" style="padding:12px 0;border-bottom:1px solid var(--border)">'
                     f'<p style="font-size:1.05rem;line-height:1.7">{esc_html(p["sentence"])}</p>'
                     f'<input class="quiz-input g-answer" data-gi="{i}" type="text" autocomplete="off"'
                     f' placeholder="{bl_attr("your answer", "جوابك")}" style="margin-top:8px;width:100%">'
                     f'<button class="btn btn-sm" style="margin-top:8px" onclick="GrammarPractice.check({i})">✓ {bl("Check", "صحح")}</button>'
                     f'<div class="g-feedback" data-gi="{i}" style="margin-top:8px"></div></div>')
        practice_card = (f'<div class="card"><h2>✍️ {bl("Practice", "تمرين")}</h2>'
                         f'<p style="color:var(--text-secondary);font-size:0.9rem">'
                         f'{bl("Fill in the blank. Completing all of them marks this exercise done.", "املا الفراغ. لما تخلص كلهم التمرين يتحسب.")}</p>'
                         f'{rows}</div>')

    # --- Mnemonic + link to speaking ---
    tail = ""
    if mnemonic:
        tail += (f'<div class="card"><h2>🧠 {bl("Remember it", "افتكرها")}</h2>'
                 f'<p style="font-size:1.05rem">{mnemonic}</p></div>')
    if connect:
        tail += (f'<div class="card" style="border-left:3px solid var(--accent)">'
                 f'<h2>🎙️ {bl("Use it when you speak", "استخدمها وانت بتتكلم")}</h2>'
                 f'<p style="line-height:1.7">{connect}</p></div>')

    answers_json = safe_json_for_script_tag([str(p["answer"]) for p in practice])
    done_hint = (bl("Completes automatically when you finish the practice.",
                    "بيتقفل تلقائيًا لما تخلص التمرين.")
                 if practice else
                 bl("Read the pattern, then mark it done.", "اقرا النمط وبعدين علّمه تم."))

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Grammar Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>📐 Grammar</h1><p class="subtitle">Week {week} • Day {day} • {theme}</p></div>
{gamification_bar()}
<div class="card" style="padding:10px 14px"><p style="color:var(--accent);font-weight:600;margin:0">📅 {bl("This week's pattern", "نمط الأسبوع")}</p>
<p style="color:var(--text-secondary);font-size:0.85rem;margin:4px 0 0">{bl("One pattern per week — it stays the same all week, so practise it every day.", "نمط واحد كل أسبوع — بيفضل نفسه طول الأسبوع، فاتمرن عليه كل يوم.")}</p></div>
<div class="card"><h2 style="margin:0">{name}</h2>
{f'<p class="arabic-text" lang="ar" dir="rtl" style="margin-top:6px">{name_ar}</p>' if name_ar else ''}</div>
{point_card}
{formula_card}
{use_card}
{struggle_card}
{examples_card}
{errors_card}
{practice_card}
{tail}
<div class="done-section" data-exercise="grammar"><div id="done-status" class="done-status" style="color:var(--text-secondary);font-size:0.85rem">{done_hint}</div><input type="checkbox" class="checkbox" style="display:none" onchange="if(this.checked)Progress.markDone('{level}',{week},{day},'grammar')"><button class="btn btn-sm btn-outline done-fallback" style="margin-top:8px">✔️ {bl("I've finished — mark done", "خلصت — علّم تم")}</button></div>
{swipe_hint()}
<div class="nav page-nav" style="margin-top:20px"><a href="/">🏠 {bl("Home", "الرئيسية")}</a><a href="index.html">📋 {bl("Today's menu", "قائمة اليوم")}</a><a href="vocab.html">{bl("Vocab", "المفردات")} →</a></div></div>
{bottom_nav('grammar')}
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>
<script>
const grammarAnswers={answers_json};
const GrammarPractice={{
  _done:new Set(),
  _norm(s){{return String(s||'').trim().toLowerCase().replace(/[.,!?;:'"]/g,'');}},
  check(i){{
    const input=document.querySelector('.g-answer[data-gi="'+i+'"]');
    const fb=document.querySelector('.g-feedback[data-gi="'+i+'"]');
    if(!input||!fb)return;
    const expected=grammarAnswers[i]||'';
    const ok=this._norm(input.value)===this._norm(expected);
    fb.innerHTML=ok
      ?'<span style="color:var(--success);font-weight:600">✅ '+{json.dumps(bl("Correct", "صح"))}+'</span>'
      :'<span style="color:var(--danger)">❌ '+{json.dumps(bl("Answer", "الإجابة"))}+': <b>'+expected+'</b></span>';
    // Counts as attempted either way -- students must not be trapped by a
    // typo, and the correct answer is revealed so the attempt still teaches.
    this._done.add(i);
    if(this._done.size>=grammarAnswers.length&&window.ExerciseComplete)window.ExerciseComplete();
  }}
}};
</script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


def gen_listening(level, week, day, theme, day_vocab, all_week_vocab, day_listening=None):
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
            opts_html += f'<div class="option"{data_c} onclick="checkAnswer(this,{is_correct})">{esc_html(o["arabic"])}</div>'
        q_html += (f'<div class="card"><h2>🔊 {bl("Word", "كلمة")} {qi+1}</h2>'
                   f'<button class="btn btn-sm" onclick="TTS.speak(\'{esc(word["word"])}\', 0.7)">▶️ {bl("Play Word", "شغل الكلمة")}</button>'
                   f'<div class="question" style="margin-top:14px"><p>❓ {bl("What does this word mean?", "معنى الكلمة دي إيه؟")}</p>'
                   f'<div class="options">{opts_html}</div></div></div>')

    if not q_html:
        q_html = f'<div class="card"><p>{bl("No vocabulary available for this day yet.", "لا توجد مفردات متاحة لهذا اليوم حتى الآن.")}</p></div>'

    theme = esc_html(theme)

    # Dictation set. The week file's authored `listening` array
    # ({say_en, expected, hint_ar}, 5 per week, 450 across the 90 authored
    # weeks) is the curriculum's CURATED dictation target -- but it had no
    # consumer at all: this page used to build dictation from `vocabulary`
    # instead, so the authored selection and all 450 Arabic hints reached
    # nobody. Authored items now come first (they are the point of the
    # exercise and carry the hint), then any of the day's vocabulary words
    # not already covered, so the day still contributes something specific.
    # Capped so a day never becomes a marathon.
    dictation_items = []
    seen = set()
    for it in (day_listening or []):
        expected = (it.get("expected") or it.get("say_en") or "").strip()
        if not expected or expected.lower() in seen:
            continue
        seen.add(expected.lower())
        dictation_items.append({
            "say": it.get("say_en") or expected,
            "expected": expected,
            "hint": it.get("hint_ar") or "",
        })
    for w in day_vocab:
        if len(dictation_items) >= 8:
            break
        word = (w.get("word") or "").strip()
        if not word or word.lower() in seen:
            continue
        seen.add(word.lower())
        dictation_items.append({
            "say": word,
            "expected": word,
            "hint": w.get("arabic") or "",
        })
    dictation_json = safe_json_for_script_tag(dictation_items)

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Listening Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>👂 Listening</h1><p class="subtitle">Week {week} • Day {day} • {theme}</p></div>
{gamification_bar()}
<div class="arabic-text" lang="ar" dir="rtl">اسمع الكلمة واختار المعنى الصحيح. ممكن تسمع أكتر من مرة.</div>
<div class="mode-toggle">
<button class="mode-btn active" data-mode="quiz" onclick="Dictation.showQuiz()">❓ {bl("Quiz", "اختبار")}</button>
<button class="mode-btn" data-mode="dictation" onclick="Dictation.show()">✍️ {bl("Dictation", "إملاء")}</button>
</div>
<div id="listening-quiz-section">
{q_html}
</div>
<div id="dictation-section" style="display:none"></div>
<div class="done-section" data-exercise="listening"><div id="done-status" class="done-status" style="color:var(--text-secondary);font-size:0.85rem">{bl("Completes automatically when you answer the quiz.", "بيتقفل تلقائيًا لما تجاوب على الاختبار.")}</div><input type="checkbox" class="checkbox" style="display:none" onchange="if(this.checked)Progress.markDone('{level}',{week},{day},'listening')"><button class="btn btn-sm btn-outline done-fallback" style="margin-top:8px">✔️ {bl("I've finished — mark done", "خلصت — علّم تم")}</button></div>
{swipe_hint()}
<div class="nav page-nav" style="margin-top:20px"><a href="/">🏠 {bl("Home", "الرئيسية")}</a><a href="shadowing.html">← {bl("Shadowing", "المحاكاة")}</a><a href="vocab.html">{bl("Vocab", "المفردات")} →</a></div></div>
{bottom_nav('listening')}
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>
<script>const dictationWords={dictation_json};document.addEventListener('DOMContentLoaded',()=>Dictation.init(dictationWords));var _lqTotal={len(questions)},_lqAnswered=0;function checkAnswer(el,c){{var opts=el.closest('.options');if(opts.dataset.answered)return;opts.dataset.answered='1';opts.querySelectorAll('.option').forEach(o=>o.style.pointerEvents='none');if(c)el.classList.add('correct');else{{el.classList.add('wrong');opts.querySelector('[data-correct]').classList.add('correct')}}_lqAnswered++;if(_lqTotal>0&&_lqAnswered>=_lqTotal&&window.ExerciseComplete)window.ExerciseComplete();}}</script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


def gen_vocab(level, week, day, theme, words):
    theme = esc_html(theme)
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Vocabulary Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>📖 Vocabulary</h1><p class="subtitle">Week {week} • Day {day} • {theme}</p></div>
{gamification_bar()}
<div class="arabic-text" lang="ar" dir="rtl">اختر طريقة التمرين:<br>📖 <b>بطاقات</b> — شوف الكلمة ومعناها.<br>✍️ <b>ترجم</b> — يظهر لك المعنى بالعربي، اكتب الكلمة بالإنجليزي.<br>🎧 <b>اسمع واكتب</b> — اسمع الكلمة واكتبها.</div>
<div class="mode-toggle">
<button class="mode-btn active" data-mode="flashcard" onclick="InteractiveVocab.switchMode('flashcard')">📖 {bl("Cards", "بطاقات")}</button>
<button class="mode-btn" data-mode="quiz" onclick="InteractiveVocab.switchMode('quiz')">✍️ {bl("Translate", "ترجم")}</button>
<button class="mode-btn" data-mode="listen" onclick="InteractiveVocab.switchMode('listen')">🎧 {bl("Listen & Type", "اسمع واكتب")}</button>
</div>
<div id="flashcard-section">
<div class="card"><p id="card-counter" style="text-align:center;color:var(--text-muted)">1/{max(len(words),1)}</p>
<div class="flashcard" id="flashcard" onclick="Flashcard.flip()"></div>
<div class="audio-controls" style="justify-content:center">
<button class="btn btn-sm btn-outline" onclick="Flashcard.prev()">←</button>
<button class="btn btn-sm" onclick="Flashcard.hearWord()">🔊</button>
<button class="btn btn-sm btn-outline" onclick="Flashcard.next()">→</button></div></div>
</div>
<div id="quiz-section" style="display:none"></div>
<div class="done-section" data-exercise="vocab"><div id="done-status" class="done-status" style="color:var(--text-secondary);font-size:0.85rem">{bl("Completes automatically when you finish the quiz or review all the cards.", "بيتقفل تلقائيًا لما تخلّص الاختبار أو تراجع كل البطاقات.")}</div><input type="checkbox" class="checkbox" style="display:none" onchange="if(this.checked)Progress.markDone('{level}',{week},{day},'vocab')"><button class="btn btn-sm btn-outline done-fallback" style="margin-top:8px">✔️ {bl("I've finished — mark done", "خلصت — علّم تم")}</button></div>
{swipe_hint()}
<div class="nav page-nav" style="margin-top:20px"><a href="/">🏠 {bl("Home", "الرئيسية")}</a><a href="listening.html">← {bl("Listening", "الاستماع")}</a><a href="speaking.html">{bl("Speaking", "التحدث")} →</a></div></div>
{bottom_nav('vocab')}
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>
<script>const words={safe_json_for_script_tag(words)};document.addEventListener('DOMContentLoaded',()=>{{Flashcard.init(words);InteractiveVocab.init(words)}});</script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


def broadcast_audio_id(level, week, index):
    """Stable clip id for one SEGMENT of a week's extended-listening script.

    Separate from audio_id() because extended listening is WEEKLY, not daily
    (one script per week, played on any day), and because one script is a list
    of speaker turns rather than a single passage -- a news bulletin or a
    two-person scene needs one clip per voice. Hence `{level}-w{week}-bc{i}`
    with no day component: seven days share the week's clips instead of
    generating seven identical copies of the same minute of audio.
    """
    return f"{level}-w{week}-bc{index}"


def gen_broadcast(level, week, day, theme, bc):
    """Phase 11D: EXTENDED LISTENING — the last CEFR gap, and the only one that
    authored text could never close.

    After reading and mediation shipped, five descriptors were still taught by
    no week:

        A2.R.2  main point of short, clear messages and ANNOUNCEMENTS
        B1.R.1  main points of clear standard SPEECH on familiar matters
        B1.R.2  main points of many RADIO or TV programmes
        B2.R.1  extended SPEECH and LECTURES, complex lines of argument
        B2.R.2  most TV NEWS and current-affairs programmes, and FILMS

    The existing listening page is word-level dictation: five words a week,
    typed back. Its unit is smaller than the unit these descriptors are about,
    so no amount of it can evidence them. This page plays roughly a minute of
    connected speech instead.

    THE ONE RULE THAT MAKES IT HONEST: the transcript and the detail questions
    stay LOCKED until the main-point question has been answered. If the
    transcript were on screen from the start, a student could read instead of
    listen, the exercise would be reading with a play button, and it could not
    honestly evidence a listening descriptor. The lock is what the descriptor
    claim rests on, so it is enforced here rather than left as advice.

    Completion is by genuine engagement: the gist question plus every detail
    question must be answered before the exercise auto-completes.
    """
    theme = esc_html(theme)
    if not bc:
        return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Extended Listening Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>🎧 {bl("Extended Listening", "الاستماع الممتد")}</h1><p class="subtitle">Week {week} • Day {day}</p></div>
<div class="card"><p>{bl("The extended listening for this week is not published yet.", "الاستماع الممتد للأسبوع ده لسه مش منشور.")}</p></div>
<div class="nav page-nav" style="margin-top:20px"><a href="/">🏠 {bl("Home", "الرئيسية")}</a><a href="index.html">📋 {bl("Today's menu", "قائمة اليوم")}</a></div></div>
{bottom_nav('broadcast')}
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''

    title = esc_html(bc.get("title", ""))
    title_ar = esc_html(bc.get("title_ar", ""))
    gist_ar = esc_html(bc.get("gist_ar", ""))
    fmt = esc_html((bc.get("format") or "recording").replace("_", " "))
    segments = [s for s in (bc.get("segments") or []) if (s.get("text") or "").strip()]
    word_count = sum(len((s.get("text") or "").split()) for s in segments)
    # ~150 words per minute of clear delivery — an honest estimate, and it sets
    # the student's expectation before they press play.
    approx_sec = max(10, int(round(word_count / 150 * 60)))

    before = bc.get("before_listening") or {}
    before_en = esc_html(before.get("en", ""))
    before_ar = esc_html(before.get("ar", ""))

    # --- the player: speaker labels only, never the words ---
    #
    # AUTHENTIC SCENE AUDIO. B2.R.2 and C1.R.2 name FILMS, and synthesis cannot
    # deliver what an actor does with a line. When a scene has been re-recorded
    # with real voices it arrives as ONE continuous file ({level}-w{week}-scene.mp3)
    # — actors perform a scene, they do not record one clean turn at a time — so
    # the player uses that single file instead of the per-turn TTS clips.
    #
    # Per-turn highlighting is lost with a continuous recording, which is a fair
    # trade: reading tone off a real voice is the whole point of the descriptor.
    # Falls back to the TTS sequence whenever no scene file is present, so this is
    # purely additive and nothing changes until a recording lands.
    scene_file = OUTPUT_DIR / "audio" / f"{level}-w{week}-scene.mp3"
    authentic_scene = scene_file.exists()
    if authentic_scene:
        seq = [{"id": f"{level}-w{week}-scene", "text": ""}]
    else:
        # Each segment carries the per-level playback rate: broadcast is
        # rendered phoneme-safe (af_heart) and slowed at playback to hit the
        # level's CEFR pace target. rate == 1.0 for c1/c2 (no slowing needed).
        _bc_rate = round(split_pace(level, "af_heart")[1], 4)
        seq = [{"id": broadcast_audio_id(level, week, i),
                "text": s.get("text", ""), "rate": _bc_rate}
               for i, s in enumerate(segments)]
    seq_json = safe_json_for_script_tag(seq)
    turn_rows = ""
    if len(segments) > 1:
        for i, s in enumerate(segments):
            spk = esc_html(s.get("speaker") or f"Voice {i+1}")
            spk_ar = esc_html(s.get("speaker_ar") or "")
            turn_rows += (
                f'<div class="bc-turn" data-si="{i}" style="display:flex;align-items:center;'
                f'gap:8px;padding:6px 0;border-bottom:1px solid var(--border)">'
                f'<span class="bc-turn-dot" style="width:8px;height:8px;border-radius:50%;'
                f'background:var(--border);flex:0 0 auto"></span>'
                f'<b style="font-size:0.9rem">{spk}</b>'
                + (f'<span class="arabic-text" lang="ar" dir="rtl" style="font-size:0.85rem">{spk_ar}</span>'
                   if spk_ar else '')
                + f'<button class="btn btn-sm btn-outline" style="margin-inline-start:auto;padding:2px 8px"'
                f' onclick="Broadcast.playFrom({i})">▶️</button></div>')
        turn_rows = (f'<div class="card"><h2>🗣️ {bl("Who speaks", "مين بيتكلم")}</h2>'
                     f'<p style="color:var(--text-secondary);font-size:0.85rem;margin:0 0 8px">'
                     f'{bl("The order of the voices — not the words.", "ترتيب الأصوات — مش الكلام.")}</p>'
                     f'{turn_rows}</div>')

    # --- glossary: shown BEFORE listening on purpose ---
    # Pre-teaching a handful of words is standard listening practice and gives
    # nothing away about the main point, whereas the transcript would.
    glossary = ""
    gitems = [g for g in (bc.get("glossary") or []) if g.get("word")]
    if gitems:
        rows = "".join(
            f'<div style="padding:6px 0;border-bottom:1px solid var(--border)">'
            f'<b>{esc_html(g["word"])}</b>'
            f'<span class="arabic-text" lang="ar" dir="rtl" style="margin-inline-start:10px">{esc_html(g.get("ar",""))}</span>'
            f'</div>' for g in gitems)
        glossary = (f'<div class="card"><h2>📕 {bl("Words to listen for", "كلمات استمع لها")}</h2>'
                    f'{rows}</div>')

    # --- the gist question: the gate ---
    gist = bc.get("gist_question") or {}
    gist_opts = "".join(
        f'<div class="option" data-oi="{oi}" onclick="Broadcast.pickGist({oi})">{esc_html(o)}</div>'
        for oi, o in enumerate(gist.get("options") or []))
    gist_card = (
        f'<div class="card" style="border-left:3px solid var(--accent)">'
        f'<h2>🎯 {bl("The main point", "الفكرة الأساسية")}</h2>'
        f'<p style="color:var(--text-secondary);font-size:0.85rem;margin:0 0 8px">'
        f'{bl("Answer this from listening. The transcript unlocks afterwards.", "جاوب من السمع. النص بيتفتح بعد كده.")}</p>'
        f'<p style="line-height:1.7">{esc_html(gist.get("q",""))}</p>'
        + (f'<p class="arabic-text" lang="ar" dir="rtl" style="margin:6px 0">{esc_html(gist.get("q_ar",""))}</p>'
           if gist.get("q_ar") else '')
        + f'<div class="options" id="bc-gist-options">{gist_opts}</div>'
        f'<div class="q-feedback" id="bc-gist-feedback" style="margin-top:8px"></div></div>')

    # --- detail questions: locked until the gist is answered ---
    questions = [q for q in (bc.get("questions") or [])
                 if q.get("q") and q.get("options")]
    q_html = ""
    for qi, q in enumerate(questions):
        opts = "".join(
            f'<div class="option" data-qi="{qi}" data-oi="{oi}"'
            f' onclick="Broadcast.pick({qi},{oi})">{esc_html(o)}</div>'
            for oi, o in enumerate(q["options"]))
        q_html += (f'<div class="card"><h2>❓ {bl("Question", "سؤال")} {qi+1}</h2>'
                   f'<p style="line-height:1.7">{esc_html(q["q"])}</p>'
                   + (f'<p class="arabic-text" lang="ar" dir="rtl" style="margin:6px 0">{esc_html(q.get("q_ar",""))}</p>'
                      if q.get("q_ar") else '')
                   + f'<div class="options" data-qi="{qi}">{opts}</div>'
                   f'<div class="q-feedback" data-qi="{qi}" style="margin-top:8px"></div></div>')
    details_block = (
        f'<div id="bc-details" class="bc-locked" aria-hidden="true">{q_html}</div>'
        f'<div id="bc-details-lock" class="card">'
        f'<p style="color:var(--text-secondary);margin:0">🔒 '
        f'{bl("Answer the main-point question above to unlock the detail questions.", "جاوب على سؤال الفكرة الأساسية فوق عشان تفتح أسئلة التفاصيل.")}</p></div>'
    ) if questions else ""

    # --- transcript: locked until the gist is answered ---
    transcript_rows = ""
    for s in segments:
        spk = esc_html(s.get("speaker") or "")
        txt = esc_html(s.get("text") or "")
        transcript_rows += (
            f'<div style="margin:10px 0">'
            + (f'<b style="color:var(--accent);font-size:0.85rem">{spk}</b><br>' if spk else '')
            + f'<span style="line-height:1.9">{txt}</span></div>')
    transcript_card = (
        f'<div id="bc-transcript" class="card bc-locked" aria-hidden="true">'
        f'<h2>📄 {bl("Transcript", "النص")}</h2>'
        f'<p style="color:var(--text-secondary);font-size:0.85rem;margin:0 0 8px">'
        f'{bl("Now read while you listen again — check what you missed.", "اقرا وإنت بتسمع تاني — شوف إيه اللي فاتك.")}</p>'
        f'{transcript_rows}</div>'
        f'<div id="bc-transcript-lock" class="card">'
        f'<p style="color:var(--text-secondary);margin:0">🔒 '
        f'{bl("The transcript opens after you answer the main-point question — so the answer comes from your ears, not your eyes.", "النص بيتفتح بعد ما تجاوب على سؤال الفكرة الأساسية — عشان الإجابة تطلع من ودنك، مش من عينك.")}</p></div>')

    answers_json = safe_json_for_script_tag([int(q.get("answer", 0)) for q in questions])
    gist_answer = int(gist.get("answer", 0))
    done_hint = (bl("Completes automatically when you answer the main point and every question.",
                    "بيتقفل تلقائيًا لما تجاوب على الفكرة الأساسية وكل الأسئلة.")
                 if questions else
                 bl("Listen, answer the main point, then mark it done.",
                    "اسمع، جاوب على الفكرة الأساسية، وبعدين علّمه تم."))

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Extended Listening Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}
<style>.bc-locked{{display:none}}.bc-turn.playing .bc-turn-dot{{background:var(--accent)}}</style></head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>🎧 {bl("Extended Listening", "الاستماع الممتد")}</h1><p class="subtitle">Week {week} • Day {day} • {theme}</p></div>
{gamification_bar()}
<div class="card" style="padding:10px 14px"><p style="color:var(--accent);font-weight:600;margin:0">📅 {bl("This week's recording", "تسجيل الأسبوع")} · {fmt} · ~{approx_sec}s</p>
<p style="color:var(--text-secondary);font-size:0.85rem;margin:4px 0 0">{bl("One recording per week — listen again each day and you will need fewer replays.", "تسجيل واحد كل أسبوع — اسمعه كل يوم وهتحتاج تعيده أقل.")}</p></div>
<div class="card"><h2 style="margin:0">{title}</h2>
{f'<p class="arabic-text" lang="ar" dir="rtl" style="margin-top:6px">{title_ar}</p>' if title_ar else ''}</div>
<div class="card" style="border-left:3px solid var(--accent-light)"><h2>👂 {bl("Before you listen", "قبل ما تسمع")}</h2>
<p style="line-height:1.7;margin:0">{before_en}</p>
{f'<p class="arabic-text" lang="ar" dir="rtl" style="margin:8px 0 0">{before_ar}</p>' if before_ar else ''}</div>
{glossary}
<div class="card"><h2>▶️ {bl("Listen", "اسمع")}</h2>
<button class="btn" onclick="Broadcast.playAll()">▶️ {bl("Play", "شغل")}</button>
<button class="btn btn-outline" style="margin-inline-start:8px" onclick="Broadcast.stop()">⏹️ {bl("Stop", "قف")}</button>
<div class="speed-control" style="margin-top:10px"><label>{bl("Speed","السرعة")}:</label>
<select id="bc-speed" onchange="Broadcast.setRate(this.value)">
<option value="0.75">Slow / بطيء</option><option value="0.9">Careful / متمهل</option>
<option value="1.0" selected>Normal / عادي</option></select></div>
<p style="color:var(--text-secondary);font-size:0.85rem;margin:10px 0 0">{bl("Times played", "عدد المرات")}: <b id="bc-plays">0</b></p>
<p style="color:var(--text-muted);font-size:0.8rem;margin:6px 0 0">🎙️ {bl("Studio-quality audio when available, otherwise your browser's voice.", "صوت استوديو لو متوفر، وإلا صوت المتصفح.")}</p></div>
{turn_rows}
{f'<div class="arabic-text" lang="ar" dir="rtl">{gist_ar}</div>' if gist_ar else ''}
{gist_card}
{details_block}
{transcript_card}
<div class="done-section" data-exercise="broadcast"><div id="done-status" class="done-status" style="color:var(--text-secondary);font-size:0.85rem">{done_hint}</div><input type="checkbox" class="checkbox" style="display:none" onchange="if(this.checked)Progress.markDone('{level}',{week},{day},'broadcast')"><button class="btn btn-sm btn-outline done-fallback" style="margin-top:8px">✔️ {bl("I've finished — mark done", "خلصت — علّم تم")}</button></div>
{swipe_hint()}
<div class="nav page-nav" style="margin-top:20px"><a href="/">🏠 {bl("Home", "الرئيسية")}</a><a href="index.html">📋 {bl("Today's menu", "قائمة اليوم")}</a><a href="reading.html">📖 {bl("Reading", "القراءة")} →</a></div></div>
{bottom_nav('broadcast')}
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>
<script>
const bcSegments={seq_json};
const bcGistAnswer={gist_answer};
const bcAnswers={answers_json};
const Broadcast={{
  _plays:0, _rate:1.0, _answered:new Set(), _gistDone:false,
  playAll(){{
    this._plays++;
    const el=document.getElementById('bc-plays');
    if(el) el.textContent=this._plays;
    KokoroAudio.playSequence(bcSegments,{{
      rate:this._rate,
      onSegment:(i)=>{{
        document.querySelectorAll('.bc-turn').forEach(t=>t.classList.remove('playing'));
        const row=document.querySelector('.bc-turn[data-si="'+i+'"]');
        if(row) row.classList.add('playing');
      }},
      onEnd:()=>{{ document.querySelectorAll('.bc-turn').forEach(t=>t.classList.remove('playing')); }}
    }});
  }},
  playFrom(i){{
    KokoroAudio.playSequence(bcSegments.slice(i),{{rate:this._rate}});
  }},
  stop(){{ KokoroAudio.stop(); document.querySelectorAll('.bc-turn').forEach(t=>t.classList.remove('playing')); }},
  setRate(r){{ this._rate=parseFloat(r); KokoroAudio.setRate(r); }},
  pickGist(oi){{
    const box=document.getElementById('bc-gist-options');
    const fb=document.getElementById('bc-gist-feedback');
    if(!box||box.dataset.answered) return;
    box.dataset.answered='1';
    box.querySelectorAll('.option').forEach(el=>{{
      const o=parseInt(el.dataset.oi,10);
      if(o===bcGistAnswer) el.classList.add('correct');
      else if(o===oi) el.classList.add('wrong');
    }});
    if(fb) fb.innerHTML = (oi===bcGistAnswer)
      ? '<span style="color:var(--success)">✅ Correct — صح</span>'
      : '<span style="color:var(--text-secondary)">The highlighted answer is the main point. Listen once more with the transcript.</span>';
    this._gistDone=true;
    this.unlock();
    this.check();
  }},
  unlock(){{
    ['bc-details','bc-transcript'].forEach(id=>{{
      const el=document.getElementById(id);
      if(el){{ el.classList.remove('bc-locked'); el.setAttribute('aria-hidden','false'); }}
    }});
    ['bc-details-lock','bc-transcript-lock'].forEach(id=>{{
      const el=document.getElementById(id);
      if(el) el.remove();
    }});
  }},
  pick(qi,oi){{
    if(!this._gistDone) return;
    const box=document.querySelector('#bc-details .options[data-qi="'+qi+'"]');
    const fb=document.querySelector('#bc-details .q-feedback[data-qi="'+qi+'"]');
    if(!box||box.dataset.answered) return;
    box.dataset.answered='1';
    const correct=bcAnswers[qi];
    box.querySelectorAll('.option').forEach(el=>{{
      const o=parseInt(el.dataset.oi,10);
      if(o===correct) el.classList.add('correct');
      else if(o===oi) el.classList.add('wrong');
    }});
    if(fb) fb.innerHTML = (oi===correct)
      ? '<span style="color:var(--success)">✅ Correct — صح</span>'
      : '<span style="color:var(--text-secondary)">Check the transcript for this one.</span>';
    this._answered.add(qi);
    this.check();
  }},
  check(){{
    if(!this._gistDone) return;
    if(this._answered.size<bcAnswers.length) return;
    const cb=document.querySelector('.done-section .checkbox');
    if(cb&&!cb.checked){{ cb.checked=true; cb.dispatchEvent(new Event('change')); }}
  }}
}};
</script>
{content_gate_js()}{copyright_footer()}</div></body></html>'''


def gen_day_index(level, week, day, grammar=None, can_do=None, reading=None,
                  mediation=None, broadcast=None):
    """The day's menu.

    Phase 11A-4 fixed TWO holes here:

    1. The "Today's Pattern" card was fed from content/patterns/{level}_patterns.json,
       which only ever existed for the retired legacy levels (l0-l3). For every
       CEFR level the loader returned [], so `pattern` was always None and the
       card rendered NOTHING -- verified: the generated a1/week1/day1/index.html
       contained zero occurrences of "Today's Pattern". It is now fed from the
       week's real authored grammar pattern, which is the actual pattern of the
       week, and links to the grammar exercise instead of dead-ending.
    2. The week's CEFR can-do goals were never shown while studying (only on the
       Phase-9 progress screen and the certificate, i.e. after the fact), so
       students could not see WHY the day's tasks exist.
    """
    # --- This week's pattern (from the authored grammar, not the dead
    #     legacy patterns file) ---
    pattern_card = ""
    if grammar:
        name = esc_html(grammar.get("pattern_name", ""))
        name_ar = esc_html(grammar.get("pattern_name_ar", ""))
        formula = esc_html(grammar.get("formula", ""))
        when = esc_html(grammar.get("when_to_use", ""))
        examples = [e for e in (grammar.get("examples") or []) if e.get("en")]
        example = esc_html(examples[0]["en"]) if examples else ""
        # Speak the EXAMPLE sentence, not the formula: "Subject + am / is /
        # are + (complement)" is not something a student should hear read out.
        speak_src = esc(examples[0]["en"]) if examples else esc(grammar.get("pattern_name", ""))
        pattern_card = (
            f'<div class="card" style="border-left:3px solid var(--accent)">'
            f'<h2>💬 {bl("This Week\'s Pattern", "نمط الأسبوع")}</h2>'
            f'<div class="transcript" style="font-size:1.2rem;line-height:1.6"><b>{name}</b></div>'
            + (f'<p class="arabic-text" lang="ar" dir="rtl" style="margin:6px 0">{name_ar}</p>' if name_ar else '')
            + (f'<p style="color:var(--accent-light);margin:8px 0;font-family:monospace">{formula}</p>' if formula else '')
            + (f'<p style="color:var(--text-secondary);margin:8px 0">📍 {when}</p>' if when else '')
            + (f'<p style="color:var(--text-secondary);font-size:0.85rem;margin:12px 0;font-style:italic">💡 "{example}"</p>' if example else '')
            + (f'<button class="btn btn-sm" onclick="TTS.speak(\'{speak_src}\', 0.7)">🔊 {bl("Listen", "استمع")}</button>' if speak_src else '')
            + f'<a class="btn btn-sm btn-outline" style="margin-inline-start:8px" href="grammar.html">📐 {bl("Practise it", "اتمرن عليه")}</a>'
            f'</div>'
        )

    # Reading is listed ONLY when the week actually has an authored passage.
    # Phase 11B rolls out level by level behind the owner approval gate, so
    # linking it unconditionally would send students of not-yet-authored
    # levels to a "coming soon" dead end.
    reading_link = ""
    if reading:
        reading_link = (
            f'<a href="reading.html">📖 Reading — القراءة '
            f'<span style="color:var(--text-muted);font-size:0.8rem">'
            f'({bl("weekly", "أسبوعي")})</span></a>'
        )

    # Mediation, like reading, is listed ONLY where it is authored.
    mediation_link = ""
    if mediation:
        mediation_link = (
            f'<a href="mediation.html">🤝 Mediation — الوساطة '
            f'<span style="color:var(--text-muted);font-size:0.8rem">'
            f'({bl("weekly", "أسبوعي")})</span></a>'
        )

    # Extended listening (Phase 11D) — same rule again: listed only where a
    # script is authored, so a level still awaiting content never links to a
    # "coming soon" dead end.
    broadcast_link = ""
    if broadcast:
        broadcast_link = (
            f'<a href="broadcast.html">🎧 Extended Listening — الاستماع الممتد '
            f'<span style="color:var(--text-muted);font-size:0.8rem">'
            f'({bl("weekly", "أسبوعي")})</span></a>'
        )

    # --- This week's CEFR goals (the "I can ..." statements) ---
    can_do_card = ""
    if can_do:
        rows = ""
        for g in can_do:
            en = esc_html(g.get("en", ""))
            ar = esc_html(g.get("ar", ""))
            rows += ('<li style="margin:8px 0">'
                     + (f'<span class="arabic-text" lang="ar" dir="rtl">{ar}</span>' if ar else '')
                     + (f'<br><span style="color:var(--text-secondary);font-size:0.9rem">{en}</span>' if en else '')
                     + '</li>')
        can_do_card = (
            f'<div class="card"><h2>🎯 {bl("This week you will be able to", "بعد الأسبوع ده تقدر")}</h2>'
            f'<ul style="padding-inline-start:18px;margin:8px 0">{rows}</ul>'
            f'<p style="color:var(--text-muted);font-size:0.8rem;margin:8px 0 0">'
            f'{bl("CEFR-aligned goals for this week.", "أهداف الأسبوع حسب معيار CEFR.")}</p></div>'
        )

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Week {week} Day {day} | Empire English</title>
{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header">
<img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px">
<h1>Week {week} — Day {day}</h1><p class="subtitle">{bl("Choose your exercise", "اختار التمرين")}</p></div>
<div class="arabic-text" lang="ar" dir="rtl">اختار التمرين اللي عايز تعمله</div>
{can_do_card}
{pattern_card}
<div class="card"><h2>📋 {bl("Today's Exercises", "تمارين اليوم")}</h2>
<div class="nav" style="flex-direction:column;align-items:stretch">
<a href="accent.html">🎯 Accent Drill — تدريب النطق</a>
<a href="shadowing.html">🎧 Shadowing — المحاكاة</a>
<a href="listening.html">👂 Listening — الاستماع</a>
<a href="vocab.html">📖 Vocabulary — المفردات</a>
<a href="speaking.html">🎙️ Speaking — التحدث</a>
<a href="grammar.html">📐 Grammar — القواعد <span style="color:var(--text-muted);font-size:0.8rem">({bl("weekly", "أسبوعي")})</span></a>
{broadcast_link}
{reading_link}
{mediation_link}
<a href="review.html">🧠 Review — مراجعة <span style="color:var(--text-muted);font-size:0.8rem">({bl("weekly", "أسبوعي")})</span></a>
</div></div>
<div class="nav" style="margin-top:20px"><a href="/index.html">← {bl("Home", "الرئيسية")}</a></div>
<div class="footer">Empire English Community — Common Sense First 🏛️</div>
</div>
<script src="/js/speech-id.js"></script><script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


# ============================================================
#  GENERATE
# ============================================================

def load_week_mediation_data(level, week):
    """The week's authored mediation task, or None when not authored yet."""
    med_dir = CONTENT_DIR / level / "mediation"
    if not med_dir.exists():
        return None
    matches = (sorted(med_dir.glob(f"week{week}_*.json"))
               + sorted(med_dir.glob(f"week{week}.json")))
    if not matches:
        return None
    with open(matches[0], encoding="utf-8") as f:
        return json.load(f)


def load_week_reading_data(level, week):
    """The week's authored reading passage (content/{level}/reading/weekN_*.json).

    Returns None when the level/week has no authored passage -- Phase 11B is
    rolled out level by level behind the owner approval gate, so "not authored
    yet" is a normal state and must render an honest empty page.
    """
    reading_dir = CONTENT_DIR / level / "reading"
    if not reading_dir.exists():
        return None
    matches = (sorted(reading_dir.glob(f"week{week}_*.json"))
               + sorted(reading_dir.glob(f"week{week}.json")))
    if not matches:
        return None
    with open(matches[0], encoding="utf-8") as f:
        return json.load(f)


def load_week_broadcast_data(level, week):
    """The week's authored extended-listening script
    (content/{level}/broadcast/weekN_*.json).

    Returns None when the level/week has no authored script -- Phase 11D is
    rolled out level by level behind the owner approval gate, exactly like
    reading and mediation, so "not authored yet" is a normal state that must
    render an honest empty page.
    """
    bc_dir = CONTENT_DIR / level / "broadcast"
    if not bc_dir.exists():
        return None
    matches = (sorted(bc_dir.glob(f"week{week}_*.json"))
               + sorted(bc_dir.glob(f"week{week}.json")))
    if not matches:
        return None
    with open(matches[0], encoding="utf-8") as f:
        return json.load(f)


def load_week_grammar_data(level, week):
    """The week's authored grammar pattern (content/{level}/grammar/weekN_*.json).
    Same lookup shape as load_week_accent_data. Returns None when the week has
    no authored pattern -- callers must render an honest empty state, never a
    fabricated pattern."""
    grammar_dir = CONTENT_DIR / level / "grammar"
    if not grammar_dir.exists():
        return None
    # "week1_*.json" cannot match "week10_*.json" (the underscore is
    # required immediately after the number), so week 1 never picks up
    # week 10's file -- same guarantee the accent loader relies on.
    matches = (sorted(grammar_dir.glob(f"week{week}_*.json"))
               + sorted(grammar_dir.glob(f"week{week}.json")))
    if not matches:
        return None
    with open(matches[0], encoding="utf-8") as f:
        return json.load(f)


def load_week_accent_data(level, week):
    accent_dir = CONTENT_DIR / level / "accent"
    matches = sorted(accent_dir.glob(f"week{week}_*.json")) + sorted(accent_dir.glob(f"week{week}.json"))
    if not matches:
        return None
    with open(matches[0], encoding="utf-8") as f:
        return json.load(f)


_CAN_DO_CACHE = {}


def load_can_do_library(level):
    """{code: {code, en, ar, mode}} for a level from content/cefr/can_do.json.

    Mirrors nexus curriculum.can_do_descriptor_map(). Note the per-level dict
    mixes list-valued modes (reception/production/interaction/mediation) with
    plain string keys (overview_en/overview_ar), so values MUST be
    isinstance-checked. Returns {} on any failure -- a missing library means
    "no goals card", never a broken build.
    """
    key = level.upper()
    if key in _CAN_DO_CACHE:
        return _CAN_DO_CACHE[key]
    out = {}
    path = CONTENT_DIR / "cefr" / "can_do.json"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for mode, items in (data.get(key) or {}).items():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and item.get("code"):
                    out[item["code"]] = {
                        "code": item["code"], "en": item.get("en", ""),
                        "ar": item.get("ar", ""), "mode": mode,
                    }
    except Exception as e:
        print(f"  ⚠️  can_do library for {level} unavailable: {e}")
        out = {}
    _CAN_DO_CACHE[key] = out
    return out


def generate_level(level, audio_manifest):
    max_week = ALL_WEEK_COUNTS[level]
    total = 0
    # The week's CEFR can-do goals are resolved from the shared descriptor
    # library once per level. (The old content/patterns/*.json "pattern"
    # source was removed in Phase 11A-4: it existed only for the retired
    # legacy levels, so the day index's pattern card always rendered
    # nothing. The card now comes from the week's authored grammar.)
    can_do_library = load_can_do_library(level)

    # Preloaded for the weekly REVIEW quiz (Phase 11C): retrieval practice
    # needs EARLIER weeks' content, not just the current week's, so the whole
    # level's vocabulary and grammar must be in hand before the loop.
    weeks_vocab, weeks_grammar = {}, {}
    for w in range(1, max_week + 1):
        wf = DATA_DIR / f"{level}_week{w}.json"
        if wf.exists():
            with open(wf, encoding="utf-8") as f:
                weeks_vocab[w] = (json.load(f) or {}).get("vocabulary", []) or []
        g = load_week_grammar_data(level, w)
        if g:
            weeks_grammar[w] = g

    for week in range(1, max_week + 1):
        week_file = DATA_DIR / f"{level}_week{week}.json"
        if not week_file.exists():
            print(f"  [{level}] Skip week {week} (no data)")
            continue
        with open(week_file, encoding="utf-8") as f:
            week_data = json.load(f)

        accent_data = load_week_accent_data(level, week)
        grammar_data = load_week_grammar_data(level, week)
        reading_data = load_week_reading_data(level, week)
        mediation_data = load_week_mediation_data(level, week)
        broadcast_data = load_week_broadcast_data(level, week)
        focus = accent_data.get("focus", "Review") if accent_data else "Review"
        theme = week_data.get("theme", "General")
        vocab = week_data.get("vocabulary", [])
        # Authored listening/dictation targets for the week (5 per week).
        # Must mirror nexus curriculum.get_listening_for_day(): every day
        # surfaces the FULL set, rotated by day for variety, because 5 items
        # cannot be split across 7 days without leaving days empty and
        # making coverage depend on which days a student happens to do.
        week_listening = week_data.get("listening") or []
        # Resolve the week's can-do CODES ("A1.P.1") into the real bilingual
        # "I can ..." descriptors. Unknown codes are skipped rather than
        # shown raw -- a code means nothing to a student.
        week_can_do = [can_do_library[c] for c in (week_data.get("can_do") or [])
                       if c in can_do_library]
        review_items = build_review_items(level, week, weeks_vocab, weeks_grammar)

        drills_by_day = {}
        if accent_data:
            for d in accent_data.get("daily_drills", []):
                if isinstance(d, dict) and "day" in d:
                    drills_by_day[d["day"]] = d

        for day in range(1, 8):
            day_dir = OUTPUT_DIR / level / f"week{week}" / f"day{day}"
            day_dir.mkdir(parents=True, exist_ok=True)

            # Split weekly vocab into 7 days using the SAME formula as the
            # bot's curriculum.py get_vocabulary_for_day(). This MUST stay
            # byte-for-byte equivalent: nexus `database.record_vocab_quiz`
            # and `verification.py` both assume the bot and this site agree
            # word-for-word on what a given day teaches.
            #
            # History, so neither copy regresses again:
            #  1. Originally a hardcoded "8 words/day" slice that fell back
            #     to vocab[:8] (day 1's words, verbatim) for any week with
            #     fewer than day*8 words -- silently re-showing day 1's
            #     vocabulary on day 6/7 for every week under 56 words.
            #  2. Then `max(1, len(vocab) // 7)`, which fixed the repeat but
            #     truncated on integer division and never assigned the
            #     remainder to any day -- so the last `len % 7` words of
            #     EVERY week were unreachable. Measured across the 90
            #     authored weeks: 354 of 2,909 words (12.2%) never rendered
            #     on any page; 88 of 90 weeks affected; worst week lost 6.
            #  3. Now: distribute the remainder. The first `len % 7` days
            #     get one extra word, so the 7 slices reconstruct the week's
            #     list exactly (contiguous, in authored order, zero loss).
            base, remainder = divmod(len(vocab), 7)
            if base == 0:
                # Fewer than 7 words: cycle so no day is empty, and every
                # word still appears across the week.
                day_vocab = [vocab[(day - 1) % len(vocab)]] if vocab else []
            else:
                _start = (day - 1) * base + min(day - 1, remainder)
                _size = base + (1 if (day - 1) < remainder else 0)
                day_vocab = vocab[_start:_start + _size]

            if week_listening:
                _off = ((day - 1) % 7) % len(week_listening)
                day_listening = week_listening[_off:] + week_listening[:_off]
            else:
                day_listening = []
            norm = normalize_drill(drills_by_day.get(day))
            shadow_aid = audio_id(level, week, day, "shadow")

            with open(day_dir / "index.html", "w", encoding="utf-8") as f:
                f.write(gen_day_index(level, week, day,
                                      grammar=grammar_data,
                                      can_do=week_can_do,
                                      reading=reading_data,
                                      mediation=mediation_data,
                                      broadcast=broadcast_data))
            with open(day_dir / "accent.html", "w", encoding="utf-8") as f:
                f.write(gen_accent(level, week, day, focus, norm,
                                   phoneme_focus=week_data.get("phoneme_focus")))
            with open(day_dir / "shadowing.html", "w", encoding="utf-8") as f:
                f.write(gen_shadowing(level, week, day, theme, norm, shadow_aid))
            with open(day_dir / "listening.html", "w", encoding="utf-8") as f:
                f.write(gen_listening(level, week, day, theme, day_vocab, vocab,
                                      day_listening=day_listening))

            with open(day_dir / "review.html", "w", encoding="utf-8") as f:
                f.write(gen_review(level, week, day, theme, review_items))

            with open(day_dir / "mediation.html", "w", encoding="utf-8") as f:
                f.write(gen_mediation(level, week, day, theme, mediation_data))

            with open(day_dir / "reading.html", "w", encoding="utf-8") as f:
                f.write(gen_reading(level, week, day, theme, reading_data))

            with open(day_dir / "broadcast.html", "w", encoding="utf-8") as f:
                f.write(gen_broadcast(level, week, day, theme, broadcast_data))

            with open(day_dir / "grammar.html", "w", encoding="utf-8") as f:
                f.write(gen_grammar(level, week, day, theme, grammar_data,
                                    grammar_point=week_data.get("grammar_point")))
            with open(day_dir / "vocab.html", "w", encoding="utf-8") as f:
                f.write(gen_vocab(level, week, day, theme, day_vocab))
            # E1: Speaking page. Speaking missions are keyed by day-name in
            # the weekly JSON (Sat..Fri = day 1..7), same mapping the bot uses.
            _day_names = ["Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
            _mission = (week_data.get("speaking_missions", {}) or {}).get(_day_names[day - 1])
            with open(day_dir / "speaking.html", "w", encoding="utf-8") as f:
                f.write(gen_speaking(level, week, day, theme, _mission))

            audio_manifest[shadow_aid] = {
                "level": level, "week": week, "day": day,
                "text": norm["primary_text"],
            }
            # index + accent, shadowing, listening, vocab, speaking, grammar,
            # reading, mediation, review, broadcast
            pages_per_day = 11
            total += pages_per_day

        # --- extended-listening clips (Phase 11D) ---
        # Registered ONCE PER WEEK, outside the day loop: the script is weekly,
        # so the seven days share the same clips rather than rendering seven
        # identical copies of the same minute of audio (which would have added
        # ~630 needless MP3s and minutes of Kokoro time per level).
        #
        # Each speaker turn is its own clip AND carries its own `voice`, which
        # is what makes a two-person scene or a news bulletin with a
        # correspondent possible -- one voice reading every part cannot teach
        # "the majority of films in standard dialect".
        for _i, _seg in enumerate(
                [s for s in ((broadcast_data or {}).get("segments") or [])
                 if (s.get("text") or "").strip()]):
            # OWNER DECISION 2026-09-02: af_heart is the single brand voice for
            # EVERYTHING, so broadcast ignores the content file's per-segment
            # `voice` and always uses af_heart. The `speaker` label is kept as
            # on-screen metadata (the transcript still shows who is speaking),
            # but one voice narrates every turn. See voice_cast.json's
            # _brand_voice_decision_2026_09_02.
            _bc_voice = "af_heart"
            # Pace is split into a phoneme-safe render speed and a playback rate
            # (af_heart at 212 wpm corrupts below ~0.90, so low levels are
            # slowed at playback instead of synthesis). Emit the rate so the
            # player delivers each level at its CEFR target; omit when 1.0.
            _render_speed, _playback = split_pace(level, _bc_voice)
            _entry = {
                "level": level, "week": week, "day": 0,
                "kind": "broadcast",
                "voice": _bc_voice,
                "speaker": _seg.get("speaker") or "",
                "text": " ".join((_seg.get("text") or "").split()),
            }
            if round(_playback, 4) != 1.0:
                _entry["playback_rate"] = round(_playback, 4)
            audio_manifest[broadcast_audio_id(level, week, _i)] = _entry

        print(f"  [{level}] Week {week}: {pages_per_day * 7} pages ✅")

    return total


def review_items(level):
    """Every authored reading / mediation / extended-listening item for a level.

    Lives in generate.py rather than a separate script on purpose: the review
    surface must show exactly what the BUILD sees, so that approving an item and
    shipping it cannot diverge. A second loader would eventually drift.
    """
    items = []
    for week in range(1, ALL_WEEK_COUNTS[level] + 1):
        r = load_week_reading_data(level, week)
        if r and (r.get("text") or "").strip():
            items.append({"kind": "reading", "week": week, "data": r})
        m = load_week_mediation_data(level, week)
        if m and m.get("source") and (m.get("key_points") or []):
            items.append({"kind": "mediation", "week": week, "data": m})
        b = load_week_broadcast_data(level, week)
        if b and [s for s in (b.get("segments") or []) if (s.get("text") or "").strip()]:
            items.append({"kind": "broadcast", "week": week, "data": b})
    return items


KIND_LABEL = {
    "reading": ("📖", "Reading"),
    "mediation": ("🤝", "Mediation"),
    "broadcast": ("🎧", "Extended Listening"),
}


def _rv_questions(qs, label="Question"):
    """Render comprehension questions with the CORRECT option marked.

    Marking the answer is the point — the reviewer is checking whether the
    intended answer is genuinely the only defensible one, which they cannot do
    if they have to guess which it is.
    """
    out = ""
    for qi, q in enumerate(qs or []):
        opts = ""
        for oi, o in enumerate(q.get("options") or []):
            correct = (oi == q.get("answer"))
            mark = "✅ " if correct else "&nbsp;&nbsp;&nbsp;"
            style = ("background:rgba(46,204,113,0.12);border-color:var(--success)"
                     if correct else "")
            opts += (f'<div style="padding:5px 9px;margin:3px 0;border:1px solid '
                     f'var(--border);border-radius:7px;{style}">{mark}{esc_html(o)}</div>')
        out += (f'<div style="margin:10px 0"><b style="font-size:0.9rem">{label} {qi+1}.</b> '
                f'{esc_html(q.get("q",""))}'
                + (f'<div class="arabic-text" lang="ar" dir="rtl" style="font-size:0.85rem;'
                   f'margin:3px 0">{esc_html(q.get("q_ar",""))}</div>'
                   if q.get("q_ar") else "")
                + f'{opts}</div>')
    return out


def _rv_glossary(gl):
    if not gl:
        return ""
    rows = " · ".join(f'<b>{esc_html(g.get("word",""))}</b> '
                      f'<span class="arabic-text" lang="ar" dir="rtl">{esc_html(g.get("ar",""))}</span>'
                      for g in gl if g.get("word"))
    return (f'<p style="font-size:0.85rem;color:var(--text-secondary);margin:8px 0">'
            f'📕 {rows}</p>')


def _rv_body(level, item):
    """The reviewable content of one item, rendered in full."""
    kind, d, week = item["kind"], item["data"], item["week"]
    out = ""

    if kind == "reading":
        wc = len(str(d.get("text", "")).split())
        out += (f'<p style="color:var(--text-muted);font-size:0.8rem;margin:0 0 6px">'
                f'{wc} words</p>')
        for para in str(d.get("text", "")).split("\n\n"):
            if para.strip():
                out += (f'<p style="line-height:1.85;margin:8px 0">'
                        f'{esc_html(" ".join(para.split()))}</p>')
        out += _rv_glossary(d.get("glossary"))
        out += _rv_questions(d.get("questions"))

    elif kind == "mediation":
        sc = d.get("scenario") or {}
        tk = d.get("task") or {}
        ma = d.get("model_answer") or {}
        out += (f'<p style="margin:6px 0"><b>Scenario:</b> {esc_html(sc.get("en",""))}</p>'
                f'<div class="arabic-text" lang="ar" dir="rtl" style="font-size:0.85rem">'
                f'{esc_html(sc.get("ar",""))}</div>')
        out += (f'<div style="border-inline-start:3px solid var(--accent);padding:8px 12px;'
                f'margin:10px 0;background:rgba(212,175,55,0.05)"><b>Source the student is '
                f'given:</b><br>{esc_html(d.get("source",""))}</div>')
        out += f'<p style="margin:6px 0"><b>Task:</b> {esc_html(tk.get("en",""))}</p>'
        kp = "".join(f'<li>{esc_html(p.get("en",""))}</li>'
                     for p in (d.get("key_points") or []))
        out += (f'<p style="margin:8px 0 2px"><b>Must get across ({len(d.get("key_points") or [])}):</b></p>'
                f'<ul style="margin:2px 0;padding-inline-start:20px;font-size:0.92rem">{kp}</ul>')
        out += (f'<p style="margin:8px 0"><b>Model answer:</b> '
                f'<i>{esc_html(ma.get("en",""))}</i></p>')
        sp = " · ".join(esc_html(s.get("en", "")) for s in (d.get("signal_phrases") or []))
        if sp:
            out += (f'<p style="font-size:0.85rem;color:var(--text-secondary)">'
                    f'💬 If you do not understand: {sp}</p>')

    elif kind == "broadcast":
        segs = [s for s in (d.get("segments") or []) if (s.get("text") or "").strip()]
        wc = sum(len(s["text"].split()) for s in segs)
        out += (f'<p style="color:var(--text-muted);font-size:0.8rem;margin:0 0 6px">'
                f'{esc_html((d.get("format") or "recording").replace("_", " "))} · '
                f'{wc} words · {len(segs)} '
                f'{"turns" if len(segs) > 1 else "turn"}</p>')
        bl_ = d.get("before_listening") or {}
        if bl_.get("en"):
            out += (f'<p style="margin:6px 0"><b>Before you listen:</b> '
                    f'{esc_html(bl_["en"])}</p>')
        for i, s in enumerate(segs):
            aid = broadcast_audio_id(level, week, i)
            out += (f'<div style="margin:8px 0;padding:8px 10px;border:1px solid var(--border);'
                    f'border-radius:8px">'
                    f'<b style="color:var(--accent);font-size:0.85rem">'
                    f'{esc_html(s.get("speaker") or f"Voice {i+1}")}</b>'
                    f'<span style="color:var(--text-muted);font-size:0.78rem;'
                    f'margin-inline-start:8px">{esc_html(s.get("voice",""))}</span>'
                    f'<audio controls preload="none" src="/audio/{aid}.mp3" '
                    f'style="width:100%;margin:6px 0;height:34px"></audio>'
                    f'<div style="line-height:1.8;font-size:0.95rem">'
                    f'{esc_html(" ".join(s["text"].split()))}</div></div>')
        out += _rv_glossary(d.get("glossary"))
        gq = d.get("gist_question") or {}
        if gq.get("q"):
            out += ('<p style="margin:10px 0 0"><b>Main-point question</b> '
                    '<span style="color:var(--text-muted);font-size:0.8rem">'
                    '(asked before the transcript unlocks)</span></p>')
            out += _rv_questions([gq], label="Gist")
        out += _rv_questions(d.get("questions"), label="Detail")

    return out


def gen_content_review(level, items):
    """Owner sign-off surface for one level's authored content.

    Why this exists: signing off 174 authored items meant opening 174 JSON files,
    which is why it had not happened. Ticking the checkboxes without reading them
    would have destroyed the only artefact that distinguishes "a human with
    authority read this" from "a machine generated it" — the same class of
    unearned claim the coverage work exists to remove. So the fix is to make the
    review cheap, not to skip it.

    Decisions are kept in localStorage and exported as markdown for the
    ALIGNMENT docs. No new API, no new table, nothing that can break a student
    path: this page is inert with respect to the rest of the system.
    """
    lv = level.upper()
    counts = {k: sum(1 for i in items if i["kind"] == k)
              for k in ("reading", "mediation", "broadcast")}
    cards = ""
    for item in items:
        d, kind, week = item["data"], item["kind"], item["week"]
        icon, label = KIND_LABEL[kind]
        rid = f"{kind}:{level}:{week}"
        codes = " ".join(f'<span style="background:rgba(212,175,55,0.15);color:var(--accent);'
                         f'padding:1px 7px;border-radius:9px;font-size:0.75rem;'
                         f'margin-inline-end:4px">{esc_html(c)}</span>'
                         for c in (d.get("can_do") or []))
        cards += f'''<div class="card rv-item" data-rid="{rid}" data-kind="{kind}">
<div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap">
<span style="font-size:1.1rem">{icon}</span>
<b style="color:var(--accent-light)">Week {week}</b>
<span style="color:var(--text-muted);font-size:0.8rem">{label}</span>
<span class="rv-state" style="margin-inline-start:auto;font-size:0.8rem"></span></div>
<h3 style="margin:6px 0 2px;font-size:1.05rem">{esc_html(d.get("title",""))}</h3>
<div class="arabic-text" lang="ar" dir="rtl" style="font-size:0.9rem">{esc_html(d.get("title_ar",""))}</div>
<div style="margin:6px 0">{codes}</div>
{_rv_body(level, item)}
<div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border)">
<button class="btn btn-sm rv-ok" type="button">✅ Approve</button>
<button class="btn btn-sm btn-outline rv-flag" type="button" style="margin-inline-start:8px">⚠️ Needs change</button>
<textarea class="rv-note" rows="2" placeholder="What should change? (only needed if flagged)"
 style="width:100%;margin-top:8px;padding:8px;border-radius:8px;border:1px solid var(--border);
 background:var(--bg-primary);color:var(--text-primary);font-family:inherit;font-size:0.9rem"></textarea>
</div></div>'''

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0"><meta name="robots" content="noindex,nofollow">
<link rel="icon" type="image/png" href="/favicon.png">
<title>{lv} content review | Empire English</title>
<link rel="stylesheet" href="/css/empire.css"></head><body>
<div class="container">
<div class="header"><h1 style="font-size:1.4rem">{lv} — content review</h1>
<p class="subtitle">{counts["reading"]} reading · {counts["mediation"]} mediation · {counts["broadcast"]} extended listening</p></div>

<div class="card" style="padding:12px 14px">
<p style="margin:0 0 6px"><b id="rv-progress">0 of {len(items)} reviewed</b></p>
<div style="height:7px;background:var(--border);border-radius:4px;overflow:hidden">
<div id="rv-bar" style="height:100%;width:0;background:var(--accent);transition:width .2s"></div></div>
<p style="color:var(--text-secondary);font-size:0.84rem;margin:8px 0 0">
Judgements only you can make: is this right for <b>your</b> students, at this level?
The correct answer is marked on every question so you can check it is the only defensible one.
Decisions save on this device as you go.</p>
<div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">
<button class="btn btn-sm btn-outline rv-filter" data-f="all" type="button">All</button>
<button class="btn btn-sm btn-outline rv-filter" data-f="todo" type="button">Not yet reviewed</button>
<button class="btn btn-sm btn-outline rv-filter" data-f="flag" type="button">Flagged</button>
<button class="btn btn-sm btn-outline rv-filter" data-f="reading" type="button">📖 Reading</button>
<button class="btn btn-sm btn-outline rv-filter" data-f="mediation" type="button">🤝 Mediation</button>
<button class="btn btn-sm btn-outline rv-filter" data-f="broadcast" type="button">🎧 Listening</button>
</div></div>

<div id="rv-list">{cards}</div>

<div class="card"><h2 style="font-size:1rem">Send me your decisions</h2>
<p style="color:var(--text-secondary);font-size:0.85rem">Press this when you have finished (or part-finished).
Copy the text and send it to me — I will apply the approvals to the ALIGNMENT docs and fix everything you flagged.</p>
<button class="btn" id="rv-export" type="button">📋 Build my decisions</button>
<textarea id="rv-out" rows="10" readonly style="width:100%;margin-top:10px;display:none;
padding:10px;border-radius:8px;border:1px solid var(--border);background:var(--bg-primary);
color:var(--text-primary);font-family:monospace;font-size:0.8rem"></textarea></div>

<div class="nav page-nav" style="margin-top:16px"><a href="/content-review/">← All levels</a></div>
<div class="footer">Empire English Community — owner review surface</div>
</div>
<script>
(function(){{
  var KEY='eec-review-v1';
  var store={{}};
  try{{ store=JSON.parse(localStorage.getItem(KEY)||'{{}}'); }}catch(e){{ store={{}}; }}
  function save(){{ try{{ localStorage.setItem(KEY,JSON.stringify(store)); }}catch(e){{}} }}
  var items=[].slice.call(document.querySelectorAll('.rv-item'));

  function paint(el){{
    var rid=el.dataset.rid, rec=store[rid], s=el.querySelector('.rv-state');
    var note=el.querySelector('.rv-note');
    el.style.borderInlineStart='3px solid transparent';
    if(!rec){{ s.textContent=''; return; }}
    if(rec.v==='ok'){{ s.textContent='✅ approved'; s.style.color='var(--success)';
      el.style.borderInlineStart='3px solid var(--success)'; }}
    else {{ s.textContent='⚠️ needs change'; s.style.color='var(--accent)';
      el.style.borderInlineStart='3px solid var(--accent)'; }}
    if(rec.n && note.value!==rec.n) note.value=rec.n;
  }}
  function progress(){{
    var n=items.filter(function(el){{ return store[el.dataset.rid]; }}).length;
    document.getElementById('rv-progress').textContent=n+' of '+items.length+' reviewed';
    document.getElementById('rv-bar').style.width=(items.length?100*n/items.length:0)+'%';
  }}
  document.getElementById('rv-list').addEventListener('click',function(ev){{
    var b=ev.target.closest('button'); if(!b) return;
    var el=ev.target.closest('.rv-item'); if(!el) return;
    var rid=el.dataset.rid;
    if(b.classList.contains('rv-ok')) store[rid]={{v:'ok',n:''}};
    else if(b.classList.contains('rv-flag')) store[rid]={{v:'flag',n:el.querySelector('.rv-note').value}};
    else return;
    save(); paint(el); progress();
  }});
  document.getElementById('rv-list').addEventListener('input',function(ev){{
    if(!ev.target.classList.contains('rv-note')) return;
    var el=ev.target.closest('.rv-item'), rid=el.dataset.rid;
    if(store[rid]){{ store[rid].n=ev.target.value; save(); }}
  }});
  [].slice.call(document.querySelectorAll('.rv-filter')).forEach(function(btn){{
    btn.addEventListener('click',function(){{
      var f=btn.dataset.f;
      items.forEach(function(el){{
        var rec=store[el.dataset.rid], show=true;
        if(f==='todo') show=!rec;
        else if(f==='flag') show=!!rec&&rec.v==='flag';
        else if(f!=='all') show=el.dataset.kind===f;
        el.style.display=show?'':'none';
      }});
    }});
  }});
  document.getElementById('rv-export').addEventListener('click',function(){{
    var ok=[],fl=[],todo=[];
    items.forEach(function(el){{
      var rid=el.dataset.rid, rec=store[rid];
      if(!rec) todo.push(rid);
      else if(rec.v==='ok') ok.push(rid);
      else fl.push(rid+(rec.n?' — '+rec.n:' — (no note)'));
    }});
    var t='{lv} CONTENT REVIEW\\n'+
      'approved: '+ok.length+'  flagged: '+fl.length+'  not reviewed: '+todo.length+'\\n\\n'+
      'APPROVED\\n'+(ok.length?ok.map(function(x){{return '  '+x;}}).join('\\n'):'  (none)')+'\\n\\n'+
      'NEEDS CHANGE\\n'+(fl.length?fl.map(function(x){{return '  '+x;}}).join('\\n'):'  (none)')+'\\n\\n'+
      'NOT REVIEWED\\n'+(todo.length?todo.map(function(x){{return '  '+x;}}).join('\\n'):'  (none)');
    var out=document.getElementById('rv-out');
    out.style.display='block'; out.value=t; out.focus(); out.select();
    try{{ navigator.clipboard.writeText(t); }}catch(e){{}}
  }});
  items.forEach(paint); progress();
}})();
</script>
{copyright_footer()}</body></html>'''


def gen_content_review_index(by_level):
    rows = ""
    total = 0
    for level, items in by_level.items():
        if not items:
            continue
        total += len(items)
        c = {k: sum(1 for i in items if i["kind"] == k)
             for k in ("reading", "mediation", "broadcast")}
        rows += (f'<a href="/content-review/{level}.html" '
                 f'style="display:block;padding:12px 14px;margin:7px 0;border:1px solid '
                 f'var(--border);border-radius:10px;text-decoration:none">'
                 f'<b style="color:var(--accent);font-size:1.05rem">{level.upper()}</b>'
                 f'<span style="color:var(--text-muted);margin-inline-start:8px;font-size:0.85rem">'
                 f'{len(items)} items</span><br>'
                 f'<span style="color:var(--text-secondary);font-size:0.85rem">'
                 f'📖 {c["reading"]} reading · 🤝 {c["mediation"]} mediation · '
                 f'🎧 {c["broadcast"]} extended listening</span></a>')
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0"><meta name="robots" content="noindex,nofollow">
<link rel="icon" type="image/png" href="/favicon.png">
<title>Content review | Empire English</title>
<link rel="stylesheet" href="/css/empire.css"></head><body>
<div class="container">
<div class="header"><img src="/logo.png" alt="Empire" style="width:44px;height:44px;border-radius:50%;margin-bottom:8px">
<h1 style="font-size:1.4rem">Content review</h1>
<p class="subtitle">{total} authored items awaiting your sign-off</p></div>
<div class="card"><p style="margin:0;color:var(--text-secondary);font-size:0.9rem">
Everything authored for reading, mediation and extended listening, with the audio playable and the
correct answer marked on every question. Approve or flag each item; your decisions save on this
device, and the button at the bottom of each level builds a summary to send me.</p>
<p style="margin:10px 0 0;color:var(--text-muted);font-size:0.82rem">
This page is owner-only — it shows every answer, so it sits behind the ops passcode, not a student session.</p></div>
{rows}
<div class="footer">Empire English Community — owner review surface</div>
</div>{copyright_footer()}</body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level", choices=list(ALL_WEEK_COUNTS), default=None,
                         help="Generate only this level (default: every level "
                              "that has curriculum data on disk)")
    args = parser.parse_args()

    if not DATA_DIR.exists():
        raise SystemExit(
            f"ERROR: empire-nexus data directory not found: {DATA_DIR}\n"
            f"Set EEC_REPO_DIR to the correct path, e.g.:\n"
            f"  EEC_REPO_DIR=/path/to/empire-nexus python3 generate.py"
        )

    print("Generating Empire English Practice Platform...")
    print(f"  Reading curriculum from: {BOT_DIR}")
    print(f"  Writing pages to:        {OUTPUT_DIR}")

    # Default: every level that actually has curriculum data on disk — the
    # legacy L0–L3 today, plus each CEFR level as its content ships (A1, A2,
    # …). A level with no week-1 data file is skipped so we never emit empty
    # directories for unauthored levels (b1–c2).
    if args.level:
        levels = [args.level]
    else:
        levels = [lvl for lvl in ALL_WEEK_COUNTS
                  if (DATA_DIR / f"{lvl}_week1.json").exists()]
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

    # --- owner content-review surface (passcode-gated, not student-facing) ---
    review_dir = OUTPUT_DIR / "content-review"
    review_dir.mkdir(parents=True, exist_ok=True)
    by_level, reviewable = {}, 0
    for level in ALL_WEEK_COUNTS:
        items = review_items(level)
        by_level[level] = items
        if not items:
            continue
        reviewable += len(items)
        with open(review_dir / f"{level}.html", "w", encoding="utf-8") as f:
            f.write(gen_content_review(level, items))
        total += 1
    with open(review_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(gen_content_review_index(by_level))
    total += 1
    print(f"  Content review: {reviewable} items across "
          f"{sum(1 for v in by_level.values() if v)} levels -> /content-review/")

    print(f"\n  TOTAL: {total} HTML pages generated")
    print(f"  Audio manifest: {AUDIO_MANIFEST_PATH} ({len(audio_manifest)} clips needed)")
    print(f"  Run generate_audio.py against this manifest to produce Kokoro MP3s.")

    # Keep the student/owner manuals in sync with the system on every build.
    # The guides' AUTO regions (level table, feature-flag catalog, counts) are
    # filled from the same curriculum/config data used above, so any change to
    # the system flows into the guides here instead of drifting until someone
    # notices. Editorial prose is untouched — see scripts/guide_sync.py. If
    # empire-nexus is absent the sync no-ops with a warning rather than failing.
    print("\n  Syncing guide manuals (/guide, /ops-guide)...")
    _sync_guides()

    print(f"  Platform ready at: {OUTPUT_DIR}/")


def _sync_guides():
    """Run guide_sync in-process. Kept out of the main flow above so a guide
    import problem can never block the (more important) page generation."""
    try:
        import guide_sync
        guide_sync.main()
    except SystemExit:
        pass  # guide_sync.main() returns via sys.exit in some paths
    except Exception as exc:  # noqa: BLE001
        print(f"  ::warning::guide sync skipped — {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
