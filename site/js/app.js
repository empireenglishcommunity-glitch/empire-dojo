/**
 * Empire English Practice Platform — Main Application
 * TTS Engine, Voice Recorder, Timer, Progress Tracking
 */

// ============================================================
//  TEXT-TO-SPEECH ENGINE
// ============================================================
const TTS = {
  speaking: false,
  rate: 0.85, // Slow for beginners
  voice: null,

  init() {
    // Find American English voice
    const loadVoices = () => {
      const voices = speechSynthesis.getVoices();
      this.voice = voices.find(v => v.lang === 'en-US' && v.name.includes('Google')) ||
                   voices.find(v => v.lang === 'en-US') ||
                   voices[0];
    };
    loadVoices();
    speechSynthesis.onvoiceschanged = loadVoices;
  },

  speak(text, rate = null) {
    this.stop();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.voice = this.voice;
    utterance.rate = rate || this.rate;
    utterance.pitch = 1;
    utterance.lang = 'en-US';
    this.speaking = true;
    utterance.onend = () => { this.speaking = false; };
    speechSynthesis.speak(utterance);
  },

  stop() {
    speechSynthesis.cancel();
    this.speaking = false;
  },

  setRate(rate) {
    this.rate = parseFloat(rate);
  }
};

// ============================================================
//  KOKORO AUDIO (pre-generated studio-quality clips, with
//  automatic fallback to browser TTS if the MP3 isn't there yet)
// ============================================================
const KokoroAudio = {
  _current: null,

  /**
   * Play a pre-generated clip by id (see audio-manifest.json / generate.py).
   * Falls back to the browser's SpeechSynthesis voice if the MP3 is
   * missing (e.g. Kokoro generation hasn't been run yet for this clip),
   * so every page works correctly even before audio has been generated.
   */
  play(id, fallbackText, rate = null) {
    this.stop();
    const audio = new Audio(`/audio/${id}.mp3`);
    this._current = audio;
    if (rate) audio.playbackRate = rate;

    audio.addEventListener('error', () => {
      // MP3 not found (404) or unsupported — use browser TTS instead.
      TTS.speak(fallbackText, rate);
    });

    audio.play().catch(() => {
      // Autoplay/decoding failure — fall back too.
      TTS.speak(fallbackText, rate);
    });
  },

  stop() {
    if (this._current) {
      this._current.pause();
      this._current = null;
    }
    TTS.stop();
  }
};

// ============================================================
//  VOICE RECORDER
// ============================================================
const Recorder = {
  mediaRecorder: null,
  chunks: [],
  recording: false,
  startTime: null,

  async start(onTimeUpdate) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.mediaRecorder = new MediaRecorder(stream);
      this.chunks = [];
      this.recording = true;
      this.startTime = Date.now();

      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) this.chunks.push(e.data);
      };

      this.mediaRecorder.start();

      // Update timer
      if (onTimeUpdate) {
        this._timer = setInterval(() => {
          const elapsed = Math.floor((Date.now() - this.startTime) / 1000);
          onTimeUpdate(elapsed);
        }, 1000);
      }
    } catch (err) {
      alert('لم نتمكن من الوصول للمايك. تأكد من إعطاء الإذن.');
    }
  },

  stop() {
    return new Promise((resolve) => {
      if (!this.mediaRecorder || !this.recording) { resolve(null); return; }
      
      this.mediaRecorder.onstop = () => {
        const blob = new Blob(this.chunks, { type: 'audio/webm' });
        this.recording = false;
        clearInterval(this._timer);
        resolve(blob);
      };
      
      this.mediaRecorder.stop();
      this.mediaRecorder.stream.getTracks().forEach(t => t.stop());
    });
  },

  getElapsed() {
    if (!this.startTime) return 0;
    return Math.floor((Date.now() - this.startTime) / 1000);
  }
};

// ============================================================
//  TIMER
// ============================================================
const Timer = {
  seconds: 0,
  running: false,
  interval: null,
  el: null,

  init(elementId, targetSeconds) {
    this.el = document.getElementById(elementId);
    this.target = targetSeconds;
    this.seconds = 0;
    this.update();
  },

  start() {
    this.running = true;
    this.interval = setInterval(() => {
      this.seconds++;
      this.update();
    }, 1000);
  },

  stop() {
    this.running = false;
    clearInterval(this.interval);
  },

  reset() {
    this.stop();
    this.seconds = 0;
    this.update();
  },

  update() {
    if (!this.el) return;
    const mins = Math.floor(this.seconds / 60);
    const secs = this.seconds % 60;
    this.el.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
    if (this.target && this.seconds >= this.target) {
      this.el.classList.add('recording');
    }
  },

  formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }
};

// ============================================================
//  PROGRESS TRACKING (localStorage)
// ============================================================
const Progress = {
  getKey(level, week, day, type) {
    return `empire_${level}_w${week}_d${day}_${type}`;
  },

  markDone(level, week, day, type) {
    localStorage.setItem(this.getKey(level, week, day, type), 'done');
  },

  isDone(level, week, day, type) {
    return localStorage.getItem(this.getKey(level, week, day, type)) === 'done';
  },

  getWeekProgress(level, week) {
    let done = 0;
    const types = ['accent', 'shadowing', 'listening', 'vocab'];
    for (let d = 1; d <= 7; d++) {
      for (const t of types) {
        if (this.isDone(level, week, d, t)) done++;
      }
    }
    return { done, total: 28 }; // 7 days × 4 types
  }
};

// ============================================================
//  FLASHCARD
// ============================================================
const Flashcard = {
  words: [],
  index: 0,
  flipped: false,

  init(words) {
    this.words = words;
    this.index = 0;
    this.flipped = false;
    this.render();
  },

  flip() {
    this.flipped = !this.flipped;
    this.render();
  },

  next() {
    this.index = (this.index + 1) % this.words.length;
    this.flipped = false;
    this.render();
  },

  prev() {
    this.index = (this.index - 1 + this.words.length) % this.words.length;
    this.flipped = false;
    this.render();
  },

  render() {
    const card = document.getElementById('flashcard');
    if (!card) return;
    const word = this.words[this.index];
    if (!word) return;

    // Build the flashcard's inner DOM with real elements + textContent
    // instead of an innerHTML template string. Found via adversarial-
    // input stress testing on empire-dojo's generate.py: word.arabic/
    // word.word/word.pronunciation/word.pos come straight from
    // curriculum JSON with no HTML sanitization anywhere in the
    // pipeline, and a crafted <img src=x onerror=...> value genuinely
    // executed here via the old innerHTML assignment. textContent can
    // never be interpreted as markup, so this closes the vulnerability
    // at the point where it actually executes, independent of whatever
    // escaping the page generator does (or fails to do) upstream.
    card.innerHTML = '';
    if (this.flipped) {
      const arabic = document.createElement('div');
      arabic.className = 'arabic';
      arabic.textContent = word.arabic;
      const pos = document.createElement('div');
      pos.className = 'pos';
      pos.textContent = word.pos || '';
      const instruction = document.createElement('div');
      instruction.className = 'instruction';
      instruction.innerHTML = 'Tap to flip back <span class="ar-inline" lang="ar" dir="rtl">/ اضغط للرجوع</span>';
      card.append(arabic, pos, instruction);
    } else {
      const wordEl = document.createElement('div');
      wordEl.className = 'word';
      wordEl.textContent = word.word;
      const pron = document.createElement('div');
      pron.className = 'pronunciation';
      pron.textContent = word.pronunciation;
      const instruction = document.createElement('div');
      instruction.className = 'instruction';
      instruction.innerHTML = 'Tap to see Arabic meaning <span class="ar-inline" lang="ar" dir="rtl">/ اضغط لرؤية المعنى</span>';
      card.append(wordEl, pron, instruction);
    }

    // Update counter
    const counter = document.getElementById('card-counter');
    if (counter) counter.textContent = `${this.index + 1} / ${this.words.length}`;
  },

  hearWord() {
    const word = this.words[this.index];
    if (word) TTS.speak(word.word, 0.7);
  }
};

// ============================================================
//  GAMIFICATION (Sahel S5 — streak, progress, confetti)
// ============================================================
const Gamification = {
  init() {
    this._updateStreak();
    this._renderProgressBar();
    this._checkDailyCompletion();
  },

  _getToday() {
    return new Date().toISOString().slice(0, 10); // YYYY-MM-DD
  },

  _updateStreak() {
    const today = this._getToday();
    const lastActive = localStorage.getItem('empire_last_active_date');
    let streak = parseInt(localStorage.getItem('empire_streak') || '0');

    if (lastActive === today) {
      // Already logged today, streak unchanged
    } else {
      const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
      if (lastActive === yesterday) {
        streak++;
      } else if (lastActive && lastActive !== today) {
        streak = 1; // Streak broken, restart
      } else {
        streak = 1; // First visit
      }
      localStorage.setItem('empire_streak', streak);
      localStorage.setItem('empire_last_active_date', today);
    }

    // Render streak in header if element exists
    const streakEl = document.getElementById('streak-display');
    if (streakEl) {
      streakEl.textContent = `🔥 ${streak}`;
      streakEl.title = `${streak} day streak`;
    }
  },

  _renderProgressBar() {
    const bar = document.getElementById('daily-progress');
    if (!bar) return;

    // Detect current level/week/day from URL
    const match = window.location.pathname.match(/\/(l\d)\/week(\d+)\/day(\d)/);
    if (!match) return;

    const [, level, week, day] = match;
    const types = ['accent', 'shadowing', 'listening', 'vocab'];
    let done = 0;
    types.forEach(t => { if (Progress.isDone(level, parseInt(week), parseInt(day), t)) done++; });

    const pct = (done / 4) * 100;
    bar.innerHTML = `<div class="progress-fill" style="width:${pct}%"></div>`;
    bar.title = `${done}/4 exercises done today`;

    // Update tasks counter
    const counter = document.getElementById('tasks-done');
    if (counter) counter.textContent = `✅ ${done}/4`;
  },

  _checkDailyCompletion() {
    const match = window.location.pathname.match(/\/(l\d)\/week(\d+)\/day(\d)/);
    if (!match) return;

    const [, level, week, day] = match;
    const types = ['accent', 'shadowing', 'listening', 'vocab'];
    const allDone = types.every(t => Progress.isDone(level, parseInt(week), parseInt(day), t));

    if (allDone) {
      const confettiKey = `empire_confetti_${level}_w${week}_d${day}`;
      if (!localStorage.getItem(confettiKey)) {
        localStorage.setItem(confettiKey, '1');
        this._showConfetti();
      }
    }
  },

  _showConfetti() {
    // Simple confetti animation using CSS
    const overlay = document.createElement('div');
    overlay.className = 'confetti-overlay';
    overlay.innerHTML = '<div class="confetti-message">🎉 أحسنت! All done today!</div>';
    document.body.appendChild(overlay);

    // Create confetti particles
    for (let i = 0; i < 40; i++) {
      const particle = document.createElement('div');
      particle.className = 'confetti-particle';
      particle.style.left = Math.random() * 100 + '%';
      particle.style.animationDelay = Math.random() * 2 + 's';
      particle.style.backgroundColor = ['#D4AF37', '#2ECC71', '#E74C3C', '#3498DB', '#F39C12'][Math.floor(Math.random() * 5)];
      overlay.appendChild(particle);
    }

    setTimeout(() => overlay.remove(), 4000);
  }
};

// ============================================================
//  SWIPE NAVIGATION (Sahel S1 — navigate between exercises)
// ============================================================
const SwipeNav = {
  startX: 0,
  startY: 0,
  threshold: 60, // minimum px to count as a swipe

  init() {
    // Only on exercise pages (accent, shadowing, listening, vocab)
    const pages = ['accent', 'shadowing', 'listening', 'vocab'];
    const path = window.location.pathname;
    const current = pages.find(p => path.endsWith('/' + p) || path.endsWith('/' + p + '.html'));
    if (!current) return;

    this.pages = pages;
    this.currentIndex = pages.indexOf(current);

    document.addEventListener('touchstart', (e) => this._onTouchStart(e), { passive: true });
    document.addEventListener('touchend', (e) => this._onTouchEnd(e), { passive: true });
  },

  _onTouchStart(e) {
    this.startX = e.changedTouches[0].screenX;
    this.startY = e.changedTouches[0].screenY;
  },

  _onTouchEnd(e) {
    const dx = e.changedTouches[0].screenX - this.startX;
    const dy = e.changedTouches[0].screenY - this.startY;

    // Only trigger if horizontal swipe is dominant (not scrolling)
    if (Math.abs(dx) < this.threshold || Math.abs(dy) > Math.abs(dx)) return;

    if (dx > 0) {
      // Swipe right → previous exercise
      this._navigate(-1);
    } else {
      // Swipe left → next exercise
      this._navigate(1);
    }
  },

  _navigate(direction) {
    const newIndex = this.currentIndex + direction;
    if (newIndex < 0 || newIndex >= this.pages.length) return;
    // Navigate to sibling page (same day, different exercise)
    window.location.href = this.pages[newIndex];
  }
};

// ============================================================
//  BOTTOM NAV HIGHLIGHT (Sahel S1)
// ============================================================
const BottomNav = {
  init() {
    const nav = document.getElementById('bottom-nav');
    if (!nav) return;
    const pages = ['accent', 'shadowing', 'listening', 'vocab'];
    const path = window.location.pathname;
    const current = pages.find(p => path.endsWith('/' + p) || path.endsWith('/' + p + '.html'));
    if (!current) return;

    const links = nav.querySelectorAll('a');
    links.forEach(a => {
      const href = a.getAttribute('href');
      if (href && (href.endsWith('/' + current) || href.endsWith('/' + current + '.html') || href === current + '.html' || href === current)) {
        a.classList.add('active');
      }
    });
  }
};

// ============================================================
//  INTERACTIVE VOCAB (Sahel S2 — Quiz Mode + Listen & Type)
// ============================================================
const InteractiveVocab = {
  words: [],
  mode: 'flashcard', // 'flashcard' | 'quiz' | 'listen'
  currentIndex: 0,
  score: 0,
  attempted: 0,

  init(words) {
    this.words = words;
    this.currentIndex = 0;
    this.score = 0;
    this.attempted = 0;
    // Mode buttons will call switchMode
  },

  switchMode(mode) {
    this.mode = mode;
    this.currentIndex = 0;
    this.score = 0;
    this.attempted = 0;

    // Update mode buttons
    document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
    const activeBtn = document.querySelector(`.mode-btn[data-mode="${mode}"]`);
    if (activeBtn) activeBtn.classList.add('active');

    // Show/hide sections
    const flashcardSection = document.getElementById('flashcard-section');
    const quizSection = document.getElementById('quiz-section');

    if (flashcardSection) flashcardSection.style.display = mode === 'flashcard' ? 'block' : 'none';
    if (quizSection) quizSection.style.display = mode !== 'flashcard' ? 'block' : 'none';

    if (mode !== 'flashcard') this._renderQuizCard();
  },

  _renderQuizCard() {
    const container = document.getElementById('quiz-section');
    if (!container || !this.words.length) return;

    if (this.currentIndex >= this.words.length) {
      // Show final score
      const pct = Math.round((this.score / this.words.length) * 100);
      container.innerHTML = `<div class="card"><h2>🏆 ${this.score}/${this.words.length} (${pct}%)</h2>` +
        `<p style="color:var(--text-secondary);margin:12px 0">${pct >= 80 ? 'أحسنت! Excellent!' : pct >= 50 ? 'Good effort! حاول تاني' : 'Keep practicing! كمّل تمرين'}</p>` +
        `<button class="btn btn-sm" onclick="InteractiveVocab.switchMode('${this.mode}')">🔄 Try Again</button></div>`;
      return;
    }

    const word = this.words[this.currentIndex];
    const isQuiz = this.mode === 'quiz';
    // Quiz: show Arabic, type English. Listen: play English audio, type word.
    const prompt = isQuiz
      ? `<div style="font-family:'Cairo',sans-serif;font-size:1.4rem;direction:rtl;color:var(--accent);margin:16px 0">${this._escText(word.arabic)}</div>`
      : `<button class="btn" onclick="TTS.speak('${this._escAttr(word.word)}', 0.7)">🔊 Play Word</button>`;

    const hint = isQuiz ? 'Type the English word / اكتب الكلمة بالإنجليزي' : 'Type what you hear / اكتب اللي سمعته';

    container.innerHTML = `<div class="card"><p style="text-align:center;color:var(--text-muted)">${this.currentIndex + 1}/${this.words.length}</p>` +
      prompt +
      `<p style="color:var(--text-secondary);font-size:0.85rem;margin:10px 0">${hint}</p>` +
      `<input type="text" id="quiz-input" class="quiz-input" autocomplete="off" autocapitalize="off" placeholder="..." onkeydown="if(event.key==='Enter')InteractiveVocab.checkAnswer()">` +
      `<button class="btn btn-sm" style="margin-top:12px" onclick="InteractiveVocab.checkAnswer()">✓ Check</button>` +
      `<div id="quiz-feedback" style="margin-top:12px"></div></div>`;

    // Auto-play in listen mode
    if (!isQuiz) setTimeout(() => TTS.speak(word.word, 0.7), 300);

    // Focus input
    setTimeout(() => { const inp = document.getElementById('quiz-input'); if (inp) inp.focus(); }, 100);
  },

  checkAnswer() {
    const input = document.getElementById('quiz-input');
    const feedback = document.getElementById('quiz-feedback');
    if (!input || !feedback) return;

    const word = this.words[this.currentIndex];
    const answer = input.value.trim().toLowerCase();
    const correct = word.word.toLowerCase();
    this.attempted++;

    if (answer === correct) {
      this.score++;
      feedback.innerHTML = `<div style="color:var(--success);font-weight:600">✅ Correct! — ${this._escText(word.word)}</div>`;
    } else {
      feedback.innerHTML = `<div style="color:var(--danger);font-weight:600">❌ ${this._escText(word.word)}</div>`;
    }

    input.disabled = true;
    setTimeout(() => { this.currentIndex++; this._renderQuizCard(); }, 1500);
  },

  _escText(s) { return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); },
  _escAttr(s) { return String(s || '').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'&quot;'); }
};

// ============================================================
//  DICTATION MODE (Sahel S2 — Listening page)
// ============================================================
const Dictation = {
  sentences: [],
  currentIndex: 0,
  score: 0,

  init(sentences) {
    this.sentences = sentences;
    this.currentIndex = 0;
    this.score = 0;
  },

  show() {
    const section = document.getElementById('dictation-section');
    const quizSection = document.getElementById('listening-quiz-section');
    const modeBtn = document.querySelectorAll('.mode-btn');

    if (section) section.style.display = 'block';
    if (quizSection) quizSection.style.display = 'none';
    modeBtn.forEach(b => b.classList.remove('active'));
    const activeBtn = document.querySelector('.mode-btn[data-mode="dictation"]');
    if (activeBtn) activeBtn.classList.add('active');

    this._renderCard();
  },

  showQuiz() {
    const section = document.getElementById('dictation-section');
    const quizSection = document.getElementById('listening-quiz-section');
    const modeBtn = document.querySelectorAll('.mode-btn');

    if (section) section.style.display = 'none';
    if (quizSection) quizSection.style.display = 'block';
    modeBtn.forEach(b => b.classList.remove('active'));
    const activeBtn = document.querySelector('.mode-btn[data-mode="quiz"]');
    if (activeBtn) activeBtn.classList.add('active');
  },

  _renderCard() {
    const section = document.getElementById('dictation-section');
    if (!section || !this.sentences.length) return;

    if (this.currentIndex >= this.sentences.length) {
      const pct = Math.round((this.score / this.sentences.length) * 100);
      section.innerHTML = `<div class="card"><h2>🏆 ${this.score}/${this.sentences.length} (${pct}%)</h2>` +
        `<p style="color:var(--text-secondary);margin:12px 0">${pct >= 80 ? 'أحسنت! Excellent!' : 'Keep practicing! كمّل تمرين'}</p>` +
        `<button class="btn btn-sm" onclick="Dictation.currentIndex=0;Dictation.score=0;Dictation._renderCard()">🔄 Try Again</button></div>`;
      return;
    }

    const sentence = this.sentences[this.currentIndex];
    section.innerHTML = `<div class="card"><h2>✍️ Dictation ${this.currentIndex + 1}/${this.sentences.length}</h2>` +
      `<button class="btn" onclick="TTS.speak('${sentence.replace(/'/g,"\\'")}', 0.6)">🔊 Play Sentence</button>` +
      `<p style="color:var(--text-secondary);font-size:0.85rem;margin:12px 0">Type what you hear / اكتب اللي سمعته</p>` +
      `<textarea id="dictation-input" class="quiz-input" rows="2" style="width:100%;resize:vertical" placeholder="..."></textarea>` +
      `<button class="btn btn-sm" style="margin-top:12px" onclick="Dictation.check()">✓ Check</button>` +
      `<div id="dictation-feedback" style="margin-top:12px"></div></div>`;

    setTimeout(() => TTS.speak(sentence, 0.6), 300);
    setTimeout(() => { const inp = document.getElementById('dictation-input'); if (inp) inp.focus(); }, 100);
  },

  check() {
    const input = document.getElementById('dictation-input');
    const feedback = document.getElementById('dictation-feedback');
    if (!input || !feedback) return;

    const sentence = this.sentences[this.currentIndex];
    const answer = input.value.trim().toLowerCase().replace(/[.,!?;:'"]/g, '');
    const correct = sentence.toLowerCase().replace(/[.,!?;:'"]/g, '');

    // Simple word-by-word comparison
    const answerWords = answer.split(/\s+/).filter(Boolean);
    const correctWords = correct.split(/\s+/).filter(Boolean);
    let matches = 0;
    correctWords.forEach((w, i) => { if (answerWords[i] === w) matches++; });
    const accuracy = correctWords.length ? Math.round((matches / correctWords.length) * 100) : 0;

    if (accuracy >= 80) this.score++;

    const highlighted = correctWords.map((w, i) => {
      const got = answerWords[i] || '';
      return got === w ? `<span style="color:var(--success)">${w}</span>` : `<span style="color:var(--danger);text-decoration:underline">${w}</span>`;
    }).join(' ');

    feedback.innerHTML = `<div style="margin-top:8px"><p style="font-weight:600;color:${accuracy >= 80 ? 'var(--success)' : 'var(--danger)'}">${accuracy}% accurate</p>` +
      `<p style="margin-top:8px;line-height:1.8">${highlighted}</p></div>`;

    input.disabled = true;
    setTimeout(() => { this.currentIndex++; this._renderCard(); }, 3000);
  }
};

// ============================================================
//  SHADOW & RECORD (Sahel S2 — simultaneous play + record)
// ============================================================
const ShadowRecord = {
  /**
   * Play the model audio/TTS while simultaneously recording the user.
   * Uses the existing Recorder and KokoroAudio/TTS.
   */
  async start(audioId, fallbackText) {
    // Start recording first
    await RecorderUI.start();
    // Then play model (slight delay for mic to initialize)
    setTimeout(() => {
      if (audioId) {
        KokoroAudio.play(audioId, fallbackText);
      } else {
        TTS.speak(fallbackText, 0.75);
      }
    }, 300);
  }
};

// ============================================================
//  RECORDER UI (Sahel S0 — wires existing Recorder into pages)
// ============================================================
const RecorderUI = {
  blob: null,
  audioUrl: null,
  _player: null,

  /**
   * Start recording — updates UI to show stop button, timer, waveform.
   */
  async start() {
    // Clean up any previous recording playback
    this._stopPlayback();

    const card = document.querySelector('.recorder-card');
    const startBtn = document.getElementById('rec-start');
    const stopBtn = document.getElementById('rec-stop');
    const timer = document.getElementById('rec-timer');
    const indicator = document.getElementById('rec-indicator');
    const playback = document.getElementById('recorder-playback');

    if (!startBtn || !stopBtn) return;

    // Reset UI state
    startBtn.style.display = 'none';
    stopBtn.style.display = 'inline-flex';
    if (timer) { timer.textContent = '0:00'; timer.classList.add('is-recording'); }
    if (playback) playback.style.display = 'none';
    if (card) card.classList.add('is-recording');

    // Create waveform bars if not present
    if (indicator) {
      indicator.classList.add('active');
      if (!indicator.children.length) {
        for (let i = 0; i < 5; i++) {
          const bar = document.createElement('span');
          bar.className = 'bar';
          indicator.appendChild(bar);
        }
      }
    }

    // Start recording using existing Recorder class
    await Recorder.start((elapsed) => {
      if (timer) timer.textContent = Timer.formatTime(elapsed);
    });
  },

  /**
   * Stop recording — shows playback controls + A/B comparison.
   */
  async stop() {
    const card = document.querySelector('.recorder-card');
    const startBtn = document.getElementById('rec-start');
    const stopBtn = document.getElementById('rec-stop');
    const timer = document.getElementById('rec-timer');
    const indicator = document.getElementById('rec-indicator');
    const playback = document.getElementById('recorder-playback');
    const downloadLink = document.getElementById('rec-download');

    // Stop recording
    this.blob = await Recorder.stop();

    // Update UI
    if (stopBtn) stopBtn.style.display = 'none';
    if (startBtn) startBtn.style.display = 'inline-flex';
    if (timer) timer.classList.remove('is-recording');
    if (indicator) indicator.classList.remove('active');
    if (card) card.classList.remove('is-recording');

    if (this.blob) {
      // Create object URL for playback
      if (this.audioUrl) URL.revokeObjectURL(this.audioUrl);
      this.audioUrl = URL.createObjectURL(this.blob);

      // Show playback section
      if (playback) playback.style.display = 'block';

      // Set download link
      if (downloadLink) downloadLink.href = this.audioUrl;
    }
  },

  /**
   * Play back the user's recording.
   */
  playMine() {
    if (!this.audioUrl) return;
    this._stopPlayback();
    this._player = new Audio(this.audioUrl);
    this._player.play().catch(() => {});
  },

  /**
   * Stop any current playback of user recording.
   */
  _stopPlayback() {
    if (this._player) {
      this._player.pause();
      this._player.currentTime = 0;
      this._player = null;
    }
  }
};

// ============================================================
//  INITIALIZATION
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  TTS.init();
  SwipeNav.init();
  BottomNav.init();
  Gamification.init();
  
  // Speed control
  const speedSelect = document.getElementById('speed-select');
  if (speedSelect) {
    speedSelect.addEventListener('change', (e) => TTS.setRate(e.target.value));
  }

  // Register Service Worker (PWA — Sahel S4)
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }
});
