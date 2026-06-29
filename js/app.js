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
//  LANGUAGE TOGGLE
// ============================================================
const Lang = {
  current: 'ar', // Default Arabic for L0

  toggle() {
    this.current = this.current === 'ar' ? 'en' : 'ar';
    document.querySelectorAll('.arabic-text').forEach(el => {
      el.style.display = this.current === 'ar' ? 'block' : 'none';
    });
    const btn = document.getElementById('lang-toggle-btn');
    if (btn) btn.textContent = this.current === 'ar' ? 'EN' : 'عربي';
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

    if (this.flipped) {
      card.innerHTML = `
        <div class="arabic">${word.arabic}</div>
        <div class="pos">${word.pos || ''}</div>
        <div class="instruction">Tap to flip back</div>
      `;
    } else {
      card.innerHTML = `
        <div class="word">${word.word}</div>
        <div class="pronunciation">${word.pronunciation}</div>
        <div class="instruction">Tap to see Arabic meaning</div>
      `;
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
//  INITIALIZATION
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  TTS.init();
  
  // Speed control
  const speedSelect = document.getElementById('speed-select');
  if (speedSelect) {
    speedSelect.addEventListener('change', (e) => TTS.setRate(e.target.value));
  }

  // Language toggle
  const langBtn = document.getElementById('lang-toggle-btn');
  if (langBtn) langBtn.addEventListener('click', () => Lang.toggle());
});
