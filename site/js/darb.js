/**
 * Darb (Phase 2) — Personal Calendar + Session Management
 *
 * This module adds:
 *  - DarbSession: manages the signed empire_session token (stored in
 *    localStorage + sent via X-Darb-Session header to bot API)
 *  - DarbCalendar: renders the personal, join-anchored calendar from
 *    /api/calendar data
 *  - DarbExercise: hooks into exercise page "Done" checkboxes to call
 *    /api/practice-complete and show tier feedback
 */

// ============================================================
//  DARB SESSION MANAGEMENT
// ============================================================
const DarbSession = {
  API_BASE: 'https://bot.empireenglish.online',
  _token: null,
  _payload: null,  // decoded from token (client-side, for display only)

  /** Initialize: check for stored session token */
  init() {
    this._token = localStorage.getItem('empire_darb_session');
    if (this._token) {
      this._payload = this._decode(this._token);
      // Validate it hasn't expired client-side (server is final authority)
      if (this._payload && this._payload.exp < Date.now() / 1000) {
        this.clear();
      }
    }
  },

  /** Whether we have a (potentially valid) session */
  hasSession() {
    return !!this._token && !!this._payload;
  },

  /** Get the token string */
  getToken() {
    return this._token;
  },

  /** Get decoded payload fields (did, lvl, sid, iat, exp) */
  getPayload() {
    return this._payload;
  },

  /** Get student's level from session (e.g. "L0") */
  getLevel() {
    return this._payload ? this._payload.lvl : null;
  },

  /** Store a session token (after successful claim) */
  store(token) {
    this._token = token;
    this._payload = this._decode(token);
    localStorage.setItem('empire_darb_session', token);
  },

  /** Clear session */
  clear() {
    this._token = null;
    this._payload = null;
    localStorage.removeItem('empire_darb_session');
  },

  /** Decode the token payload (base64url.sig) — client-side only for display */
  _decode(token) {
    try {
      const [body] = token.split('.');
      const padded = body.replace(/-/g, '+').replace(/_/g, '/');
      const json = atob(padded + '='.repeat((4 - padded.length % 4) % 4));
      return JSON.parse(json);
    } catch (e) {
      return null;
    }
  },

  /** Make an authenticated API call (adds X-Darb-Session header) */
  async fetch(endpoint, options = {}) {
    if (!this._token) return null;
    const url = this.API_BASE + endpoint;
    const headers = {
      ...(options.headers || {}),
      'X-Darb-Session': this._token,
    };
    try {
      const res = await fetch(url, { ...options, headers, credentials: 'include' });
      if (res.status === 401) {
        // Session expired/revoked on server
        this.clear();
        return null;
      }
      return res;
    } catch (e) {
      return null;
    }
  },

  /** Claim a code and store the resulting session */
  async claim(code) {
    try {
      const res = await fetch(this.API_BASE + '/api/claim', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        return { ok: false, error: data.error || 'invalid code' };
      }
      const data = await res.json();
      if (data.ok && data.token) {
        this.store(data.token);
        return { ok: true, level: data.level, name: data.name };
      }
      return { ok: false, error: data.error || 'claim failed' };
    } catch (e) {
      return { ok: false, error: 'network error' };
    }
  },

  /** Validate session is still active on the server */
  async validate() {
    const res = await this.fetch('/api/session-status');
    if (!res) return false;
    try {
      const data = await res.json();
      return data.valid === true;
    } catch (e) {
      return false;
    }
  }
};


// ============================================================
//  DARB CALENDAR RENDERING
// ============================================================
const DarbCalendar = {
  data: null,
  container: null,

  /** Fetch calendar data from the API */
  async load() {
    const res = await DarbSession.fetch('/api/calendar');
    if (!res) return null;
    try {
      const data = await res.json();
      if (data.error) return null;
      this.data = data;
      return data;
    } catch (e) {
      return null;
    }
  },

  /** Render the full calendar into a container element */
  render(containerId) {
    this.container = document.getElementById(containerId);
    if (!this.container || !this.data) return;

    const { days, level, tier_names, level_complete, today_index } = this.data;

    // Group days by week
    const weeks = {};
    days.forEach(d => {
      if (!weeks[d.week]) weeks[d.week] = [];
      weeks[d.week].push(d);
    });

    let html = '';

    // Level complete banner
    if (level_complete) {
      html += `<div class="darb-complete-banner">
        <h2>🎉 Level Complete!</h2>
        <p style="color:var(--text-secondary)">You've completed all days in ${level}. Amazing work!</p>
      </div>`;
    }

    // Legend
    html += `<div class="darb-legend">
      <span><span class="dot dot-today"></span> Today</span>
      <span><span class="dot dot-done"></span> Done</span>
      <span><span class="dot dot-missed"></span> Catch-up</span>
      <span><span class="dot dot-locked"></span> Locked</span>
    </div>`;

    // Render each week
    const weekNums = Object.keys(weeks).map(Number).sort((a, b) => a - b);
    for (const w of weekNums) {
      const weekDays = weeks[w];
      html += `<div class="darb-week-header">
        <h3>Week ${w}</h3>
        <span class="week-line"></span>
      </div>`;
      html += `<div class="darb-calendar">`;
      for (const d of weekDays) {
        const tierName = tier_names[d.day_tier] || 'none';
        const tierClass = tierName !== 'none' ? `tier-${tierName}` : '';
        const stateClass = `state-${d.state}`;
        const dateStr = this._formatDate(d.date);
        const dayLabel = `D${d.day}`;
        const href = d.state !== 'locked'
          ? `/${level.toLowerCase()}/week${d.week}/day${d.day}/`
          : '#';

        html += `<a class="darb-cal-cell ${stateClass} ${tierClass}" 
          href="${href}" 
          data-tier="${d.day_tier}"
          data-week="${d.week}" data-day="${d.day}"
          ${d.state === 'locked' ? `title="Opens ${d.date}"` : ''}>
          <span class="cal-day">${dayLabel}</span>
          <span class="cal-date">${dateStr}</span>
          ${d.day_tier > 0 ? `<span class="tier-badge tier-${tierName}" style="font-size:0.55rem;padding:2px 5px">${tierName}</span>` : ''}
        </a>`;
      }
      html += `</div>`;
    }

    this.container.innerHTML = html;
  },

  /** Format ISO date to short display (e.g. "23 Jul") */
  _formatDate(isoStr) {
    try {
      const d = new Date(isoStr + 'T00:00:00');
      const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      return `${d.getDate()} ${months[d.getMonth()]}`;
    } catch (e) {
      return isoStr;
    }
  }
};


// ============================================================
//  DARB EXERCISE — hooks "Done" into /api/practice-complete
// ============================================================
const DarbExercise = {
  /** Initialize on exercise pages: hook into the Done checkbox */
  init() {
    if (!DarbSession.hasSession()) return;

    // Detect level/week/day/exercise from URL
    const match = window.location.pathname.match(/\/(l\d)\/week(\d+)\/day(\d+)\/(accent|shadowing|listening|vocab)/);
    if (!match) return;

    const [, level, week, day, exercise] = match;
    this._level = level.toUpperCase();
    this._week = parseInt(week);
    this._day = parseInt(day);
    this._exercise = exercise;

    // Hook the checkbox
    const checkbox = document.querySelector('.done-section .checkbox');
    if (checkbox) {
      // Remove existing onchange (Progress.markDone still works via the
      // original attribute; we ADD our server call on top)
      checkbox.addEventListener('change', () => {
        if (checkbox.checked) {
          this._submitCompletion();
        }
      });
    }

    // Check if already completed today (show tier badge)
    this._loadExistingState();
  },

  /** Submit completion to the server */
  async _submitCompletion() {
    const res = await DarbSession.fetch('/api/practice-complete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        exercise: this._exercise === 'shadowing' ? 'shadow' : this._exercise,
        week: this._week,
        day: this._day,
      }),
    });

    if (!res) return;

    try {
      const data = await res.json();
      if (data.ok) {
        this._showTierFeedback(data);
      }
    } catch (e) {
      // Non-fatal — localStorage still works as cache
    }
  },

  /** Show tier feedback after completion */
  _showTierFeedback(data) {
    const doneSection = document.querySelector('.done-section');
    if (!doneSection) return;

    // Remove existing feedback if any
    const existing = doneSection.querySelector('.darb-tier-feedback');
    if (existing) existing.remove();

    const tierNames = { 0:'none', 1:'bronze', 2:'silver', 3:'gold', 4:'platinum', 5:'diamond' };
    const exTierName = tierNames[data.exercise_tier] || 'none';
    const dayTierName = tierNames[data.day_tier] || 'none';

    let msg = '';
    if (data.incremented) {
      msg = `<span class="tier-badge tier-${exTierName}">&#x2B50; ${exTierName}</span>`;
      if (data.day_done) {
        msg += ` <span style="color:var(--success);font-size:0.8rem;margin-left:8px">Day complete!</span>`;
      }
    } else {
      msg = `<span style="color:var(--text-muted);font-size:0.8rem">Already recorded today — come back tomorrow for ${exTierName === 'diamond' ? 'max tier!' : 'next tier'}</span>`;
    }

    const div = document.createElement('div');
    div.className = 'darb-tier-feedback';
    div.style.cssText = 'margin-top:12px;text-align:center';
    div.innerHTML = msg;
    doneSection.appendChild(div);
  },

  /** Load existing mastery state for this exercise (from calendar data) */
  async _loadExistingState() {
    // Quick check via calendar API
    const res = await DarbSession.fetch('/api/calendar');
    if (!res) return;
    try {
      const cal = await res.json();
      if (!cal || !cal.days) return;
      const dayData = cal.days.find(d => d.week === this._week && d.day === this._day);
      if (!dayData) return;

      const exerciseKey = this._exercise === 'shadowing' ? 'shadow' : this._exercise;
      const tier = dayData.exercises[exerciseKey] || 0;
      if (tier > 0) {
        const tierNames = { 1:'bronze', 2:'silver', 3:'gold', 4:'platinum', 5:'diamond' };
        const doneSection = document.querySelector('.done-section');
        if (doneSection && !doneSection.querySelector('.darb-tier-feedback')) {
          const div = document.createElement('div');
          div.className = 'darb-tier-feedback';
          div.style.cssText = 'margin-top:8px;text-align:center';
          div.innerHTML = `<span class="tier-badge tier-${tierNames[tier]}">&#x2B50; ${tierNames[tier]}</span>`;
          doneSection.appendChild(div);
        }
      }
    } catch (e) {
      // Non-fatal
    }
  }
};


// ============================================================
//  DARB RECORDING — Send to Discord (#showcase) + auto-complete
// ============================================================
const DarbRecording = {
  /** Initialize on exercise pages: add "Send to Discord" button */
  init() {
    if (!DarbSession.hasSession()) return;

    // Detect level/week/day/exercise from URL
    const match = window.location.pathname.match(/\/(l\d)\/week(\d+)\/day(\d+)\/(accent|shadowing|listening|vocab)/);
    if (!match) return;

    const [, level, week, day, exercise] = match;
    this._level = level.toUpperCase();
    this._week = parseInt(week);
    this._day = parseInt(day);
    this._exercise = exercise === 'shadowing' ? 'shadow' : exercise;

    // Find the recorder playback section and add "Send to Discord" button
    const playbackSection = document.getElementById('recorder-playback');
    if (playbackSection) {
      this._addSendButton(playbackSection);
    }

    // Also observe for when playback appears (after first recording)
    const observer = new MutationObserver(() => {
      const pb = document.getElementById('recorder-playback');
      if (pb && pb.style.display !== 'none' && !pb.querySelector('.darb-send-btn')) {
        this._addSendButton(pb);
      }
    });
    const recorderCard = document.querySelector('.recorder-card');
    if (recorderCard) {
      observer.observe(recorderCard, { childList: true, subtree: true, attributes: true });
    }
  },

  _addSendButton(container) {
    if (container.querySelector('.darb-send-btn')) return;

    const actionsDiv = container.querySelector('.recorder-actions') || container;
    const btn = document.createElement('button');
    btn.className = 'btn btn-success btn-sm darb-send-btn';
    btn.innerHTML = '📤 Send to Discord <span class="ar-inline" lang="ar" dir="rtl">/ أرسل للديسكورد</span>';
    btn.style.cssText = 'margin-top:8px';
    btn.onclick = () => this._send(btn);
    actionsDiv.appendChild(btn);
  },

  async _send(btn) {
    // Get the recorded blob from RecorderUI
    if (!RecorderUI || !RecorderUI.blob) {
      this._showFeedback('Record first before sending', 'error');
      return;
    }

    btn.disabled = true;
    btn.textContent = 'Sending...';

    const formData = new FormData();
    formData.append('audio', RecorderUI.blob, RecorderUI._extensionFor
      ? `recording.${RecorderUI._extensionFor(RecorderUI.blob.type)}`
      : 'recording.webm');
    formData.append('exercise', this._exercise);
    formData.append('week', this._week.toString());
    formData.append('day', this._day.toString());

    const res = await DarbSession.fetch('/api/submit-recording', {
      method: 'POST',
      body: formData,
    });

    if (!res) {
      btn.disabled = false;
      btn.innerHTML = '📤 Send to Discord <span class="ar-inline" lang="ar" dir="rtl">/ أرسل للديسكورد</span>';
      this._showFeedback('Network error — try again', 'error');
      return;
    }

    try {
      const data = await res.json();
      if (data.ok) {
        btn.innerHTML = '✅ Sent!';
        btn.style.background = 'var(--success)';

        // Auto-check the Done checkbox (visual feedback)
        const checkbox = document.querySelector('.done-section .checkbox');
        if (checkbox && !checkbox.checked) {
          checkbox.checked = true;
          // Also update localStorage for consistency
          if (typeof Progress !== 'undefined') {
            const exType = this._exercise === 'shadow' ? 'shadowing' : this._exercise;
            Progress.markDone(this._level.toLowerCase(), this._week, this._day, exType);
          }
        }

        // Show tier feedback
        const tierNames = { 0:'none', 1:'bronze', 2:'silver', 3:'gold', 4:'platinum', 5:'diamond' };
        const tierName = tierNames[data.exercise_tier] || 'none';
        let msg = `<span class="tier-badge tier-${tierName}">⭐ ${tierName}</span>`;
        if (data.posted) {
          msg += ' <span style="color:var(--success);font-size:0.8rem">Posted to #showcase!</span>';
        }
        if (data.day_done) {
          msg += ' <span style="color:var(--success);font-size:0.8rem;margin-left:4px">Day complete!</span>';
        }
        if (data.already_done) {
          msg = '<span style="color:var(--text-muted);font-size:0.8rem">Already done today — posted to showcase anyway</span>';
        }
        this._showFeedback(msg, 'success');
      } else {
        btn.disabled = false;
        btn.innerHTML = '📤 Send to Discord <span class="ar-inline" lang="ar" dir="rtl">/ أرسل للديسكورد</span>';
        this._showFeedback(data.error || 'Failed to send', 'error');
      }
    } catch (e) {
      btn.disabled = false;
      btn.innerHTML = '📤 Send to Discord <span class="ar-inline" lang="ar" dir="rtl">/ أرسل للديسكورد</span>';
      this._showFeedback('Something went wrong', 'error');
    }
  },

  _showFeedback(html, type) {
    const recorderCard = document.querySelector('.recorder-card');
    if (!recorderCard) return;

    let fb = recorderCard.querySelector('.darb-send-feedback');
    if (!fb) {
      fb = document.createElement('div');
      fb.className = 'darb-send-feedback';
      fb.style.cssText = 'margin-top:12px;text-align:center;padding:8px;border-radius:8px';
      recorderCard.appendChild(fb);
    }

    fb.innerHTML = html;
    fb.style.background = type === 'error' ? 'rgba(231,76,60,0.1)' : 'rgba(46,204,113,0.08)';
  }
};


// ============================================================
//  INITIALIZATION (runs on every page that loads darb.js)
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  DarbSession.init();
  DarbExercise.init();
  DarbRecording.init();
});
