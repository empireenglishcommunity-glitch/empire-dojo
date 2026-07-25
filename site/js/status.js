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

  function etaLine(eta) {
    if (!eta) return '';
    return '<div class="maint-eta">🕒 <b>' + esc(eta) + '</b></div>';
  }

  function renderSoft(s) {
    if (document.getElementById('maint-banner')) return;
    var reason = s.message || s.reason || '';
    var bar = document.createElement('div');
    bar.id = 'maint-banner';
    bar.className = 'maint-banner';
    bar.innerHTML =
      '<div class="maint-banner-text">' +
        '🔧 <b>Updates in progress</b> — you can keep practicing; you may see small glitches. ' +
        '<span dir="rtl" lang="ar">جاري تحديثات بسيطة — كمّل تمرينك عادي، وممكن تشوف خلل بسيط.</span>' +
        (reason ? ' <span class="maint-reason">' + esc(reason) + '</span>' : '') +
        (s.eta ? ' 🕒 ' + esc(s.eta) : '') +
      '</div>' +
      '<button class="maint-close" aria-label="Dismiss" onclick="this.parentNode.remove()">✕</button>';
    document.body.appendChild(bar);
    document.body.classList.add('has-maint-banner');
  }

  function renderHard(s) {
    if (document.getElementById('maint-overlay')) return;
    var reason = s.message || s.reason || '';
    var ov = document.createElement('div');
    ov.id = 'maint-overlay';
    ov.className = 'maint-overlay';
    ov.innerHTML =
      '<div class="maint-card">' +
        '<div class="maint-emoji">🔧</div>' +
        '<h1>We\'re making things better</h1>' +
        '<p class="maint-sub">Empire English is under a quick maintenance. We\'ll be right back.</p>' +
        '<p class="maint-ar" dir="rtl" lang="ar">إمباير إنجلش في صيانة سريعة دلوقتي، وهنرجع حالًا بإذن الله.</p>' +
        (reason ? '<p class="maint-reason">' + esc(reason) + '</p>' : '') +
        etaLine(s.eta) +
        '<div class="maint-safe">🔒 Your streak &amp; progress are 100% safe.' +
          '<br><span dir="rtl" lang="ar">تقدّمك وسلسلة أيامك محفوظة بالكامل.</span></div>' +
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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', check);
  } else {
    check();
  }
})();
