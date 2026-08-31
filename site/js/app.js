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
  _audio: null,
  _warned: false,

  /**
   * Where the pre-rendered speech clips live. NOT /audio/ on the site:
   * Cloudflare Pages caps a free-plan deployment at 20,000 files and site/ is
   * already at 8,056, so the 9,360 speech clips are served from R2.
   */
  // The /vN/ segment must match R2_PREFIX in scripts/render_speech.py. It is
  // bumped whenever the AUDIO changes for text that has not changed: a clip id
  // hashes voice+text, not the bytes, so a re-render lands on the same URL —
  // and these objects are served `immutable` for a year AND cached cache-first
  // by the service worker. Without a new path, students would keep the old
  // audio. v2 fixes clips whose phonemes were corrupted by rendering below
  // speed 1.0.
  BASE: 'https://audio.empireenglish.online/speech/v2',

  init() {
    // Nothing to load. The old implementation hunted for an en-US
    // speechSynthesis voice here, which is exactly what this replaced: the
    // device voice varies by phone, is robotic, and on many Android handsets
    // is not American at all — on a programme that teaches American English.
    this.voice = null;
  },

  /** The single voice this page speaks in, derived from the URL. Cached
   *  because every call site would otherwise recompute it. */
  pageVoice() {
    if (!this._pageVoice) {
      this._pageVoice = (typeof SpeechId !== 'undefined')
        ? SpeechId.voiceForPath(location.pathname)
        : 'af_heart';
    }
    return this._pageVoice;
  },

  /**
   * Say out loud that a clip is missing, INSTEAD of quietly falling back to
   * the robotic device voice. A silent fallback is how the robot voice
   * survived on 7 page types unnoticed; if audio is missing the student and
   * the owner should both be able to see that it is missing.
   */
  _reportMissing(text) {
    if (this._warned) return;          // one banner per page, not one per click
    this._warned = true;
    try {
      const bar = document.createElement('div');
      bar.setAttribute('role', 'alert');
      bar.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:9999;' +
        'background:#c0392b;color:#fff;padding:10px 14px;font-size:0.9rem;' +
        'text-align:center;line-height:1.5';
      bar.innerHTML = '\u26a0\ufe0f <b>Audio missing for this page.</b> ' +
        'The recording has not been generated yet \u2014 please report this. ' +
        '<span dir="rtl" lang="ar">\u0627\u0644\u0635\u0648\u062a \u063a\u064a\u0631 ' +
        '\u0645\u062a\u0648\u0641\u0631 \u0644\u0647\u0630\u0647 \u0627\u0644\u0635\u0641\u062d\u0629</span>';
      document.body.appendChild(bar);
    } catch (e) { /* document not ready — the console line below still lands */ }
    console.error('[TTS] no clip for:', JSON.stringify(text),
                  'voice:', this.pageVoice());
  },

  /**
   * Speak `text`. `onDone` (Phase 11D) is invoked when the utterance
   * finishes OR errors, which is what lets KokoroAudio.playSequence chain
   * one segment to the next when it is running on the browser-TTS fallback
   * path rather than on pre-generated MP3s. Optional and backwards
   * compatible: every existing caller passes one or two arguments.
   *
   * Note that speechSynthesis.cancel() (i.e. TTS.stop()) also fires onend,
   * so any sequencing built on this callback must guard against advancing
   * after a deliberate stop -- playSequence does, via its cancel flag.
   */
  speak(text, rate = null, onDone = null) {
    this.stop();
    const r = parseFloat(rate || this.rate);
    this.speaking = true;
    let finished = false;
    const finish = () => {                 // fires once, on end OR failure
      if (finished) return;
      finished = true;
      this.speaking = false;
      if (typeof onDone === 'function') onDone();
    };

    if (typeof SpeechId === 'undefined') {
      // speech-id.js failed to load. Do NOT fall back to speechSynthesis —
      // that is the robotic voice this replaced, and a silent fallback is
      // precisely how it went unnoticed on 7 page types.
      this._reportMissing(text);
      finish();
      return;
    }

    SpeechId.clipId(this.pageVoice(), text).then((id) => {
      const audio = new Audio(`${this.BASE}/${id}.mp3`);
      this._audio = audio;
      // The clip is rendered at a neutral ~160 wpm and the per-call-site
      // slowdown is applied here instead of being baked in, which would have
      // meant a separate clip per rate. Browsers pitch-correct playbackRate,
      // so a slow word still sounds like the same speaker.
      audio.playbackRate = r;
      audio.addEventListener('ended', finish);
      audio.addEventListener('error', () => {
        this._reportMissing(text);
        finish();
      });
      audio.play().catch(() => {
        // Autoplay policy blocks playback until the first user gesture. That
        // is not a missing clip, so it must not raise the missing-audio
        // banner — every call site here is already behind a click or a
        // setTimeout following one.
        finish();
      });
    }).catch(() => {                        // SubtleCrypto unavailable
      this._reportMissing(text);
      finish();
    });
  },

  stop() {
    if (this._audio) {
      this._audio.pause();
      this._audio = null;
    }
    // Cancel any utterance queued by an older cached copy of this file. Harmless
    // when nothing is speaking, and it keeps a stale service-worker cache from
    // leaving a robot voice running underneath the new one.
    if (typeof speechSynthesis !== 'undefined') speechSynthesis.cancel();
    this.speaking = false;
  },

  setRate(rate) {
    this.rate = parseFloat(rate);
    if (this._audio) this._audio.playbackRate = this.rate;
  }
};

// ============================================================
//  KOKORO AUDIO (pre-generated studio-quality clips, with
//  automatic fallback to browser TTS if the MP3 isn't there yet)
// ============================================================
const KokoroAudio = {
  _current: null,
  _fallbackText: null,
  _seqCancelled: false,
  rate: 0.75,

  /**
   * Play a pre-generated clip by id (see audio-manifest.json / generate.py).
   * Falls back to the browser's SpeechSynthesis voice if the MP3 is
   * missing (e.g. Kokoro generation hasn't been run yet for this clip),
   * so every page works correctly even before audio has been generated.
   */
  play(id, fallbackText, rate = null) {
    this.stop();
    this._fallbackText = fallbackText;
    if (rate) this.rate = parseFloat(rate);
    const audio = new Audio(`/audio/${id}.mp3`);
    this._current = audio;
    audio.playbackRate = this.rate;

    audio.addEventListener('error', () => {
      // MP3 not found (404) or unsupported — use browser TTS instead.
      TTS.speak(fallbackText, this.rate);
    });

    audio.play().catch(() => {
      // Autoplay/decoding failure — fall back too.
      TTS.speak(fallbackText, this.rate);
    });
  },

  /**
   * Fix D015: the Shadowing page's Stop button called TTS.stop() and its
   * Speed <select> called TTS.setRate() -- but the passage is actually
   * played via KokoroAudio.play() (an <audio> element), not TTS's
   * speechSynthesis. Neither control ever touched the real playing
   * <audio> element, so Stop did nothing while a clip was mid-playback
   * and Speed changes had no audible effect until/unless the fallback
   * TTS path happened to be in use. stop() now pauses the actual <audio>
   * element (and still cancels speechSynthesis as a no-op-safe fallback,
   * in case the browser-TTS path was the one actually playing).
   */
  stop() {
    // Phase 11D: cancel any running sequence FIRST. TTS.stop() below fires
    // the utterance's onend, which is the same callback playSequence uses to
    // advance -- without this flag, pressing Stop mid-sequence on the
    // browser-TTS fallback path would start the next segment instead.
    this._seqCancelled = true;
    if (this._current) {
      this._current.pause();
      this._current = null;
    }
    TTS.stop();
  },

  /**
   * Phase 11D — play a LIST of clips back to back as one continuous piece of
   * audio.
   *
   * This is what makes extended listening possible at all. The five CEFR
   * descriptors this exercise exists for include "most TV news ... and films
   * in standard dialect" and "main points of many radio or TV programmes",
   * and a news bulletin or a two-person scene cannot be one voice reading one
   * blob: each speaker turn is its own clip with its own Kokoro voice, and
   * they have to play in order without the student pressing anything between
   * them.
   *
   * `items` is [{id, text}]. Each item independently falls back to browser
   * TTS if its MP3 is missing, so a script works end to end before Kokoro has
   * been run over it -- and a single failed clip degrades that one turn
   * instead of breaking the whole sequence.
   *
   * opts: {rate, onSegment(index), onEnd()}.
   */
  playSequence(items, opts = {}) {
    this.stop();
    this._seqCancelled = false;
    if (!Array.isArray(items) || items.length === 0) return;
    if (opts.rate) this.rate = parseFloat(opts.rate);
    const onSegment = typeof opts.onSegment === 'function' ? opts.onSegment : null;
    const onEnd = typeof opts.onEnd === 'function' ? opts.onEnd : null;

    const playAt = (i) => {
      if (this._seqCancelled) return;
      if (i >= items.length) {
        this._current = null;
        if (onEnd) onEnd();
        return;
      }
      if (onSegment) onSegment(i);
      const item = items[i] || {};
      const next = () => playAt(i + 1);
      const audio = new Audio(`/audio/${item.id}.mp3`);
      this._current = audio;
      audio.playbackRate = this.rate;
      // Guard against double-advancing: an <audio> element can fire both
      // 'error' and a rejected play() promise for the same failure.
      let handed = false;
      const fallback = () => {
        if (handed || this._seqCancelled) return;
        handed = true;
        TTS.speak(item.text || '', this.rate, next);
      };
      audio.addEventListener('error', fallback);
      audio.addEventListener('ended', () => {
        if (handed || this._seqCancelled) return;
        handed = true;
        next();
      });
      audio.play().catch(fallback);
    };
    playAt(0);
  },

  /**
   * Fix D015 (Speed control): apply a new rate immediately to whatever is
   * currently playing (mid-clip playbackRate changes on <audio> apply
   * live), and remember it for the next play() call too.
   */
  setRate(rate) {
    this.rate = parseFloat(rate);
    if (this._current) this._current.playbackRate = this.rate;
    TTS.setRate(rate);
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
  mimeType: 'audio/webm', // actual negotiated type, set at start()

  /**
   * Pick a MIME type the current browser's MediaRecorder can actually
   * produce. Fixes D014: 'audio/webm' was hardcoded everywhere (both
   * here and in the Blob construction in stop()), but Safari/iOS
   * MediaRecorder does not support audio/webm at all -- recording
   * silently produced a blob tagged as audio/webm that Safari itself
   * (and the <audio> playback element used for "Listen to Yours") could
   * not decode, so nothing played back and downloads were unusable.
   * Feature-detect the best available type instead of assuming one.
   */
  _pickMimeType() {
    const candidates = [
      'audio/mp4',                 // Safari/iOS
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/ogg;codecs=opus',
    ];
    if (typeof MediaRecorder === 'undefined' || !MediaRecorder.isTypeSupported) {
      return ''; // let the browser pick its own default
    }
    return candidates.find(c => MediaRecorder.isTypeSupported(c)) || '';
  },

  async start(onTimeUpdate) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferredType = this._pickMimeType();
      this.mediaRecorder = preferredType
        ? new MediaRecorder(stream, { mimeType: preferredType })
        : new MediaRecorder(stream);
      // Use whatever MediaRecorder actually reports it's producing (it may
      // differ slightly from the requested type, e.g. adding a codec
      // string) so the Blob we build in stop() is tagged correctly.
      this.mimeType = this.mediaRecorder.mimeType || preferredType || 'audio/webm';
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
        const blob = new Blob(this.chunks, { type: this.mimeType || 'audio/webm' });
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
    // Fix D016: the "Done" checkbox on each exercise page called
    // markDone() but nothing re-rendered the progress bar/task counter on
    // the same page afterward -- Gamification._renderProgressBar() only
    // ran once, on DOMContentLoaded, before the checkbox existed in its
    // "done" state. Checking the box gave zero visible feedback that
    // anything happened. Re-run both here so the change is reflected
    // immediately, without needing per-page markup changes in
    // generate.py's 4 near-identical checkbox handlers.
    if (typeof Gamification !== 'undefined') {
      Gamification._renderProgressBar();
      Gamification._checkDailyCompletion();
    }
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
    this._viewed = new Set();   // Level 2: distinct cards reviewed this session
    this._completed = false;
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

    // Level 2: auto-complete the day's vocab once the student has reviewed
    // every flashcard at least once (a genuine full pass). Covers students
    // who study by cards rather than the quiz, so neither path blocks them.
    if (this._viewed) {
      this._viewed.add(this.index);
      if (!this._completed && this.words.length > 0 &&
          this._viewed.size >= this.words.length && window.ExerciseComplete) {
        this._completed = true;
        window.ExerciseComplete();
      }
    }
  },

  hearWord() {
    const word = this.words[this.index];
    if (word) TTS.speak(word.word, 0.7);
  }
};

// ============================================================
//  CONNECTED PROGRESS (Sahel S6 — Discord bot API sync)
// ============================================================
const ConnectedProgress = {
  token: null,
  data: null,
  API_BASE: 'https://bot.empireenglish.online',  // Cloudflare Tunnel
  // Hisn D030: tracks whether the CURRENT page load's token came fresh
  // from the !link URL (vs. a previously-saved token on an ordinary
  // homepage revisit) -- see index.html's listener for why this
  // distinction matters (auto-jump to today's exercises on a fresh
  // !link click, but don't force-navigate away on a normal revisit).
  _connectedFromUrlThisLoad: false,

  init() {
    // Hisn D029: !link's DM'd URL is `{platform_url}?token={token}` --
    // but until now, nothing on this page ever read the `?token=` query
    // parameter at all. It was silently ignored: clicking that link just
    // landed on the plain homepage with the token sitting inert in the
    // address bar, doing nothing, while the student would have had to
    // separately notice the "Connect Discord" button and manually
    // paste the same token in by hand for it to take effect. Confirmed
    // live during Hisn H6 (owner "took the link straight" and it never
    // connected). Now checked FIRST, before falling back to any
    // previously-saved token in localStorage, and persisted the same
    // way manual connect() already does -- so following the !link URL
    // directly connects immediately, exactly as its own DM text implies
    // ("your personal link").
    const urlToken = new URLSearchParams(window.location.search).get('token');
    if (urlToken) {
      this._connectedFromUrlThisLoad = true;
      this.connect(urlToken);
      // Remove the token from the visible URL after consuming it (same
      // reasoning !link's own DM gives for not sharing it -- a token
      // sitting in the address bar is easy to accidentally screenshot/
      // share). replaceState avoids adding a new history entry.
      const cleanUrl = window.location.pathname + window.location.hash;
      window.history.replaceState({}, document.title, cleanUrl);
      return;
    }
    // R1 fix (2026-07-28): prefer the CURRENT active Darb session token over
    // the legacy empire_link_token. That legacy key can hold a stale/cap-
    // evicted session token (a revoked device) — which makes /api/progress
    // 404 and then self-disconnect, wiping the streak header for a student
    // who is otherwise perfectly signed in via their active Darb session
    // (confirmed live 2026-07-28). Using the live session token (whose device
    // IS active) fixes the 404, and we keep empire_link_token in sync so the
    // exercise-page gates that still read it stay consistent. Falls back to
    // the legacy token only when there's no active Darb session.
    if (typeof DarbSession !== 'undefined') {
      try { DarbSession.init(); } catch (e) { /* no-op */ }
      if (DarbSession.hasSession && DarbSession.hasSession()) {
        this.token = DarbSession.getToken();
        localStorage.setItem('empire_link_token', this.token);
        this._fetchProgress();
        return;
      }
    }
    this.token = localStorage.getItem('empire_link_token');
    if (this.token) {
      this._fetchProgress();
    }
  },

  connect(token) {
    token = token.trim();
    if (!token) return;
    localStorage.setItem('empire_link_token', token);
    this.token = token;
    this._fetchProgress();
  },

  disconnect() {
    localStorage.removeItem('empire_link_token');
    this.token = null;
    this.data = null;
    this._updateUI();
  },

  async _fetchProgress() {
    try {
      const res = await fetch(`${this.API_BASE}/api/progress?token=${this.token}`);
      if (!res.ok) {
        if (res.status === 404) {
          // Invalid token
          this.disconnect();
        }
        return;
      }
      this.data = await res.json();
      this._updateUI();
      // Hisn D029: let pages that need to react to the student's real
      // level/week (currently just the homepage's picker) hook in
      // without ConnectedProgress needing to know those pages exist.
      // Dispatched every time fresh data arrives (not just on first
      // connect), so a page that's already open and later becomes
      // connected still gets the update.
      //
      // Hisn D030: includes fromUrlThisLoad so listeners can tell "this
      // is a fresh !link click, just now" apart from "this token was
      // already saved from a previous visit" -- the homepage uses this
      // to decide whether to auto-jump straight to today's exercises
      // (fresh link click -- the whole point was to get straight to
      // today's tasks) vs. just highlighting today's card without
      // forcing navigation away (ordinary revisit, e.g. browsing an
      // earlier week -- shouldn't get yanked back to today every time).
      window.dispatchEvent(new CustomEvent('empire:progress-loaded', {
        detail: { ...this.data, fromUrlThisLoad: this._connectedFromUrlThisLoad },
      }));
    } catch (e) {
      // Network error — use cached data or ignore
    }
  },

  _updateUI() {
    const streakEl = document.getElementById('streak-display');
    const connectBtn = document.getElementById('connect-discord-btn');

    if (this.data && streakEl) {
      streakEl.textContent = `🔥 ${this.data.streak}`;
      streakEl.title = `${this.data.streak} day streak (synced from Discord)`;
    }

    // Show pronunciation stats if available
    if (this.data && this.data.pronunciation && this.data.pronunciation.last_score !== null) {
      const pron = this.data.pronunciation;
      const pronEl = document.getElementById('pronunciation-stat');
      if (pronEl) {
        const trend = pron.trend === 'improving' ? '↑' : pron.trend === 'declining' ? '↓' : '→';
        pronEl.textContent = `🎯 ${pron.average_7d}% ${trend}`;
        pronEl.title = `Pronunciation: ${pron.average_7d}% avg (${pron.trend})`;
        pronEl.style.display = 'inline';
      }
    }

    if (connectBtn) {
      connectBtn.style.display = this.token ? 'none' : 'inline-flex';
    }
  },

  async submitSrsReview(word, score) {
    if (!this.token) return false;
    try {
      const res = await fetch(`${this.API_BASE}/api/srs-review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: this.token, word, score })
      });
      return res.ok;
    } catch (e) {
      // Queue for later
      const queue = JSON.parse(localStorage.getItem('empire_srs_queue') || '[]');
      queue.push({ word, score, ts: Date.now() });
      localStorage.setItem('empire_srs_queue', JSON.stringify(queue));
      return false;
    }
  },

  async syncQueue() {
    if (!this.token) return;
    const queue = JSON.parse(localStorage.getItem('empire_srs_queue') || '[]');
    if (!queue.length) return;
    const remaining = [];
    for (const item of queue) {
      try {
        const res = await fetch(`${this.API_BASE}/api/srs-review`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: this.token, word: item.word, score: item.score })
        });
        if (!res.ok) remaining.push(item);
      } catch (e) {
        remaining.push(item);
        break; // still offline
      }
    }
    localStorage.setItem('empire_srs_queue', JSON.stringify(remaining));
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
    this._restoreDoneCheckbox();
  },

  /**
   * Where am I? Returns {level, week, day, type} or null.
   *
   * ONE parser, because three copies of this had already rotted. Each of
   * _restoreDoneCheckbox, _renderProgressBar and _checkDailyCompletion carried
   * its own `/\/(l\d)\/week(\d+)\/day(\d)/` — the LEGACY L0-L3 level scheme.
   * The site moved to CEFR levels (a1..c2) and those levels were archived, so
   * that pattern has matched NOTHING since: all three functions have been
   * silently returning early on every page of the site.
   *
   * darb.js was updated for CEFR at the time and app.js was not, which is why
   * marking an exercise done still worked while restoring it never did. A
   * student reported the symptom: she completed the grammar exercise, left,
   * came back, and it showed as not done. It had been saved correctly all
   * along — nothing read it back.
   *
   * The exercise list matches darb.js: all ten surfaces, not the four this
   * used to know about.
   */
  _locate() {
    const EX = ['accent', 'shadowing', 'listening', 'vocab', 'speaking',
                'grammar', 'reading', 'mediation', 'review', 'broadcast'];
    const path = window.location.pathname;
    const m = path.match(/\/(l\d|[abc][12])\/week(\d+)\/day(\d+)/);
    if (!m) return null;
    const type = EX.find(t => path.endsWith('/' + t) || path.endsWith('/' + t + '.html'));
    return { level: m[1], week: parseInt(m[2]), day: parseInt(m[3]),
             type: type || null, exercises: EX };
  },

  /**
   * Fix D017: the "Done" checkbox's checked state was never restored on
   * page load -- Progress.markDone() writes to localStorage, but nothing
   * ever read it back to set the checkbox's `.checked` property, so
   * navigating away and back always showed an unchecked box even though
   * the exercise really was recorded as done.
   *
   * That fix was correct and then quietly stopped working: see _locate().
   * DarbDone.init() only renders "✅ Completed today" when it finds the box
   * already checked, so with this dead the completed state was invisible on
   * every return visit.
   */
  _restoreDoneCheckbox() {
    const at = this._locate();
    if (!at || !at.type) return;
    const checkbox = document.querySelector('.done-section .checkbox');
    if (!checkbox) return;
    checkbox.checked = Progress.isDone(at.level, at.week, at.day, at.type);
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

  // The bar counts the FIVE exercises in the bottom nav. It used to count four
  // and divide by four while the nav already showed five, so 'speaking' could
  // never be reflected. The remaining surfaces (grammar, reading, mediation,
  // review, broadcast) are reached from the day menu and are deliberately not
  // part of the daily bar — widening it would change what "day complete" means.
  DAILY_EXERCISES: ['accent', 'shadowing', 'listening', 'vocab', 'speaking'],

  _renderProgressBar() {
    const bar = document.getElementById('daily-progress');
    if (!bar) return;
    const at = this._locate();
    if (!at) return;

    const types = this.DAILY_EXERCISES;
    let done = 0;
    types.forEach(t => { if (Progress.isDone(at.level, at.week, at.day, t)) done++; });

    const pct = (done / types.length) * 100;
    bar.innerHTML = `<div class="progress-fill" style="width:${pct}%"></div>`;
    bar.title = `${done}/${types.length} exercises done today`;

    // Update tasks counter
    const counter = document.getElementById('tasks-done');
    if (counter) counter.textContent = `✅ ${done}/${types.length}`;
  },

  _checkDailyCompletion() {
    const at = this._locate();
    if (!at) return;

    const types = this.DAILY_EXERCISES;
    const allDone = types.every(t => Progress.isDone(at.level, at.week, at.day, t));

    if (allDone) {
      const confettiKey = `empire_confetti_${at.level}_w${at.week}_d${at.day}`;
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
    // Only on exercise pages. 'speaking' (E1, the 5th exercise) was missing
    // here, so students couldn't swipe to/from the Speaking page even though
    // it appears in the bottom nav and page nav — added for consistency.
    const pages = ['accent', 'shadowing', 'listening', 'vocab', 'speaking'];
    const path = window.location.pathname;
    const current = pages.find(p => path.endsWith('/' + p) || path.endsWith('/' + p + '.html'));
    if (!current) return;

    this.pages = pages;
    this.currentIndex = pages.indexOf(current);

    document.addEventListener('touchstart', (e) => this._onTouchStart(e), { passive: true });
    document.addEventListener('touchend', (e) => this._onTouchEnd(e), { passive: true });

    // Reveal the "← Swipe to navigate →" hint ONLY now that the listeners are
    // actually attached. The generator prints that hint on every exercise page,
    // but this function returns early on any page outside `pages` — so grammar,
    // reading, mediation, review and broadcast were advertising a gesture that
    // did nothing, which is what a student reported. The CSS now requires
    // .swipe-ready, so the hint and the behaviour cannot drift apart again.
    document.querySelectorAll('.swipe-hint')
      .forEach((el) => el.classList.add('swipe-ready'));
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
    // Include 'speaking' (E1) so the Speak tab highlights on its own page.
    const pages = ['accent', 'shadowing', 'listening', 'vocab', 'speaking'];
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
      // Results screen — clearly the END, not a wrong answer.
      // Level 2: finishing the quiz (answered every word) auto-completes vocab.
      if (window.ExerciseComplete) window.ExerciseComplete();
      const pct = Math.round((this.score / this.words.length) * 100);
      const praise = pct >= 80 ? 'أحسنت! ممتاز! / Excellent!'
        : pct >= 50 ? 'جيد! واصل التمرين / Good — keep going!'
        : 'استمر في التدريب / Keep practicing!';
      container.innerHTML = `<div class="card" style="text-align:center"><h2>🏆 ${this.score}/${this.words.length} (${pct}%)</h2>` +
        `<p style="color:var(--text-secondary);margin:12px 0">${praise}</p>` +
        `<div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">` +
        `<button class="btn btn-sm btn-outline" onclick="InteractiveVocab.switchMode('${this.mode}')">🔄 راجع تاني / Review again</button>` +
        `<a class="btn btn-sm" href="index.html">✅ خلصت / Done</a>` +
        `</div></div>`;
      return;
    }

    const word = this.words[this.currentIndex];
    const isTranslate = this.mode === 'quiz';
    // Translate: show Arabic, type English (no audio — it would reveal the
    // answer). Listen & Type: play the English audio, type what you hear.
    const prompt = isTranslate
      ? `<div style="font-family:'Cairo',sans-serif;font-size:1.4rem;direction:rtl;color:var(--accent);margin:16px 0">${this._escText(word.arabic)}</div>`
      : `<button class="btn" onclick="TTS.speak('${this._escAttr(word.word)}', 0.7)">🔊 اسمع الكلمة / Play word</button>`;

    const hint = isTranslate
      ? 'اكتب الكلمة بالإنجليزي / Type the English word'
      : 'اكتب الكلمة اللي سمعتها / Type the word you heard';

    container.innerHTML = `<div class="card"><p style="text-align:center;color:var(--text-muted)">${this.currentIndex + 1}/${this.words.length}</p>` +
      prompt +
      `<p style="color:var(--text-secondary);font-size:0.85rem;margin:10px 0">${hint}</p>` +
      `<input type="text" id="quiz-input" class="quiz-input" autocomplete="off" autocapitalize="off" placeholder="..." onkeydown="if(event.key==='Enter')InteractiveVocab.checkAnswer()">` +
      `<button class="btn btn-sm" style="margin-top:12px" onclick="InteractiveVocab.checkAnswer()">✓ تحقق / Check</button>` +
      `<div id="quiz-feedback" style="margin-top:12px"></div></div>`;

    // Auto-play in Listen & Type mode
    if (!isTranslate) setTimeout(() => TTS.speak(word.word, 0.7), 300);

    setTimeout(() => { const inp = document.getElementById('quiz-input'); if (inp) inp.focus(); }, 100);
  },

  checkAnswer() {
    const input = document.getElementById('quiz-input');
    const feedback = document.getElementById('quiz-feedback');
    if (!input || !feedback) return;

    const word = this.words[this.currentIndex];
    const result = this._match(input.value, word.word);
    this.attempted++;

    // A 🔊 replay so they always hear the correct pronunciation.
    const replay = `<button class="btn btn-sm btn-outline" style="margin-top:8px" onclick="TTS.speak('${this._escAttr(word.word)}', 0.7)">🔊 اسمعها / Hear it</button>`;

    if (result.ok && !result.almost) {
      this.score++;
      feedback.innerHTML = `<div style="color:var(--success);font-weight:600">✅ صح! Correct — ${this._escText(word.word)}</div>${replay}`;
    } else if (result.ok && result.almost) {
      // Tiny typo / spelling variant — count it, but show the exact spelling.
      this.score++;
      feedback.innerHTML = `<div style="color:var(--success);font-weight:600">✅ تقريباً صح! Almost — it's spelled: <b>${this._escText(word.word)}</b></div>${replay}`;
    } else {
      feedback.innerHTML = `<div style="color:var(--danger);font-weight:600">❌ الصح: ${this._escText(word.word)}</div>${replay}`;
    }

    input.disabled = true;
    setTimeout(() => { this.currentIndex++; this._renderQuizCard(); }, result.ok ? 1600 : 2400);
  },

  // ---- Forgiving answer matching ---------------------------------------
  // Normalise, accept US/UK spelling variants, and tolerate a 1-char typo
  // so students aren't wrongly told "try again" for trivial differences.
  _canon(s) {
    let t = String(s || '').toLowerCase().trim()
      .replace(/^[^a-z]+|[^a-z]+$/g, '')   // strip surrounding punctuation
      .replace(/\s+/g, ' ');
    // Curated, collision-GUARDED British→American normalisations so both
    // spellings canonicalise identically. Each pattern requires enough
    // leading letters that common short words are NOT swept up: the old
    // unanchored rules (/our\b/, /ise\b/, /re\b/, /ll/) mangled everyday
    // words and silently accepted WRONG answers — e.g. "for" was accepted
    // for "four" (four→"for"), "well"→"wel", "here"→"heer". Since both the
    // student's answer and the correct word pass through here, an exact
    // correct answer can never be rejected; the only risk is over-accepting
    // a wrong one, which these guards remove for the common collisions.
    t = t
      .replace(/([a-z]{2,})our\b/g, '$1or')       // colour→color, favour→favor (not four/hour/your/pour/tour/sour)
      .replace(/([a-z]{3,})isation\b/g, '$1ization') // organisation→organization
      .replace(/([a-z]{3,})ise\b/g, '$1ize')      // realise→realize (not wise/rise)
      .replace(/([a-z]{2,})re\b/g, '$1er')        // centre→center, metre→meter
      .replace(/([a-z]{3,})lling\b/g, '$1ling')   // travelling→traveling (not selling/telling stay-equal both sides anyway)
      .replace(/([a-z]{3,})lled\b/g, '$1led')     // travelled→traveled
      .replace(/([a-z]{3,})ller\b/g, '$1ler');    // traveller→traveler
    return t;
  },

  _lev(a, b) {
    const m = a.length, n = b.length;
    if (Math.abs(m - n) > 1) return 2;     // early out (>1 means "not close")
    const d = Array.from({ length: m + 1 }, (_, i) => [i, ...Array(n).fill(0)]);
    for (let j = 0; j <= n; j++) d[0][j] = j;
    for (let i = 1; i <= m; i++)
      for (let j = 1; j <= n; j++)
        d[i][j] = Math.min(d[i-1][j] + 1, d[i][j-1] + 1,
                           d[i-1][j-1] + (a[i-1] === b[j-1] ? 0 : 1));
    return d[m][n];
  },

  _match(answer, correct) {
    const ca = this._canon(answer), cc = this._canon(correct);
    if (!ca) return { ok: false, almost: false };
    if (ca === cc) return { ok: true, almost: false };
    // 1-character typo tolerance for words longer than 3 letters
    if (cc.length > 3 && this._lev(ca, cc) <= 1) return { ok: true, almost: true };
    return { ok: false, almost: false };
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

  /**
   * Accepts either plain strings (legacy: spoken text == expected answer)
   * or authored items {say, expected, hint} so the curriculum's curated
   * listening targets can carry a separate spoken form and an Arabic hint.
   */
  init(sentences) {
    this.sentences = (sentences || []).map(s => (
      typeof s === 'string'
        ? { say: s, expected: s, hint: '' }
        : { say: s.say || s.expected || '', expected: s.expected || s.say || '', hint: s.hint || '' }
    )).filter(s => s.say && s.expected);
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

    const item = this.sentences[this.currentIndex];
    const hintHtml = item.hint
      ? `<p class="arabic-text" lang="ar" dir="rtl" style="font-size:0.9rem;margin:10px 0">💡 ${item.hint}</p>`
      : '';
    section.innerHTML = `<div class="card"><h2>✍️ Dictation ${this.currentIndex + 1}/${this.sentences.length}</h2>` +
      `<button class="btn" onclick="TTS.speak('${item.say.replace(/'/g,"\\'")}', 0.6)">🔊 Play Sentence</button>` +
      hintHtml +
      `<p style="color:var(--text-secondary);font-size:0.85rem;margin:12px 0">Type what you hear / اكتب اللي سمعته</p>` +
      `<textarea id="dictation-input" class="quiz-input" rows="2" style="width:100%;resize:vertical" placeholder="..."></textarea>` +
      `<button class="btn btn-sm" style="margin-top:12px" onclick="Dictation.check()">✓ Check</button>` +
      `<div id="dictation-feedback" style="margin-top:12px"></div></div>`;

    setTimeout(() => TTS.speak(item.say, 0.6), 300);
    setTimeout(() => { const inp = document.getElementById('dictation-input'); if (inp) inp.focus(); }, 100);
  },

  check() {
    const input = document.getElementById('dictation-input');
    const feedback = document.getElementById('dictation-feedback');
    if (!input || !feedback) return;

    const answer = input.value.trim().toLowerCase().replace(/[.,!?;:'"]/g, '');
    const correct = this.sentences[this.currentIndex].expected.toLowerCase().replace(/[.,!?;:'"]/g, '');

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

      // Set download link. The generated markup hardcodes a
      // download="...webm" attribute (D014) -- correct the extension to
      // match the blob's real MIME type (e.g. Safari produces audio/mp4,
      // not audio/webm), so the downloaded file's extension matches its
      // actual contents and opens correctly on the device that made it.
      if (downloadLink) {
        downloadLink.href = this.audioUrl;
        const ext = this._extensionFor(this.blob.type);
        const base = (downloadLink.getAttribute('download') || 'recording.webm').replace(/\.\w+$/, '');
        downloadLink.setAttribute('download', `${base}.${ext}`);
      }
    }
  },

  /** Map a MIME type to a sensible file extension for downloads. */
  _extensionFor(mimeType) {
    if (!mimeType) return 'webm';
    if (mimeType.includes('mp4')) return 'm4a';
    if (mimeType.includes('ogg')) return 'ogg';
    if (mimeType.includes('webm')) return 'webm';
    return 'webm';
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
  ConnectedProgress.init();
  ConnectedProgress.syncQueue();
  
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
