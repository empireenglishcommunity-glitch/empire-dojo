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
  
  // Speed control
  const speedSelect = document.getElementById('speed-select');
  if (speedSelect) {
    speedSelect.addEventListener('change', (e) => TTS.setRate(e.target.value));
  }
});
