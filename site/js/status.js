/**
 * Empire English — System Status / Maintenance experience.
 *
 * Self-contained (no dependency on app.js/darb.js) so it runs on EVERY page:
 * homepage, exercise pages, gate, and guide. On load it asks the bot API for
 * the system status and, if maintenance is active, plays a short branded
 * "royal notice" animation:
 *
 *   • The Empire crest reveals in the CENTER of the screen with a message.
 *   • SOFT  → after ~2.5s the card glides UP and docks into a slim top
 *             banner; the page becomes usable. (Click/tap to skip.)
 *   • HARD  → the centered card stays as a full-screen overlay (page paused).
 *
 * Copy is bilingual with English and Arabic in SEPARATE blocks (each with its
 * own text direction) so there is no bidi jumble. Deliberately GENERAL — no
 * specific reason and NO promised time (maintenance "might take minutes, maybe
 * longer"), just a calm, professional notice.
 *
 * Principle: FAIL-OPEN. Any network/parse error → show nothing, so a status
 * outage can never trap a student behind a false maintenance screen. The
 * status fetch is no-store (never cached) so toggling maintenance is instant.
 */
(function () {
  var API_BASE = 'https://bot.empireenglish.online';
  var CREST = '/logo.png';

  // ---- Copy (general, professional, bilingual) ---------------------------
  var COPY = {
    title_en: 'Empire English is upgrading',
    title_ar: 'جاري تطوير منصة إمباير إنجلش',
    body_en: "We're polishing the platform to make it better. It'll be ready again shortly.",
    body_ar: 'بنطوّر المنصة عشان تبقى أحسن. هترجع تشتغل قريب بإذن الله.',
    safe_en: '🔒 Your streak & progress are 100% safe.',
    safe_ar: '🔒 تقدّمك وسلسلة أيامك محفوظة بالكامل.',
    banner_en: "We're upgrading the platform — you can keep practicing. Your progress is safe.",
    banner_ar: 'جاري تطوير المنصة — كمّل تمرينك عادي، وتقدّمك محفوظ.'
  };

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  // ---- Centered "royal notice" card (used by both soft + hard) -----------
  function buildCard(isHard) {
    var card = el('div', 'maint-card');
    card.innerHTML =
      '<img class="maint-crest" src="' + CREST + '" alt="Empire English" />' +
      '<div class="maint-en" dir="ltr" lang="en">' +
        '<h1>' + COPY.title_en + '</h1>' +
        '<p class="maint-sub">' + COPY.body_en + '</p>' +
      '</div>' +
      '<div class="maint-ar" dir="rtl" lang="ar">' +
        '<h2>' + COPY.title_ar + '</h2>' +
        '<p>' + COPY.body_ar + '</p>' +
      '</div>' +
      '<div class="maint-safe">' +
        '<div dir="ltr" lang="en">' + COPY.safe_en + '</div>' +
        '<div dir="rtl" lang="ar">' + COPY.safe_ar + '</div>' +
      '</div>';
    return card;
  }

  function buildOverlay(isHard) {
    var ov = el('div', 'maint-overlay' + (isHard ? ' maint-hard' : ''));
    ov.id = 'maint-overlay';
    ov.appendChild(buildCard(isHard));
    return ov;
  }

  // ---- Slim top banner (soft, after the reveal docks) --------------------
  function showBanner() {
    if (document.getElementById('maint-banner')) return;
    var bar = el('div', 'maint-banner');
    bar.id = 'maint-banner';
    bar.innerHTML =
      '<div class="maint-banner-text">' +
        '<div class="maint-line" dir="ltr" lang="en">🔧 ' + COPY.banner_en + '</div>' +
        '<div class="maint-line" dir="rtl" lang="ar">🔧 ' + COPY.banner_ar + '</div>' +
      '</div>' +
      '<button class="maint-close" aria-label="Dismiss">✕</button>';
    document.body.appendChild(bar);
    document.body.classList.add('has-maint-banner');
    bar.querySelector('.maint-close').addEventListener('click', function () {
      bar.remove();
      document.body.classList.remove('has-maint-banner');
    });
    // Trigger the drop-in animation on the next frame.
    requestAnimationFrame(function () { bar.classList.add('maint-in'); });
  }

  function runSoft() {
    if (document.getElementById('maint-overlay')) return;
    var ov = buildOverlay(false);
    document.body.appendChild(ov);
    requestAnimationFrame(function () { ov.classList.add('maint-in'); });

    var done = false;
    function dock() {
      if (done) return;
      done = true;
      ov.classList.add('maint-dock');           // animate card up + fade
      setTimeout(function () {
        ov.remove();
        showBanner();                            // slim top banner drops in
      }, 650);
    }
    // Auto-dock after the reveal holds; allow click/tap to skip.
    var timer = setTimeout(dock, 2600);
    ov.addEventListener('click', function () { clearTimeout(timer); dock(); });
  }

  function runHard() {
    if (document.getElementById('maint-overlay')) return;
    var ov = buildOverlay(true);
    document.body.appendChild(ov);
    document.body.classList.add('has-maint-overlay');
    requestAnimationFrame(function () { ov.classList.add('maint-in'); });
  }

  function apply(status) {
    if (!status || status.state !== 'maintenance') return;
    if (status.level === 'hard') runHard();
    else runSoft();
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
