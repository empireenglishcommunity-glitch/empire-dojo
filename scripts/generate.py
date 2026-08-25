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
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent  # empire-dojo/ (parent of scripts/)

import os

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
        words_html = " &bull; ".join(f"<b>{esc_html(w)}</b>" for w in words)
        words_card = (f'<div class="card"><h2>🎯 {bl("Practice Words", "كلمات للتمرين")}</h2><div class="transcript">{words_html}</div>'
                      f'<button class="btn btn-outline btn-sm" onclick="TTS.speak(\'{esc(", ".join(words))}\', 0.6)">🔊 {bl("Hear Words", "استمع للكلمات")}</button></div>')

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
<script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


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
<script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


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
<script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


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
<script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''

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
                     f' placeholder="{bl("your answer", "جوابك")}" style="margin-top:8px;width:100%">'
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
<script src="/js/app.js"></script><script src="/js/darb.js"></script>
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
<script src="/js/app.js"></script><script src="/js/darb.js"></script>
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
<script src="/js/app.js"></script><script src="/js/darb.js"></script>
<script>const words={safe_json_for_script_tag(words)};document.addEventListener('DOMContentLoaded',()=>{{Flashcard.init(words);InteractiveVocab.init(words)}});</script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


def gen_day_index(level, week, day, grammar=None, can_do=None):
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
</div></div>
<div class="nav" style="margin-top:20px"><a href="/index.html">← {bl("Home", "الرئيسية")}</a></div>
<div class="footer">Empire English Community — Common Sense First 🏛️</div>
</div>
<script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


# ============================================================
#  GENERATE
# ============================================================

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

    for week in range(1, max_week + 1):
        week_file = DATA_DIR / f"{level}_week{week}.json"
        if not week_file.exists():
            print(f"  [{level}] Skip week {week} (no data)")
            continue
        with open(week_file, encoding="utf-8") as f:
            week_data = json.load(f)

        accent_data = load_week_accent_data(level, week)
        grammar_data = load_week_grammar_data(level, week)
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
                                      can_do=week_can_do))
            with open(day_dir / "accent.html", "w", encoding="utf-8") as f:
                f.write(gen_accent(level, week, day, focus, norm,
                                   phoneme_focus=week_data.get("phoneme_focus")))
            with open(day_dir / "shadowing.html", "w", encoding="utf-8") as f:
                f.write(gen_shadowing(level, week, day, theme, norm, shadow_aid))
            with open(day_dir / "listening.html", "w", encoding="utf-8") as f:
                f.write(gen_listening(level, week, day, theme, day_vocab, vocab,
                                      day_listening=day_listening))

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
            # index + accent, shadowing, listening, vocab, speaking, grammar
            pages_per_day = 7
            total += pages_per_day

        print(f"  [{level}] Week {week}: {pages_per_day * 7} pages ✅")

    return total


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

    print(f"\n  TOTAL: {total} HTML pages generated")
    print(f"  Audio manifest: {AUDIO_MANIFEST_PATH} ({len(audio_manifest)} clips needed)")
    print(f"  Run generate_audio.py against this manifest to produce Kokoro MP3s.")
    print(f"  Platform ready at: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
