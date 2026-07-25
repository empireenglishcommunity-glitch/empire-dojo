/**
 * Empire English — System Status / Maintenance banner.
 *
 * Self-contained (no dependency on app.js/darb.js) so it can run on EVERY
 * page: homepage, exercise pages, gate, and guide. On load it asks the bot
 * API for the system status and, if maintenance is active, shows either a
 * dismissible top banner (soft) or a full-screen overlay (hard) — bilingual,
 * with the ETA and a "your progress is safe" reassurance.
 *
 * Design principle: FAIL-OPEN. Any network/parse error → show nothing, so a
 * status outage can never trap a student behind a false maintenance screen.
 * The fetch is no-store (never cached) so toggling maintenance is instant.
 */
(function () {
  var API_BASE = 'https://bot.empireenglish.online';

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Optional reason on its OWN line so it never mixes direction with the
  // bilingual copy. Note: no time/ETA is shown by default — we never promise
  // a duration (maintenance "might take minutes, maybe longer").
  function reasonLine(s) {
    var reason = s.message || s.reason || '';
    if (!reason) return '';
    return '<div class="maint-reason" dir="auto">' + esc(reason) + '</div>';
  }

  function renderSoft(s) {
    if (document.getElementById('maint-banner')) return;
    var bar = document.createElement('div');
    bar.id = 'maint-banner';
    bar.className = 'maint-banner';
    // Each language is a SEPARATE block with its own dir → no bidi jumble.
    bar.innerHTML =
      '<div class="maint-banner-text">' +
        '<div class="maint-line" dir="ltr" lang="en">🔧 We\'re improving the platform — you can keep practicing. Your progress is safe.</div>' +
        '<div class="maint-line" dir="rtl" lang="ar">🔧 بنطوّر المنصة دلوقتي — كمّل تمرينك عادي، وتقدّمك محفوظ.</div>' +
        reasonLine(s) +
      '</div>' +
      '<button class="maint-close" aria-label="Dismiss" onclick="this.parentNode.remove()">✕</button>';
    document.body.appendChild(bar);
    document.body.classList.add('has-maint-banner');
  }

  function renderHard(s) {
    if (document.getElementById('maint-overlay')) return;
    var ov = document.createElement('div');
    ov.id = 'maint-overlay';
    ov.className = 'maint-overlay';
    // English block and Arabic block are fully separate (own dir) — clean,
    // no bidi mixing. No countdown / no promised time; a calm "check back
    // shortly" instead.
    ov.innerHTML =
      '<div class="maint-card">' +
        '<div class="maint-emoji">🔧</div>' +
        '<div class="maint-en" dir="ltr" lang="en">' +
          '<h1>We\'ll be back shortly</h1>' +
          '<p class="maint-sub">Empire English is getting a quick upgrade. Please check back a little later.</p>' +
        '</div>' +
        '<div class="maint-ar" dir="rtl" lang="ar">' +
          '<h2>هنرجع قريب</h2>' +
          '<p>إمباير إنجلش بيتحسّن دلوقتي. من فضلك ارجع بعد شوية.</p>' +
        '</div>' +
        reasonLine(s) +
        '<div class="maint-safe">' +
          '<div dir="ltr" lang="en">🔒 Your streak &amp; progress are 100% safe.</div>' +
          '<div dir="rtl" lang="ar">🔒 تقدّمك وسلسلة أيامك محفوظة بالكامل.</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(ov);
    document.body.classList.add('has-maint-overlay');
  }

  function apply(status) {
    if (!status || status.state !== 'maintenance') return;
    if (status.level === 'hard') renderHard(status);
    else renderSoft(status);
  }

  function check() {
    try {
      fetch(API_BASE + '/api/status', { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (s) { if (s) apply(s); })
        .catch(function () { /* fail-open: show nothing */ });
    } catch (e) { /* fail-open */ }
  }

  // ---- "✨ What's New" one-time toast ------------------------------------
  // Shows the latest changelog entry once per student. On the very first
  // visit we silently baseline to the current latest (so we never dump the
  // whole history at a returning student) — only genuinely NEW entries after
  // that trigger the toast. Fail-open: any error shows nothing.
  var SEEN_KEY = 'empire_whatsnew_seen';

  function showWhatsNew(entry) {
    if (document.getElementById('whatsnew-toast')) return;
    var t = document.createElement('div');
    t.id = 'whatsnew-toast';
    t.className = 'whatsnew-toast';
    t.innerHTML =
      '<div class="whatsnew-head">✨ What\'s New · جديد</div>' +
      '<div class="whatsnew-body" dir="auto">' + esc(entry.text) + '</div>' +
      '<button class="whatsnew-close" aria-label="Dismiss">Got it · تمام</button>';
    document.body.appendChild(t);
    requestAnimationFrame(function () { t.classList.add('whatsnew-in'); });
    function dismiss() {
      try { localStorage.setItem(SEEN_KEY, String(entry.id)); } catch (e) {}
      t.classList.remove('whatsnew-in');
      setTimeout(function () { t.remove(); }, 400);
    }
    t.querySelector('.whatsnew-close').addEventListener('click', dismiss);
  }

  function checkChangelog() {
    try {
      fetch(API_BASE + '/api/changelog', { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (!data || !data.entries || !data.entries.length) return;
          var latest = data.entries[0];
          if (!latest || latest.id == null) return;
          var seen;
          try { seen = localStorage.getItem(SEEN_KEY); } catch (e) { return; }
          if (seen === null || seen === undefined) {
            // First visit ever: baseline silently, don't show history.
            try { localStorage.setItem(SEEN_KEY, String(latest.id)); } catch (e) {}
            return;
          }
          if (String(latest.id) !== String(seen)) showWhatsNew(latest);
        })
        .catch(function () { /* fail-open */ });
    } catch (e) { /* fail-open */ }
  }

  function init() { check(); checkChangelog(); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
