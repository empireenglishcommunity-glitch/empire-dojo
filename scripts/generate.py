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
LEVEL_WEEK_COUNTS = {"l0": 8, "l1": 10, "l2": 12, "l3": 8}

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
    `active` is one of: 'accent', 'shadowing', 'listening', 'vocab'."""
    items = [
        ('accent', '🎯', 'Accent'),
        ('shadowing', '🎧', 'Shadow'),
        ('listening', '👂', 'Listen'),
        ('vocab', '📖', 'Vocab'),
    ]
    links = ""
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
            '<meta name="robots" content="noindex, nofollow">')


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

def gen_accent(level, week, day, focus, norm):
    sounds = esc_html(norm["sounds"] or "Review")
    focus = esc_html(focus)
    primary = norm["primary_text"]
    instr_ar = esc_html(norm["instr_ar"])

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
<div class="nav page-nav" style="margin-top:20px"><a href="index.html">← {bl("Today", "اليوم")}</a><a href="shadowing.html">{bl("Shadowing", "المحاكاة")} →</a></div></div>
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
<div class="nav page-nav" style="margin-top:20px"><a href="accent.html">← {bl("Accent", "النطق")}</a><a href="listening.html">{bl("Listening", "الاستماع")} →</a></div></div>
{bottom_nav('shadowing')}
<script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


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
            opts_html += f'<div class="option"{data_c} onclick="checkAnswer(this,{is_correct})">{esc_html(o["arabic"])}</div>'
        q_html += (f'<div class="card"><h2>🔊 {bl("Word", "كلمة")} {qi+1}</h2>'
                   f'<button class="btn btn-sm" onclick="TTS.speak(\'{esc(word["word"])}\', 0.7)">▶️ {bl("Play Word", "شغل الكلمة")}</button>'
                   f'<div class="question" style="margin-top:14px"><p>❓ {bl("What does this word mean?", "معنى الكلمة دي إيه؟")}</p>'
                   f'<div class="options">{opts_html}</div></div></div>')

    if not q_html:
        q_html = f'<div class="card"><p>{bl("No vocabulary available for this day yet.", "لا توجد مفردات متاحة لهذا اليوم حتى الآن.")}</p></div>'

    theme = esc_html(theme)

    # Build dictation sentences from vocab words for this day (S2.3)
    dictation_words = [esc(w["word"]) for w in day_vocab[:5] if w.get("word")]
    dictation_json = safe_json_for_script_tag([w["word"] for w in day_vocab[:5] if w.get("word")])

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
<div class="done-section"><label><input type="checkbox" class="checkbox" onchange="if(this.checked)Progress.markDone('{level}',{week},{day},'listening')"> {bl("Done", "تم")} ✅</label></div>
{swipe_hint()}
<div class="nav page-nav" style="margin-top:20px"><a href="shadowing.html">← {bl("Shadowing", "المحاكاة")}</a><a href="vocab.html">{bl("Vocab", "المفردات")} →</a></div></div>
{bottom_nav('listening')}
<script src="/js/app.js"></script><script src="/js/darb.js"></script>
<script>const dictationWords={dictation_json};document.addEventListener('DOMContentLoaded',()=>Dictation.init(dictationWords));function checkAnswer(el,c){{el.closest('.options').querySelectorAll('.option').forEach(o=>o.style.pointerEvents='none');if(c)el.classList.add('correct');else{{el.classList.add('wrong');el.closest('.options').querySelector('[data-correct]').classList.add('correct')}}}}</script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


def gen_vocab(level, week, day, theme, words):
    theme = esc_html(theme)
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link rel="icon" type="image/png" href="/favicon.png"><title>Vocabulary Week {week} Day {day} | Empire English</title>{pwa_head()}<link rel="stylesheet" href="/css/empire.css">{content_gate_css()}</head><body>
{watermark_comment()}
{content_gate_overlay()}
<div id="gated-content" class="gated-content">
<div class="container"><div class="header"><img src="/logo.png" alt="Empire" style="width:40px;height:40px;border-radius:50%;box-shadow:0 0 10px rgba(212,175,55,0.3);margin-bottom:10px"><h1>📖 Vocabulary</h1><p class="subtitle">Week {week} • Day {day} • {theme}</p></div>
{gamification_bar()}
<div class="arabic-text" lang="ar" dir="rtl">اختار طريقة التمرين: بطاقات، اختبار، أو استماع.</div>
<div class="mode-toggle">
<button class="mode-btn active" data-mode="flashcard" onclick="InteractiveVocab.switchMode('flashcard')">📖 {bl("Cards", "بطاقات")}</button>
<button class="mode-btn" data-mode="quiz" onclick="InteractiveVocab.switchMode('quiz')">✍️ {bl("Quiz", "اختبار")}</button>
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
<div class="done-section"><label><input type="checkbox" class="checkbox" onchange="if(this.checked)Progress.markDone('{level}',{week},{day},'vocab')"> {bl("Done", "تم")} ✅</label></div>
{swipe_hint()}
<div class="nav page-nav" style="margin-top:20px"><a href="listening.html">← {bl("Listening", "الاستماع")}</a><a href="index.html">{bl("Today", "اليوم")}</a></div></div>
{bottom_nav('vocab')}
<script src="/js/app.js"></script><script src="/js/darb.js"></script>
<script>const words={safe_json_for_script_tag(words)};document.addEventListener('DOMContentLoaded',()=>{{Flashcard.init(words);InteractiveVocab.init(words)}});</script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


def gen_day_index(level, week, day, pattern=None):
    pattern_card = ""
    if pattern:
        phrase = esc_html(pattern.get("phrase", ""))
        when = esc_html(pattern.get("when", ""))
        arabic = esc_html(pattern.get("arabic", ""))
        example = esc_html(pattern.get("example", ""))
        phrase_escaped = esc(pattern.get("phrase", ""))
        today_pattern_label = bl("Today's Pattern", "نمط اليوم")
        listen_label = bl("Listen", "استمع")
        pattern_card = (
            f'<div class="card" style="border-left:3px solid var(--accent)">'
            f'<h2>💬 {today_pattern_label}</h2>'
            f'<div class="transcript" style="font-size:1.3rem;line-height:1.6"><b>{phrase}</b></div>'
            f'<p style="color:var(--text-secondary);margin:8px 0">📍 {when}</p>'
            f'<p style="font-family:Cairo,sans-serif;direction:rtl;color:var(--accent-light);margin:8px 0">{arabic}</p>'
            f'<p style="color:var(--text-secondary);font-size:0.85rem;margin:12px 0;font-style:italic">💡 "{example}"</p>'
            f'<button class="btn btn-sm" onclick="TTS.speak(\'{phrase_escaped}\', 0.7)">🔊 {listen_label}</button>'
            f'</div>'
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
{pattern_card}
<div class="card"><h2>📋 {bl("Today's Exercises", "تمارين اليوم")}</h2>
<div class="nav" style="flex-direction:column;align-items:stretch">
<a href="accent.html">🎯 Accent Drill — تدريب النطق</a>
<a href="shadowing.html">🎧 Shadowing — المحاكاة</a>
<a href="listening.html">👂 Listening — الاستماع</a>
<a href="vocab.html">📖 Vocabulary — المفردات</a>
</div></div>
<div class="nav" style="margin-top:20px"><a href="/index.html">← {bl("Home", "الرئيسية")}</a></div>
<div class="footer">Empire English Community — Common Sense First 🏛️</div>
</div>
<script src="/js/app.js"></script><script src="/js/darb.js"></script>{content_gate_js()}{copyright_footer()}</div></body></html>'''


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


def load_patterns(level):
    """Load patterns for a level, returning a flat list for round-robin."""
    patterns_file = CONTENT_DIR / "patterns" / f"{level}_patterns.json"
    if not patterns_file.exists():
        return []
    with open(patterns_file, encoding="utf-8") as f:
        data = json.load(f)
    # Flatten all categories into one list
    flat = []
    categories = list(data.keys())
    # Interleave categories for variety (round-robin through categories)
    max_per_cat = max((len(v) for v in data.values()), default=0)
    for i in range(max_per_cat):
        for cat in categories:
            items = data[cat]
            if i < len(items):
                flat.append(items[i])
    return flat


def generate_level(level, audio_manifest):
    max_week = LEVEL_WEEK_COUNTS[level]
    total = 0
    patterns = load_patterns(level)
    pattern_idx = 0

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

            # Split weekly vocab into 7 days using the SAME adaptive formula
            # as the bot's curriculum.py get_vocabulary_for_day() (len // 7,
            # no fallback). Previously this used a hardcoded "8 words/day"
            # slice that fell back to vocab[:8] (day 1's words, verbatim)
            # for any week with fewer than day*8 total words -- silently
            # showing day 1's vocabulary again on day 6/7 (or worse) for
            # every week below the 56-word threshold. That's every L2/L3
            # week (denser, more advanced vocab by design) plus a couple
            # of L1 weeks. Must stay in sync with curriculum.py's formula.
            words_per_day = max(1, len(vocab) // 7)
            day_vocab = vocab[(day - 1) * words_per_day: day * words_per_day]
            norm = normalize_drill(drills_by_day.get(day))
            shadow_aid = audio_id(level, week, day, "shadow")

            with open(day_dir / "index.html", "w", encoding="utf-8") as f:
                day_pattern = patterns[pattern_idx % len(patterns)] if patterns else None
                pattern_idx += 1
                f.write(gen_day_index(level, week, day, pattern=day_pattern))
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
            f"ERROR: empire-nexus data directory not found: {DATA_DIR}\n"
            f"Set EEC_REPO_DIR to the correct path, e.g.:\n"
            f"  EEC_REPO_DIR=/path/to/empire-nexus python3 generate.py"
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
