#!/usr/bin/env python3
"""Generate all practice platform HTML pages from curriculum data."""
import json, os
from pathlib import Path

DATA_DIR = Path("/projects/sandbox/EEC-REPO/bots/discord-learning-bot/data")
CONTENT_DIR = Path("/projects/sandbox/EEC-REPO/bots/discord-learning-bot/content/l0")
OUTPUT_DIR = Path("/projects/sandbox/Claude/practice-platform/l0")

# Shadowing passages (custom content per week)
PASSAGES = {
    1: ["Hello. My name is Sarah. I am from Cairo. I live in a small apartment. I like to read books and drink coffee. Nice to meet you.",
        "Good morning. How are you today? I am fine, thank you. What is your name? My name is Ahmed. I am a student.",
        "I wake up at seven. I eat breakfast. Then I go to work. I come home at five. I eat dinner with my family.",
        "This is my house. It has three rooms. The kitchen is small. The bedroom is big. I like my house.",
        "I have a brother and a sister. My brother is tall. My sister is short. We are a happy family.",
        "Today is Monday. It is sunny. I feel happy. I want to learn English. I study every day.",
        "I like food. I eat rice and chicken. I drink water. My favorite food is pizza."],
    2: ["What time is it? It is three o'clock. I have a meeting at four. I need to hurry.",
        "There are seven days in a week. Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday.",
        "I wake up early in the morning. Usually at six thirty. I go to bed at eleven.",
        "How much is this? It costs ten dollars. That is expensive. Can I have a discount?",
        "My birthday is in March. March is in spring. The weather is warm and sunny.",
        "I have two appointments today. The first is at nine. The second is at two. I am busy.",
        "Tomorrow is Friday. Friday is the weekend. I do not work on Friday. I rest and relax."],
}

DIALOGUES = {
    1: [
        {"text": "Hi, my name is Tom. Nice to meet you.", "q": "What is the speaker's name?", "opts": ["Tom", "Tim", "Sam"], "ans": 0},
        {"text": "I live in Cairo. Cairo is a big city. I like Cairo.", "q": "Where does the speaker live?", "opts": ["London", "Cairo", "Dubai"], "ans": 1},
        {"text": "I have two brothers and one sister.", "q": "How many brothers?", "opts": ["One", "Two", "Three"], "ans": 1},
        {"text": "I eat breakfast at seven. I eat lunch at twelve.", "q": "When is lunch?", "opts": ["Seven", "Twelve", "Three"], "ans": 1},
        {"text": "My favorite color is blue. I do not like red.", "q": "Which color does he NOT like?", "opts": ["Blue", "Green", "Red"], "ans": 2},
        {"text": "I go to work by bus. The bus comes at eight.", "q": "How does he go to work?", "opts": ["Car", "Bus", "Walk"], "ans": 1},
        {"text": "Today is hot. Forty degrees. I want cold water.", "q": "How is the weather?", "opts": ["Cold", "Hot", "Rainy"], "ans": 1},
    ],
}

def esc(s):
    """Escape for HTML/JS."""
    return s.replace("'", "\\'").replace('"', '&quot;')

def gen_accent(week, day, accent_data, focus):
    drill = None
    if accent_data and accent_data.get("daily_drills") and day <= len(accent_data["daily_drills"]):
        drill = accent_data["daily_drills"][day - 1]
    
    if drill and isinstance(drill, dict):
        sounds = ", ".join(drill.get("target_sounds", []) if isinstance(drill.get("target_sounds"), list) else [])
        pairs = drill.get("minimal_pairs", []) if isinstance(drill.get("minimal_pairs"), list) else []
        pairs_html = "<br>".join(f"<b>{p['pair'][0]}</b> / <b>{p['pair'][1]}</b>" for p in pairs[:4] if isinstance(p, dict) and 'pair' in p)
        wp = drill.get("word_practice", [])
        words = list(wp)[:6] if isinstance(wp, list) else ["pen", "paper", "people"]
        sentence = drill.get("record_this", "I am practicing English.") if isinstance(drill.get("record_this"), str) else "I am practicing English."
        instr_ar = "تمرّن على الأصوات"
        iso = drill.get("isolation", {})
        if isinstance(iso, dict):
            instr_ar = iso.get("instructions_ar", instr_ar)
    else:
        sounds = "Review all sounds"
        pairs_html = "pat / bat<br>pin / bin"
        words = ["pen", "paper", "people", "happy"]
        sentence = "Please put the paper on the table."
        instr_ar = "اسمع وكرر"

    words_html = " &bull; ".join(f"<b>{w}</b>" for w in words)
    
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Accent Week {week} Day {day} | Empire English</title><link rel="stylesheet" href="../../../css/empire.css"></head><body>
<div class="container"><div class="header"><div class="brand">🏛️</div><h1>🎯 Accent Drill</h1><p class="subtitle">Week {week} • Day {day} • {focus}</p></div>
<div class="arabic-text">{instr_ar}</div>
<div class="card"><h2>🔊 Target Sounds: {sounds}</h2>
<button class="btn" onclick="TTS.speak('{esc(sentence)}')">▶️ Listen to Model</button>
<div class="speed-control"><label>Speed:</label><select id="speed-select" onchange="TTS.setRate(this.value)"><option value="0.6">Slow</option><option value="0.8" selected>Normal</option><option value="1.0">Fast</option></select></div></div>
<div class="card"><h2>📝 Minimal Pairs</h2><div class="transcript">{pairs_html}</div></div>
<div class="card"><h2>🎯 Practice Words</h2><div class="transcript">{words_html}</div>
<button class="btn btn-outline btn-sm" onclick="TTS.speak('{esc(", ".join(words))}', 0.6)">🔊 Hear Words</button></div>
<div class="card"><h2>🎙️ Say This</h2><div class="transcript"><b>"{sentence}"</b></div>
<button class="btn btn-outline" onclick="TTS.speak('{esc(sentence)}', 0.7)">🔊 Model</button></div>
<div class="done-section"><label><input type="checkbox" class="checkbox" onchange="if(this.checked)Progress.markDone('l0',{week},{day},'accent')"> Done ✅</label></div>
<div class="nav" style="margin-top:20px"><a href="../../../index.html">← Home</a><a href="shadowing.html">Shadowing →</a></div></div>
<script src="../../../js/app.js"></script></body></html>'''

def gen_shadowing(week, day, theme, passage):
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Shadowing Week {week} Day {day} | Empire English</title><link rel="stylesheet" href="../../../css/empire.css"></head><body>
<div class="container"><div class="header"><div class="brand">🏛️</div><h1>🎧 Shadowing</h1><p class="subtitle">Week {week} • Day {day} • {theme}</p></div>
<div class="arabic-text">اسمع → كرر 3 مرات → سجل المحاولة الثالثة</div>
<div class="card"><h2>📝 Passage</h2><div class="transcript">{passage}</div>
<button class="btn" onclick="TTS.speak('{esc(passage)}')">▶️ Play</button>
<button class="btn btn-outline" onclick="TTS.stop()">⏹️ Stop</button>
<div class="speed-control"><label>Speed:</label><select id="speed-select" onchange="TTS.setRate(this.value)"><option value="0.6">Slow</option><option value="0.75" selected>Normal</option><option value="1.0">Fast</option></select></div></div>
<div class="done-section"><label><input type="checkbox" class="checkbox" onchange="if(this.checked)Progress.markDone('l0',{week},{day},'shadowing')"> Done ✅</label></div>
<div class="nav" style="margin-top:20px"><a href="accent.html">← Accent</a><a href="listening.html">Listening →</a></div></div>
<script src="../../../js/app.js"></script></body></html>'''

def gen_listening(week, day, theme, dial):
    opts = ""
    for i, o in enumerate(dial["opts"]):
        correct = "true" if i == dial["ans"] else "false"
        data_c = ' data-correct' if i == dial["ans"] else ''
        opts += f'<div class="option"{data_c} onclick="checkAnswer(this,{correct})">{o}</div>'
    
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Listening Week {week} Day {day} | Empire English</title><link rel="stylesheet" href="../../../css/empire.css"></head><body>
<div class="container"><div class="header"><div class="brand">🏛️</div><h1>👂 Listening</h1><p class="subtitle">Week {week} • Day {day} • {theme}</p></div>
<div class="arabic-text">اسمع الحوار وجاوب السؤال. ممكن تسمع أكتر من مرة.</div>
<div class="card"><h2>🔊 Listen</h2>
<button class="btn" onclick="TTS.speak('{esc(dial["text"])}')">▶️ Play</button>
<button class="btn btn-outline" onclick="TTS.stop()">⏹️ Stop</button>
<div class="speed-control"><label>Speed:</label><select id="speed-select" onchange="TTS.setRate(this.value)"><option value="0.6">Slow</option><option value="0.75" selected>Normal</option><option value="1.0">Fast</option></select></div></div>
<div class="card"><h2>❓ {dial["q"]}</h2><div class="options">{opts}</div></div>
<div class="done-section"><label><input type="checkbox" class="checkbox" onchange="if(this.checked)Progress.markDone('l0',{week},{day},'listening')"> Done ✅</label></div>
<div class="nav" style="margin-top:20px"><a href="shadowing.html">← Shadowing</a><a href="vocab.html">Vocab →</a></div></div>
<script src="../../../js/app.js"></script>
<script>function checkAnswer(el,c){{document.querySelectorAll('.option').forEach(o=>o.style.pointerEvents='none');if(c)el.classList.add('correct');else{{el.classList.add('wrong');document.querySelector('[data-correct]').classList.add('correct')}}}}</script></body></html>'''

def gen_vocab(week, day, theme, words):
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Vocabulary Week {week} Day {day} | Empire English</title><link rel="stylesheet" href="../../../css/empire.css"></head><body>
<div class="container"><div class="header"><div class="brand">🏛️</div><h1>📖 Vocabulary</h1><p class="subtitle">Week {week} • Day {day} • {theme}</p></div>
<div class="arabic-text">اضغط البطاقة لرؤية المعنى. اضغط 🔊 لسماع الكلمة.</div>
<div class="card"><p id="card-counter" style="text-align:center;color:var(--text-muted)">1/{len(words)}</p>
<div class="flashcard" id="flashcard" onclick="Flashcard.flip()"></div>
<div class="audio-controls" style="justify-content:center">
<button class="btn btn-sm btn-outline" onclick="Flashcard.prev()">←</button>
<button class="btn btn-sm" onclick="Flashcard.hearWord()">🔊</button>
<button class="btn btn-sm btn-outline" onclick="Flashcard.next()">→</button></div></div>
<div class="done-section"><label><input type="checkbox" class="checkbox" onchange="if(this.checked)Progress.markDone('l0',{week},{day},'vocab')"> Done ✅</label></div>
<div class="nav" style="margin-top:20px"><a href="listening.html">← Listening</a><a href="../../../index.html">Home</a></div></div>
<script src="../../../js/app.js"></script>
<script>const words={json.dumps(words, ensure_ascii=False)};document.addEventListener('DOMContentLoaded',()=>Flashcard.init(words));</script></body></html>'''

# === GENERATE ===
print("Generating Empire English Practice Platform...")
total = 0

for week in range(1, 9):
    week_file = DATA_DIR / f"l0_week{week}.json"
    if not week_file.exists():
        print(f"  Skip week {week} (no data)")
        continue
    with open(week_file, encoding='utf-8') as f:
        week_data = json.load(f)

    accent_data = None
    accent_files = list(CONTENT_DIR.glob(f"accent/week{week}*.json"))
    if accent_files:
        with open(accent_files[0], encoding='utf-8') as f:
            accent_data = json.load(f)
    
    focus = accent_data.get("focus", "Review") if accent_data else "Review"
    theme = week_data.get("theme", "General")
    vocab = week_data.get("vocabulary", [])
    passages = PASSAGES.get(week, PASSAGES[1])
    dialogues = DIALOGUES.get(week, DIALOGUES[1])

    for day in range(1, 8):
        day_dir = OUTPUT_DIR / f"week{week}" / f"day{day}"
        day_dir.mkdir(parents=True, exist_ok=True)

        day_vocab = vocab[(day-1)*8 : day*8] if len(vocab) >= day*8 else vocab[:8]
        passage = passages[(day-1) % len(passages)]
        dial = dialogues[(day-1) % len(dialogues)]

        with open(day_dir / "accent.html", "w", encoding="utf-8") as f:
            f.write(gen_accent(week, day, accent_data, focus))
        with open(day_dir / "shadowing.html", "w", encoding="utf-8") as f:
            f.write(gen_shadowing(week, day, theme, passage))
        with open(day_dir / "listening.html", "w", encoding="utf-8") as f:
            f.write(gen_listening(week, day, theme, dial))
        with open(day_dir / "vocab.html", "w", encoding="utf-8") as f:
            f.write(gen_vocab(week, day, theme, day_vocab))
        total += 4

    print(f"  Week {week}: 28 pages ✅")

print(f"\n  TOTAL: {total} HTML pages generated")
print(f"  Platform ready at: practice-platform/")
