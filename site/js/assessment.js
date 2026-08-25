/**
 * Itqan — Weekly Assessment runner (Phase 5)
 *
 * A timed, one-question-at-a-time assessment page. Reads unlock state from
 * /api/assessment/status, runs the attempt via /start → /item → /finish, and
 * shows a two-score result with per-item feedback.
 *
 * Server is the source of truth for scoring, the timer, the unlock gate, the
 * single-attempt rule and the cooldown (see api_server.py / assessment.py).
 * The client timer and anti-cheat here are UX + signal only — never trusted.
 *
 * Reuses globals from app.js: TTS (speech), Recorder (low-level mic), and
 * DarbSession (session-authed fetch) from darb.js.
 */
const ItqanAssessment = {
  week: null,
  config: null,
  attempt: null,        // { attempt_id, items:[...], time_limit_min }
  idx: 0,
  answers: {},          // item_no -> true (submitted)
  blob: null,           // current recording blob (audio items)
  recording: false,
  timerId: null,
  remaining: 0,
  finishing: false,
  flags: { tab_aways: 0, blur_events: 0, paste_blocked: 0, time_expired_client: false },
  _antiCheatArmed: false,

  SECTIONS: ['asmt-loading', 'asmt-nosession', 'asmt-unavailable', 'asmt-locked',
             'asmt-cooldown', 'asmt-mastered', 'asmt-resume', 'asmt-intro',
             'asmt-runner', 'asmt-submitting', 'asmt-results'],

  _show(id) {
    this.SECTIONS.forEach(s => {
      const el = document.getElementById(s);
      if (el) el.style.display = (s === id) ? '' : 'none';
    });
  },

  _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  },

  // ---- init + routing ----------------------------------------------------

  async init() {
    DarbSession.init();
    if (!DarbSession.hasSession()) { this._show('asmt-nosession'); return; }

    const params = new URLSearchParams(location.search);

    // Detect assessment type: weekly (default), monthly, or advancement
    this.type = params.get('type') || 'weekly';
    this.week = parseInt(params.get('week'), 10);

    if (this.type === 'monthly') {
      return this._initMonthly();
    }
    if (this.type === 'advancement') {
      return this._initAdvancement();
    }

    // Weekly (original flow)
    if (!this.week || this.week < 1) {
      this._unavailable("Open the weekly test from your calendar.",
                        "افتح الاختبار الأسبوعي من التقويم.");
      return;
    }

    const res = await DarbSession.fetch('/api/assessment/status?week=' + this.week);
    if (!res) { this._show('asmt-nosession'); return; }

    let data = {};
    try { data = await res.json(); } catch (e) { data = {}; }

    if (res.status === 403 || data.enabled === false || !data.ok) {
      this._unavailable();
      return;
    }

    this.config = data.config || {};
    this._routeState(data);
  },

  // ---- Monthly Review init -----------------------------------------------

  async _initMonthly() {
    const res = await DarbSession.fetch('/api/assessment/monthly/status');
    if (!res) { this._show('asmt-nosession'); return; }
    let data = {};
    try { data = await res.json(); } catch (e) { data = {}; }

    if (!data.ok || data.state === 'disabled' || data.state === 'not_due') {
      this._unavailable("Monthly review isn't available yet. Keep going!",
                        "المراجعة الشهرية مش متاحة دلوقتي. كمّل تمرين!");
      return;
    }
    if (data.state === 'passed') {
      this._show('asmt-mastered');
      document.getElementById('asmt-mastered').querySelector('h2').innerHTML =
        '🌟 Monthly Review Passed! <span class="ar-inline" lang="ar" dir="rtl">/ المراجعة الشهرية ناجحة!</span>';
      return;
    }
    if (data.state === 'cooldown') {
      let when = '';
      try { const t = new Date(data.cooldown_until); if (!isNaN(t)) when = t.toLocaleString(); } catch (e) {}
      document.getElementById('asmt-cooldown-msg').innerHTML =
        `You can retake the monthly review soon${when ? ` (after ${this._esc(when)})` : ''}. ` +
        `<span class="ar-inline" lang="ar" dir="rtl">/ تقدر تعيد المراجعة قريب.</span>`;
      this._show('asmt-cooldown');
      return;
    }

    // available
    this.config = { time_limit_min: 20 };
    this._showMonthlyIntro();
  },

  _showMonthlyIntro() {
    document.getElementById('asmt-intro-title').textContent = '📊 Monthly Progress Review';
    document.getElementById('asmt-rule-time').textContent = 'About 20 minutes';
    this._show('asmt-intro');
    const btn = document.getElementById('asmt-start-btn');
    btn.onclick = () => this._startMonthlyAttempt();
  },

  async _startMonthlyAttempt() {
    const btn = document.getElementById('asmt-start-btn');
    btn.disabled = true; btn.textContent = 'Starting...';
    const res = await DarbSession.fetch('/api/assessment/monthly/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    if (!res) { this._show('asmt-nosession'); return; }
    let data = {};
    try { data = await res.json(); } catch (e) { data = {}; }
    if (!data.ok) {
      btn.disabled = false; btn.textContent = '🚀 Start';
      this._unavailable("Monthly review isn't available right now.",
                        "المراجعة مش متاحة دلوقتي.");
      return;
    }
    this.attempt = { attempt_id: data.attempt_id, items: data.items || [],
                     time_limit_min: data.time_limit_min || 20 };
    this.answers = {};
    this.idx = 0;
    this.remaining = (data.time_limit_min || 20) * 60;
    this._monthlyApiPrefix = '/api/assessment/monthly';
    this._enterRunner();
  },

  // ---- Advancement Exam init ---------------------------------------------

  async _initAdvancement() {
    const res = await DarbSession.fetch('/api/assessment/advancement/status');
    if (!res) { this._show('asmt-nosession'); return; }
    let data = {};
    try { data = await res.json(); } catch (e) { data = {}; }

    if (!data.ok || data.state === 'disabled' || data.state === 'locked') {
      this._unavailable("Advancement exam isn't available yet. Complete all weekly tests + a monthly review first.",
                        "اختبار الترقية مش متاح — خلّص كل الاختبارات الأسبوعية + مراجعة شهرية الأول.");
      return;
    }
    if (data.state === 'passed') {
      this._show('asmt-mastered');
      document.getElementById('asmt-mastered').querySelector('h2').innerHTML =
        '🎓 Level Advanced! <span class="ar-inline" lang="ar" dir="rtl">/ اترقّيت!</span>';
      return;
    }
    if (data.state === 'cooldown') {
      let when = '';
      try { const t = new Date(data.cooldown_until); if (!isNaN(t)) when = t.toLocaleString(); } catch (e) {}
      document.getElementById('asmt-cooldown-msg').innerHTML =
        `You can retake the advancement exam soon${when ? ` (after ${this._esc(when)})` : ''}. ` +
        `<span class="ar-inline" lang="ar" dir="rtl">/ تقدر تعيد اختبار الترقية قريب.</span>`;
      this._show('asmt-cooldown');
      return;
    }

    // available
    this.config = { time_limit_min: 20 };
    this._showAdvancementIntro();
  },

  _showAdvancementIntro() {
    document.getElementById('asmt-intro-title').textContent = '🎓 Level Advancement Exam';
    document.getElementById('asmt-rule-time').textContent = 'Part A: ~20 min + Part B: ~10 min';
    this._show('asmt-intro');
    const btn = document.getElementById('asmt-start-btn');
    btn.onclick = () => this._startAdvancementAttempt();
  },

  async _startAdvancementAttempt() {
    const btn = document.getElementById('asmt-start-btn');
    btn.disabled = true; btn.textContent = 'Starting...';
    const res = await DarbSession.fetch('/api/assessment/advancement/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    if (!res) { this._show('asmt-nosession'); return; }
    let data = {};
    try { data = await res.json(); } catch (e) { data = {}; }
    if (!data.ok) {
      btn.disabled = false; btn.textContent = '🚀 Start';
      this._unavailable("Advancement exam isn't available right now.",
                        "اختبار الترقية مش متاح دلوقتي.");
      return;
    }
    this.attempt = { attempt_id: data.attempt_id, items: data.items || [],
                     time_limit_min: data.time_limit_min || 20 };
    this.answers = {};
    this.idx = 0;
    this.remaining = (data.time_limit_min || 20) * 60;
    this._advancementMode = true;
    this._enterRunner();
  },

  _unavailable(en, ar) {
    if (en) {
      document.getElementById('asmt-unavailable-msg').innerHTML =
        this._esc(en) + (ar ? ` <span class="ar-inline" lang="ar" dir="rtl">/ ${this._esc(ar)}</span>` : '');
    }
    this._show('asmt-unavailable');
  },

  _routeState(data) {
    switch (data.state) {
      case 'locked': {
        const n = (data.days_remaining || []).length || 7;
        document.getElementById('asmt-locked-msg').innerHTML =
          `Finish every day of week ${this.week} at least once to unlock this test — ` +
          `<strong>${n} day${n > 1 ? 's' : ''} left</strong>.` +
          ` <span class="ar-inline" lang="ar" dir="rtl">/ خلّص كل أيام الأسبوع ${this.week} مرة على الأقل علشان يفتح — فاضل ${n} يوم.</span>`;
        this._show('asmt-locked');
        break;
      }
      case 'cooldown': {
        let when = '';
        try {
          const t = new Date(data.cooldown_until);
          if (!isNaN(t)) when = t.toLocaleString();
        } catch (e) {}
        document.getElementById('asmt-cooldown-msg').innerHTML =
          `You can retake this week's test soon${when ? ` (after ${this._esc(when)})` : ''}. ` +
          `Review this week's days meanwhile.` +
          ` <span class="ar-inline" lang="ar" dir="rtl">/ تقدر تعيد الاختبار قريّب. راجع أيام الأسبوع لحد ما يفتح.</span>`;
        this._show('asmt-cooldown');
        break;
      }
      case 'mastered':
        this._show('asmt-mastered');
        break;
      case 'in_progress':
        this._resumeInProgress(data.attempt_id);
        break;
      case 'available':
      case 'not_yet':
      default:
        this._showIntro();
        break;
    }
  },

  _showIntro() {
    document.getElementById('asmt-intro-title').textContent = `Week ${this.week} — Assessment`;
    const mins = (this.config && this.config.time_limit_min) || 15;
    document.getElementById('asmt-rule-time').textContent = `About ${mins} minutes`;
    this._show('asmt-intro');
    const btn = document.getElementById('asmt-start-btn');
    btn.onclick = () => this._startAttempt();
  },

  // ---- resume an interrupted attempt -------------------------------------

  _resumeInProgress(attemptId) {
    const saved = this._loadProgress(attemptId);
    if (saved && saved.items && saved.items.length) {
      // Same-device resume: restore items, answered set, and remaining time.
      this.attempt = { attempt_id: attemptId, items: saved.items,
                       time_limit_min: saved.time_limit_min };
      this.answers = saved.answers || {};
      const limitSec = (saved.time_limit_min || 15) * 60;
      const elapsed = Math.floor((Date.now() - (saved.startedAtMs || Date.now())) / 1000);
      this.remaining = Math.max(0, limitSec - elapsed);
      // Jump to the first not-yet-answered item.
      this.idx = this.attempt.items.findIndex(it => !this.answers[it.item_no]);
      if (this.idx < 0) { this._finish(false); return; }
      if (this.remaining <= 0) { this._finish(true); return; }
      this._enterRunner();
    } else {
      // Can't restore locally (other device / cleared storage). Offer to
      // submit what's on the server so the student is never stuck.
      this._show('asmt-resume');
      document.getElementById('asmt-resume-finish').onclick = () => {
        this.attempt = { attempt_id: attemptId };
        this._finish(false);
      };
    }
  },

  // ---- start -------------------------------------------------------------

  async _startAttempt() {
    const btn = document.getElementById('asmt-start-btn');
    btn.disabled = true; btn.textContent = 'Starting...';
    const res = await DarbSession.fetch('/api/assessment/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ week: this.week }),
    });
    if (!res) { this._show('asmt-nosession'); return; }
    let data = {};
    try { data = await res.json(); } catch (e) { data = {}; }

    if (!data.ok) {
      // A state changed under us (locked / cooldown / mastered / in progress).
      if (data.error === 'already_mastered') { this._show('asmt-mastered'); return; }
      if (data.error === 'attempt_in_progress' && data.attempt_id) {
        this._resumeInProgress(data.attempt_id); return;
      }
      btn.disabled = false; btn.innerHTML = '🚀 Start <span class="ar-inline" lang="ar" dir="rtl">/ ابدأ</span>';
      this._unavailable("This test isn't available right now. Back to the calendar.",
                        "الاختبار مش متاح دلوقتي. ارجع للتقويم.");
      return;
    }

    this.attempt = { attempt_id: data.attempt_id, items: data.items || [],
                     time_limit_min: data.time_limit_min || 15 };
    this.answers = {};
    this.idx = 0;
    this.remaining = (data.time_limit_min || 15) * 60;
    this._saveProgress(Date.now());
    this._enterRunner();
  },

  _enterRunner() {
    this.finishing = false;
    this._armAntiCheat();
    this._show('asmt-runner');
    this._startTimer();
    this._renderItem();
  },

  // ---- item rendering ----------------------------------------------------

  _renderItem() {
    const item = this.attempt.items[this.idx];
    if (!item) { this._finish(false); return; }

    this.blob = null;
    this.recording = false;
    document.getElementById('asmt-item-msg').textContent = '';

    const total = this.attempt.items.length;
    document.getElementById('asmt-progress').textContent = `${this.idx + 1} / ${total}`;
    const pct = Math.round((this.idx / total) * 100);
    document.getElementById('asmt-progressfill').style.width = pct + '%';

    const el = document.getElementById('asmt-item');
    const p = item.payload || {};
    let html = `<div class="asmt-skill-tag">${this._skillLabel(item.skill)}</div>`;

    if (item.skill === 'vocab') {
      html += `
        <p class="asmt-q">Write the English word for: <span class="ar-inline" lang="ar" dir="rtl">/ اكتب الكلمة بالإنجليزي:</span></p>
        <div class="asmt-prompt-big" lang="ar" dir="rtl">${this._esc(p.prompt_ar)}</div>
        <input id="asmt-text" class="asmt-input" type="text" autocomplete="off"
          autocapitalize="off" autocorrect="off" spellcheck="false" placeholder="English word / الكلمة بالإنجليزي">`;
    } else if (item.skill === 'listening') {
      html += `
        <p class="asmt-q">Listen, then type the English word you heard. <span class="ar-inline" lang="ar" dir="rtl">/ اسمع، واكتب الكلمة الإنجليزية اللي سمعتها.</span></p>
        <div style="text-align:center;margin:14px 0">
          <button id="asmt-play" class="btn btn-outline" type="button">🔊 Play <span class="ar-inline" lang="ar" dir="rtl">/ اسمع</span></button>
        </div>
        <input id="asmt-text" class="asmt-input" type="text" autocomplete="off"
          autocapitalize="off" autocorrect="off" spellcheck="false" placeholder="the word you heard / الكلمة اللي سمعتها">`;
    } else if (item.skill === 'pronunciation') {
      html += `
        <p class="asmt-q">Listen, then record yourself saying this word. <span class="ar-inline" lang="ar" dir="rtl">/ اسمع، وبعدين سجّل نفسك بتقولها.</span></p>
        <div class="asmt-prompt-big">${this._esc(p.word)}</div>
        ${p.pronunciation ? `<p class="asmt-pron">${this._esc(p.pronunciation)}</p>` : ''}
        <div style="text-align:center;margin:12px 0">
          <button id="asmt-play" class="btn btn-outline" type="button">🔊 Hear it <span class="ar-inline" lang="ar" dir="rtl">/ اسمعها</span></button>
        </div>
        ${this._recorderHtml()}`;
    } else if (item.skill === 'speaking') {
      html += `
        <p class="asmt-q" lang="ar" dir="rtl">${this._esc(p.prompt_ar || '')}</p>
        <p class="asmt-q-en">${this._esc(p.prompt_en || '')}</p>
        ${this._targetWordsHtml(p.target_words)}
        ${this._recorderHtml()}`;
    } else if (item.skill === 'writing') {
      html += `
        <p class="asmt-q" lang="ar" dir="rtl">${this._esc(p.prompt_ar || '')}</p>
        <p class="asmt-q-en">${this._esc(p.prompt_en || '')}</p>
        ${this._targetWordsHtml(p.target_words)}
        <textarea id="asmt-text" class="asmt-input asmt-textarea" rows="4" placeholder="Write here... / اكتب هنا..."></textarea>`;
    }
    el.innerHTML = html;

    // Wire audio playback (listening auto-plays once).
    const playBtn = document.getElementById('asmt-play');
    if (item.skill === 'listening') {
      const say = () => TTS.speak(p.say_en, 0.8);
      if (playBtn) playBtn.onclick = say;
      setTimeout(say, 350);
    } else if (item.skill === 'pronunciation' && playBtn) {
      playBtn.onclick = () => TTS.speak(p.word, 0.8);
    }

    // Gate "Next": audio items need a recording; text items need a typed answer.
    if (item.skill === 'pronunciation' || item.skill === 'speaking') {
      this._wireRecorder();
      this._setNextEnabled(false); // require a recording first
    } else {
      const input = document.getElementById('asmt-text');
      const sync = () => this._setNextEnabled(!!(input && input.value.trim()));
      if (input) input.addEventListener('input', sync);
      sync(); // start disabled until they type something
    }

    // Last item → change the button label.
    const nextBtn = document.getElementById('asmt-next-btn');
    const last = this.idx === this.attempt.items.length - 1;
    nextBtn.innerHTML = last
      ? 'Finish <span class="ar-inline" lang="ar" dir="rtl">/ إنهاء</span>'
      : 'Next <span class="ar-inline" lang="ar" dir="rtl">/ التالي</span>';
    nextBtn.onclick = () => this._submitAndAdvance();
  },

  _skillLabel(skill) {
    const m = {
      vocab: '📖 Vocabulary', listening: '👂 Listening',
      pronunciation: '🗣️ Pronunciation', speaking: '💬 Speaking', writing: '✍️ Writing',
    };
    return m[skill] || skill;
  },

  _targetWordsHtml(words) {
    if (!words || !words.length) return '';
    const chips = words.map(w => `<span class="asmt-chip">${this._esc(w)}</span>`).join('');
    return `<div class="asmt-targets"><span class="asmt-targets-label">Try to use: <span class="ar-inline" lang="ar" dir="rtl">/ حاول تستخدم:</span></span>${chips}</div>`;
  },

  _recorderHtml() {
    return `
      <div class="asmt-recorder">
        <button id="asmt-rec-btn" class="btn btn-danger" type="button">🎙️ Record <span class="ar-inline" lang="ar" dir="rtl">/ سجّل</span></button>
        <span id="asmt-rec-timer" class="asmt-rec-timer" style="display:none">0:00</span>
        <audio id="asmt-rec-playback" controls style="display:none;margin-top:10px;width:100%"></audio>
        <p id="asmt-rec-hint" class="asmt-rec-hint">Tap record and speak. You can re-record. <span class="ar-inline" lang="ar" dir="rtl">/ اضغط سجّل واتكلّم. تقدر تعيد التسجيل.</span></p>
      </div>`;
  },

  _wireRecorder() {
    const btn = document.getElementById('asmt-rec-btn');
    const timer = document.getElementById('asmt-rec-timer');
    if (!btn) return;
    btn.onclick = async () => {
      if (!this.recording) {
        this.recording = true;
        btn.innerHTML = '⏹️ Stop <span class="ar-inline" lang="ar" dir="rtl">/ إيقاف</span>';
        if (timer) { timer.style.display = ''; timer.textContent = '0:00'; }
        await Recorder.start((elapsed) => {
          if (timer) timer.textContent = Timer.formatTime(elapsed);
        });
      } else {
        this.recording = false;
        btn.innerHTML = '🎙️ Re-record <span class="ar-inline" lang="ar" dir="rtl">/ أعِد التسجيل</span>';
        this.blob = await Recorder.stop();
        const pb = document.getElementById('asmt-rec-playback');
        if (this.blob && pb) {
          pb.src = URL.createObjectURL(this.blob);
          pb.style.display = '';
        }
        if (this.blob) this._setNextEnabled(true);
      }
    };
  },

  _setNextEnabled(on) {
    const btn = document.getElementById('asmt-next-btn');
    if (btn) btn.disabled = !on;
  },

  // ---- submit + advance --------------------------------------------------

  async _submitAndAdvance() {
    if (this.recording) {  // stop an in-flight recording before submitting
      const btn = document.getElementById('asmt-rec-btn');
      if (btn) btn.click();
      await new Promise(r => setTimeout(r, 250));
    }
    const nextBtn = document.getElementById('asmt-next-btn');
    nextBtn.disabled = true;
    const label = nextBtn.innerHTML;
    nextBtn.textContent = 'Saving...';

    const ok = await this._submitCurrent();
    if (!ok) {
      document.getElementById('asmt-item-msg').innerHTML =
        '⚠️ Couldn\'t save that answer — check your connection and try again. <span class="ar-inline" lang="ar" dir="rtl">/ متأثرش، جرّب تاني.</span>';
      nextBtn.disabled = false;
      nextBtn.innerHTML = label;
      return;
    }

    const item = this.attempt.items[this.idx];
    this.answers[item.item_no] = true;
    this._saveProgress();

    this.idx++;
    if (this.idx >= this.attempt.items.length) {
      this._finish(false);
    } else {
      this._renderItem();
    }
  },

  async _submitCurrent() {
    const item = this.attempt.items[this.idx];
    const isAudio = (item.skill === 'pronunciation' || item.skill === 'speaking');
    try {
      let res;
      if (isAudio) {
        const fd = new FormData();
        if (this.blob) {
          const ext = (RecorderUI && RecorderUI._extensionFor)
            ? RecorderUI._extensionFor(this.blob.type) : 'webm';
          fd.append('audio', this.blob, `recording.${ext}`);
        }
        fd.append('attempt_id', String(this.attempt.attempt_id));
        fd.append('item_no', String(item.item_no));
        const itemUrl = this.type === 'monthly' ? '/api/assessment/monthly/item'
                      : this._advancementMode ? '/api/assessment/advancement/item'
                      : '/api/assessment/item';
        res = await DarbSession.fetch(itemUrl, { method: 'POST', body: fd });
      } else {
        const input = document.getElementById('asmt-text');
        const answer = input ? input.value : '';
        const itemUrl = this.type === 'monthly' ? '/api/assessment/monthly/item'
                      : this._advancementMode ? '/api/assessment/advancement/item'
                      : '/api/assessment/item';
        res = await DarbSession.fetch(itemUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ attempt_id: this.attempt.attempt_id, item_no: item.item_no, answer }),
        });
      }
      if (!res) return false;
      const data = await res.json().catch(() => ({}));
      return !!data.ok;
    } catch (e) {
      return false;
    }
  },

  // ---- timer -------------------------------------------------------------

  _startTimer() {
    this._stopTimer();
    this._renderTimer();
    this.timerId = setInterval(() => {
      this.remaining--;
      if (this.remaining <= 0) {
        this.remaining = 0;
        this._renderTimer();
        this.flags.time_expired_client = true;
        this._finish(true);
        return;
      }
      this._renderTimer();
    }, 1000);
  },

  _renderTimer() {
    const el = document.getElementById('asmt-timer');
    if (!el) return;
    el.textContent = Timer.formatTime(Math.max(0, this.remaining));
    el.classList.toggle('asmt-timer-warn', this.remaining <= 60);
  },

  _stopTimer() {
    if (this.timerId) { clearInterval(this.timerId); this.timerId = null; }
  },

  // ---- finish + results --------------------------------------------------

  async _finish(auto) {
    if (this.finishing) return;
    this.finishing = true;
    this._stopTimer();
    if (this.recording) { try { await Recorder.stop(); } catch (e) {} this.recording = false; }
    this._show('asmt-submitting');

    let finishUrl = '/api/assessment/finish';
    if (this.type === 'monthly') finishUrl = '/api/assessment/monthly/finish';
    else if (this._advancementMode) finishUrl = '/api/assessment/advancement/finish-a';

    let data = {};
    try {
      const res = await DarbSession.fetch(finishUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ attempt_id: this.attempt.attempt_id, integrity_flags: this.flags }),
      });
      if (res) data = await res.json().catch(() => ({}));
    } catch (e) {}

    this._clearProgress(this.attempt.attempt_id);

    // An attempt that ran out of time before ANY answer was voided by the
    // server (no score, no penalty, no cooldown). Send the student back to a
    // clean intro with a reassuring note instead of showing a 0% "fail".
    if (data && data.voided) {
      this.finishing = false;
      this.attempt = null; this.answers = {}; this.idx = 0;
      this._showIntro();
      const t = document.getElementById('asmt-intro-title');
      if (t && t.parentNode && !document.getElementById('asmt-intro-note')) {
        const n = document.createElement('p');
        n.id = 'asmt-intro-note';
        n.className = 'asmt-flag-note';
        n.innerHTML = '⏳ Your previous attempt ran out of time before you answered, so we set it aside — no score, no penalty. Take your time and start fresh. <span class="ar-inline" lang="ar" dir="rtl">/ محاولتك السابقة خلص وقتها قبل ما تجاوب، فشِلناها من غير أي خصم. خد وقتك وابدأ من جديد.</span>';
        t.parentNode.insertBefore(n, t.nextSibling);
      }
      return;
    }

    if (!data || !data.ok) {
      this._unavailable("We saved your answers but couldn't show the result. Please check back from your calendar.",
                        "حفظنا إجاباتك بس معرفناش نعرض النتيجة. راجع من التقويم.");
      return;
    }

    // Route to the correct results view based on type
    if (this.type === 'monthly') {
      this._renderMonthlyResults(data);
    } else if (this._advancementMode) {
      this._renderAdvancementPartAResults(data);
    } else {
      this._renderResults(data);
    }
  },

  // ---- Monthly results ---------------------------------------------------

  _renderMonthlyResults(data) {
    const passed = data.result === 'passed';
    const retention = data.retention_pct || 0;
    const breakdown = data.skill_breakdown || {};
    const reviewList = data.review_list || [];

    const seal = passed ? '🌟' : '📊';
    const title = passed ? 'Monthly Review Passed!' : 'Not yet — keep reviewing';
    const titleAr = passed ? 'المراجعة الشهرية ناجحة!' : 'لسه — كمّل مراجعة';

    let html = `
      <div class="card asmt-result-hero ${passed ? 'asmt-pass' : 'asmt-notyet'}">
        <div class="asmt-seal">${seal}</div>
        <h2 class="asmt-result-title">${title} <span class="ar-inline" lang="ar" dir="rtl">/ ${titleAr}</span></h2>
        <p class="asmt-result-sub">Retention Score: <strong>${retention}%</strong> ${passed ? '✅' : '(need 65%)'}</p>
      </div>`;

    // Skill breakdown radar
    if (Object.keys(breakdown).length) {
      html += `<div class="card"><h3 style="margin-top:0">📊 Skills <span class="ar-inline" lang="ar" dir="rtl">/ مهاراتك</span></h3>`;
      for (const [skill, score] of Object.entries(breakdown)) {
        const bar = '█'.repeat(Math.round(score / 10)) + '░'.repeat(10 - Math.round(score / 10));
        html += `<div class="asmt-review-row"><span class="asmt-review-skill">${this._skillLabel(skill)}</span> ${bar} ${score}%</div>`;
      }
      html += `</div>`;
    }

    // Review list (weak items)
    if (!passed && reviewList.length) {
      html += `<div class="card"><h3 style="margin-top:0">📝 Review these <span class="ar-inline" lang="ar" dir="rtl">/ راجع دول</span></h3>`;
      reviewList.slice(0, 8).forEach(item => {
        html += `<div class="asmt-review-row">• ${this._esc(item.word)} (Week ${item.source_week}, ${this._skillLabel(item.skill)})</div>`;
      });
      html += `</div>`;
    }

    html += `<div style="text-align:center;margin:8px 0 4px"><a href="/" class="btn">🏠 Home</a></div>`;
    document.getElementById('asmt-results').innerHTML = html;
    this._show('asmt-results');
    window.scrollTo(0, 0);
    if (passed) this._confetti();
  },

  // ---- Advancement Part A results → transition to Part B -----------------

  _renderAdvancementPartAResults(data) {
    if (data.voided) {
      this.finishing = false;
      this._showAdvancementIntro();
      return;
    }

    const perSkill = data.per_skill || {};
    const partAScore = data.part_a_score || 0;
    const skillsMet = data.skill_mins_met;
    const failedSkills = data.failed_skills || [];

    let html = `
      <div class="card asmt-result-hero">
        <div class="asmt-seal">📝</div>
        <h2 class="asmt-result-title">Part A Complete! <span class="ar-inline" lang="ar" dir="rtl">/ الجزء الأول خلص!</span></h2>
        <p class="asmt-result-sub">Part A Score: <strong>${partAScore}%</strong></p>
      </div>`;

    // Per-skill breakdown
    html += `<div class="card"><h3 style="margin-top:0">📊 Per-skill scores</h3>`;
    for (const [skill, score] of Object.entries(perSkill)) {
      const ok = score >= 60;
      const mark = ok ? '✅' : '⚠️';
      html += `<div class="asmt-review-row">${mark} ${this._skillLabel(skill)}: ${score}%</div>`;
    }
    if (failedSkills.length) {
      html += `<p style="color:#e67e22">⚠️ Skills below 60%: ${failedSkills.join(', ')}</p>`;
    }
    html += `</div>`;

    // Part B prompt
    html += `
      <div class="card" style="border-color:var(--accent)">
        <h3 style="margin-top:0">🎙️ Part B — Record Yourself <span class="ar-inline" lang="ar" dir="rtl">/ الجزء التاني — سجّل نفسك</span></h3>
        <p>Now record yourself speaking freely for 60 seconds:</p>
        <p lang="ar" dir="rtl" style="font-size:1.1em"><strong>عرّف نفسك بالإنجليزي: اسمك، من فين، بتشتغل إيه، وليه بتتعلم إنجليزي.</strong></p>
        <p><em>Introduce yourself in English: your name, where you're from, what you do, and why you're learning English.</em></p>
        <p>⏱️ You have 60 seconds. Take a moment to think, then press Record.</p>
        ${this._recorderHtml()}
        <button id="asmt-partb-submit" class="btn" style="margin-top:12px" disabled>
          Submit Part B <span class="ar-inline" lang="ar" dir="rtl">/ أرسل الجزء التاني</span>
        </button>
      </div>`;

    document.getElementById('asmt-results').innerHTML = html;
    this._show('asmt-results');
    window.scrollTo(0, 0);

    // Wire Part B recorder
    this._wireRecorder();
    const submitBtn = document.getElementById('asmt-partb-submit');
    const recBtn = document.getElementById('asmt-rec-btn');
    if (recBtn) {
      const origOnclick = recBtn.onclick;
      recBtn.onclick = async () => {
        if (!this.recording) {
          this.recording = true;
          recBtn.innerHTML = '⏹️ Stop <span class="ar-inline" lang="ar" dir="rtl">/ إيقاف</span>';
          await Recorder.start();
        } else {
          this.recording = false;
          recBtn.innerHTML = '🎙️ Re-record <span class="ar-inline" lang="ar" dir="rtl">/ أعِد</span>';
          this.blob = await Recorder.stop();
          const pb = document.getElementById('asmt-rec-playback');
          if (this.blob && pb) { pb.src = URL.createObjectURL(this.blob); pb.style.display = ''; }
          if (this.blob && submitBtn) submitBtn.disabled = false;
        }
      };
    }

    if (submitBtn) {
      submitBtn.onclick = () => this._submitPartB();
    }
  },

  async _submitPartB() {
    const btn = document.getElementById('asmt-partb-submit');
    if (btn) { btn.disabled = true; btn.textContent = 'Submitting...'; }

    // Transcribe via Whisper (send audio to the server which handles transcription)
    // For now, send the audio to the existing recording submission endpoint,
    // then call finish-b with the transcript. In practice, the server-side
    // submit_item for audio items already transcribes via Whisper.
    // Simpler approach: submit the blob to a dedicated endpoint that transcribes + scores.
    let transcript = '';
    if (this.blob) {
      try {
        const fd = new FormData();
        fd.append('audio', this.blob, 'partb.webm');
        fd.append('attempt_id', String(this.attempt.attempt_id));
        fd.append('item_no', '0');  // Part B marker
        const res = await DarbSession.fetch('/api/assessment/item', { method: 'POST', body: fd });
        if (res) {
          const d = await res.json().catch(() => ({}));
          transcript = d.transcript || d.answer || '';
        }
      } catch (e) {}
    }

    // If we couldn't get a transcript from the audio endpoint, use a fallback
    // (the server's finish-b will handle empty transcripts gracefully)
    if (!transcript && this.blob) {
      transcript = '[audio_submitted]';
    }

    // Call finish-b with the transcript
    let data = {};
    try {
      const res = await DarbSession.fetch('/api/assessment/advancement/finish-b', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ attempt_id: this.attempt.attempt_id, transcript }),
      });
      if (res) data = await res.json().catch(() => ({}));
    } catch (e) {}

    if (!data.ok) {
      if (btn) { btn.disabled = false; btn.textContent = 'Submit Part B'; }
      return;
    }

    this._renderAdvancementFinalResults(data);
  },

  _renderAdvancementFinalResults(data) {
    // Mi'yar CEFR exit exam: verdict is pass / fail / review. `decision` is the
    // authoritative field; `passed` stays for backward compatibility.
    const decision = data.decision || (data.passed ? 'pass' : 'fail');
    const passed = decision === 'pass';
    const review = decision === 'review';
    const distinction = passed && data.distinction;
    const overall = data.overall_pct || 0;
    const partA = data.part_a_score || 0;
    const partB = data.part_b_score || 0;
    const partBDetail = data.part_b_detail || {};
    const perSkill = data.per_skill || {};

    // A boundary/low-confidence result is NOT decided by the machine — a human
    // teacher reviews it. Show honest "under review" limbo, never a fake fail.
    let seal, title, titleAr, heroClass;
    if (review) {
      seal = '📋';
      title = 'Under review';
      titleAr = 'تحت المراجعة';
      heroClass = 'asmt-notyet';
    } else if (passed) {
      seal = '🎓';
      title = distinction ? 'PROMOTED — with distinction!' : 'PROMOTED!';
      titleAr = distinction ? 'مبروك! اترقّيت بامتياز!' : 'مبروك! اترقّيت!';
      heroClass = distinction ? 'asmt-pass asmt-distinction' : 'asmt-pass';
    } else {
      seal = '💪';
      title = 'Not yet — you\'re close';
      titleAr = 'لسه — قربت!';
      heroClass = 'asmt-notyet';
    }

    let html = `
      <div class="card asmt-result-hero ${heroClass}">
        <div class="asmt-seal">${seal}</div>
        <h2 class="asmt-result-title">${title} <span class="ar-inline" lang="ar" dir="rtl">/ ${titleAr}</span></h2>
        <p class="asmt-result-sub">Part A: ${partA}% | Part B: ${partB}/100</p>
      </div>`;

    if (review) {
      html += `<div class="card"><p>📋 Your result was close to the boundary, so a
        human teacher will review your speaking &amp; writing before the final decision.
        We'll message you on Discord soon — your daily progress is safe.</p>
        <p class="ar-inline" lang="ar" dir="rtl">نتيجتك قريبة من الحد الفاصل، فمُدرّس بشري
        هيراجع أداءك في المحادثة والكتابة قبل القرار النهائي. هنبلّغك على ديسكورد قريب —
        وتقدّمك اليومي في أمان.</p></div>`;
    }

    // Part B breakdown
    if (partBDetail.fluency !== undefined) {
      html += `<div class="card"><h3 style="margin-top:0">🎙️ Part B Breakdown</h3>
        <div class="asmt-review-row">Fluency: ${partBDetail.fluency}/25</div>
        <div class="asmt-review-row">Accuracy: ${partBDetail.accuracy}/25</div>
        <div class="asmt-review-row">Vocabulary: ${partBDetail.vocab_range}/25</div>
        <div class="asmt-review-row">Pronunciation: ${partBDetail.pronunciation}/25</div>
        <p><em>${this._esc(partBDetail.feedback || '')}</em></p>
      </div>`;
    }

    // Per-skill (Part A)
    if (Object.keys(perSkill).length) {
      html += `<div class="card"><h3 style="margin-top:0">📊 Part A Skills</h3>`;
      for (const [skill, score] of Object.entries(perSkill)) {
        const ok = score >= 60;
        html += `<div class="asmt-review-row">${ok ? '✅' : '⚠️'} ${this._skillLabel(skill)}: ${score}%</div>`;
      }
      html += `</div>`;
    }

    // Honest "target to reach" on a not-yet (exit exam is criterion-referenced:
    // fixed cut scores, not a curve). Legacy reason_if_failed still supported.
    if (data.reason_if_failed) {
      html += `<div class="card"><p>📝 ${this._esc(data.reason_if_failed)}</p></div>`;
    } else if (!passed && !review && data.cut) {
      html += `<div class="card"><p>🎯 To pass ${this._esc(data.level || '')}: Part A
        ≥ ${data.cut.part_a_pct}% and Part B ≥ ${data.cut.part_b_min}/100.
        Keep practising and retake soon. <span class="ar-inline" lang="ar" dir="rtl">/
        عشان تعدّي: Part A ≥ ${data.cut.part_a_pct}% و Part B ≥ ${data.cut.part_b_min}.
        كمّل تمرين وأعِد قريب.</span></p></div>`;
    }

    // Certificate link on a pass.
    if (passed) {
      html += `<div class="card" style="text-align:center"><p>📜 Your CEFR-aligned
        certificate is ready.</p>
        <a href="/assessment/certificate/" class="btn">📜 View certificate / شهادتك</a></div>`;
    }

    html += `<div style="text-align:center;margin:8px 0 4px"><a href="/" class="btn">🏠 Home</a></div>`;
    document.getElementById('asmt-results').innerHTML = html;
    this._show('asmt-results');
    window.scrollTo(0, 0);
    if (passed) this._confetti();
  },

  _renderResults(data) {
    const v = data.verdict || {};
    const items = data.items || [];
    const el = document.getElementById('asmt-results');
    const passed = v.result === 'mastered';
    const dist = passed && v.distinction;

    // A flagged attempt is always a not-yet now — add a gentle, hopeful note
    // (no more blank "being reviewed" limbo; the student always sees a result).
    let flagNote = '';
    if (v.status === 'flagged') {
      flagNote = (v.flag_reason === 'ai_error')
        ? `<p class="asmt-flag-note">🧑‍🏫 Your recorded answers are being double-checked by your teacher — your result may improve. <span class="ar-inline" lang="ar" dir="rtl">/ تسجيلاتك بيراجعها المعلّم، ونتيجتك ممكن تتحسّن.</span></p>`
        : `<p class="asmt-flag-note">🧑‍🏫 So close! Your teacher will take a look — you might just make it. <span class="ar-inline" lang="ar" dir="rtl">/ قربت جدًا! المعلّم هيبص على نتيجتك.</span></p>`;
    }

    const seal = dist ? '⭐🏅' : (passed ? '🏅' : '💪');
    const title = dist ? 'Distinction!' : (passed ? 'Week Mastered!' : "Not yet — you're close");
    const titleAr = dist ? 'امتياز!' : (passed ? 'أتقنت الأسبوع!' : 'لسه — قربت');
    const sub = passed
      ? `You passed Week ${this.week}. ${dist ? 'Outstanding work!' : 'Great work!'}`
      : `Review the notes below, then try again after a short break. Your daily progress is safe.`;
    const subAr = passed
      ? `عدّيت اختبار الأسبوع ${this.week}. ${dist ? 'مستوى ممتاز!' : 'شغل رائع!'}`
      : `راجع الملاحظات تحت وأعِد بعد شوية. تقدّمك اليومي في أمان.`;

    let html = `
      <div class="card asmt-result-hero ${passed ? 'asmt-pass' : 'asmt-notyet'}${dist ? ' asmt-distinction' : ''}">
        <div class="asmt-seal">${seal}</div>
        <h2 class="asmt-result-title">${title} <span class="ar-inline" lang="ar" dir="rtl">/ ${titleAr}</span></h2>
        <p class="asmt-result-sub">${sub} <span class="ar-inline" lang="ar" dir="rtl">/ ${subAr}</span></p>
        ${flagNote}
        ${this._scoresHtml(v)}
      </div>`;

    // Per-item review (always shown now — students always get their feedback).
    if (items.length) {
      html += `<div class="card"><h3 style="margin-top:0">📋 Review <span class="ar-inline" lang="ar" dir="rtl">/ المراجعة</span></h3><div class="asmt-review">`;
      items.forEach(it => {
        const ok = it.correct === 1 || it.correct === true;
        const mark = ok ? '<span class="asmt-ok">✓</span>' : '<span class="asmt-bad">✗</span>';
        let detail = it.feedback ? this._esc(it.feedback) : (ok ? 'Correct!' : '');
        if (!ok && it.expected) {
          detail = `Correct answer: <bdi class="asmt-ans">${this._esc(it.expected)}</bdi>` + (it.feedback ? ` — ${this._esc(it.feedback)}` : '');
        }
        html += `
          <div class="asmt-review-row">
            ${mark}
            <div><span class="asmt-review-skill">${this._skillLabel(it.skill)}</span>
            ${detail ? `<div class="asmt-review-detail">${detail}</div>` : ''}</div>
          </div>`;
      });
      html += `</div></div>`;
    }

    html += `<div style="text-align:center;margin:8px 0 4px">
      <a href="/" class="btn">🏠 Home <span class="ar-inline" lang="ar" dir="rtl">/ الرئيسية</span></a>
    </div>`;

    el.innerHTML = html;
    this._show('asmt-results');
    window.scrollTo(0, 0);
    requestAnimationFrame(() => this._animateScores(v));
    if (passed) this._confetti();
  },

  _scoresHtml(v) {
    const mp = (this.config && this.config.mastery_pass_pct) || 70;
    const cp = (this.config && this.config.consistency_pass_pct) || 70;
    const ring = (id, label, ar) => `
      <div class="asmt-ring" id="${id}">
        <div class="asmt-ring-face"><span class="asmt-ring-num">0%</span></div>
        <div class="asmt-ring-label">${label}<br><span class="ar-inline" lang="ar" dir="rtl">${ar}</span></div>
      </div>`;
    return `<div class="asmt-rings" data-mp="${mp}" data-cp="${cp}">
      ${ring('ring-mastery', 'Mastery', 'الإتقان')}
      ${ring('ring-consistency', 'Consistency', 'الالتزام')}
    </div>`;
  },

  /** Count-up + fill the two circular score rings (conic-gradient). */
  _animateScores(v) {
    const mp = (this.config && this.config.mastery_pass_pct) || 70;
    const cp = (this.config && this.config.consistency_pass_pct) || 70;
    this._animateRing('ring-mastery', Math.round(v.mastery_pct || 0), (v.mastery_pct || 0) >= mp);
    this._animateRing('ring-consistency', Math.round(v.consistency_pct || 0), (v.consistency_pct || 0) >= cp);
  },

  _animateRing(id, target, pass) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.add(pass ? 'ring-pass' : 'ring-low');
    const num = el.querySelector('.asmt-ring-num');
    const color = pass ? 'var(--success)' : '#e67e22';
    let cur = 0;
    const step = Math.max(1, Math.round(target / 24));
    const tick = () => {
      cur = Math.min(target, cur + step);
      el.style.background = `conic-gradient(${color} ${cur}%, var(--bg-primary) 0)`;
      if (num) num.textContent = cur + '%';
      if (cur < target) requestAnimationFrame(tick);
    };
    tick();
  },

  /** Lightweight confetti burst on a pass. */
  _confetti() {
    const colors = ['#D4AF37', '#2ecc71', '#3498db', '#e67e22', '#e74c3c'];
    const wrap = document.createElement('div');
    wrap.className = 'asmt-confetti';
    for (let i = 0; i < 40; i++) {
      const s = document.createElement('span');
      s.style.left = Math.random() * 100 + '%';
      s.style.background = colors[i % colors.length];
      s.style.animationDelay = (Math.random() * 0.6) + 's';
      wrap.appendChild(s);
    }
    document.body.appendChild(wrap);
    setTimeout(() => wrap.remove(), 4200);
  },

  // ---- anti-cheat (client signal only; server enforces the real rules) ---

  _armAntiCheat() {
    if (this._antiCheatArmed) return;
    this._antiCheatArmed = true;

    document.addEventListener('visibilitychange', () => {
      if (document.hidden && !this.finishing && this.attempt) this.flags.tab_aways++;
    });
    window.addEventListener('blur', () => {
      if (!this.finishing && this.attempt) this.flags.blur_events++;
    });

    const runner = document.getElementById('asmt-runner');
    if (runner) {
      ['copy', 'cut', 'paste'].forEach(evt => {
        runner.addEventListener(evt, (e) => {
          e.preventDefault();
          if (evt === 'paste') this.flags.paste_blocked++;
        });
      });
      runner.addEventListener('contextmenu', (e) => e.preventDefault());
    }
  },

  // ---- localStorage resume (same-device) ---------------------------------

  _key(attemptId) { return 'itqan_attempt_' + attemptId; },

  _saveProgress(startedAtMs) {
    try {
      const key = this._key(this.attempt.attempt_id);
      let startedAt = startedAtMs;
      if (!startedAt) {
        const prev = this._loadProgress(this.attempt.attempt_id);
        startedAt = (prev && prev.startedAtMs) || Date.now();
      }
      localStorage.setItem(key, JSON.stringify({
        week: this.week,
        items: this.attempt.items,
        time_limit_min: this.attempt.time_limit_min,
        answers: this.answers,
        startedAtMs: startedAt,
      }));
    } catch (e) {}
  },

  _loadProgress(attemptId) {
    try {
      const raw = localStorage.getItem(this._key(attemptId));
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  },

  _clearProgress(attemptId) {
    try { localStorage.removeItem(this._key(attemptId)); } catch (e) {}
  },
};

document.addEventListener('DOMContentLoaded', () => ItqanAssessment.init());
