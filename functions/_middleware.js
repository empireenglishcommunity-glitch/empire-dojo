/**
 * Darb Phase 3 — Edge Gate Middleware (Cloudflare Pages Functions)
 *
 * Runs BEFORE any page is served. Verifies the student has a valid,
 * non-expired, non-revoked HMAC session token (empire_session cookie).
 * If not, serves gate.html instead of the requested content.
 *
 * This is the switch that makes the practice content genuinely gated.
 * Removing this file + redeploying instantly reverts to open serving
 * (documented rollback procedure).
 *
 * Token format (same as darb.py):
 *   base64url(payload_json) + "." + base64url(hmac_sha256)
 *   payload: {did, lvl, sid, iat, exp}
 *
 * Env vars required:
 *   DARB_SESSION_SECRET — same hex string as the bot's .env
 * Optional:
 *   BOT_API_BASE — overrides the default bot API origin used for the
 *                  revocation check (see checkRevoked below).
 */

// Bot API origin for the revocation check. Same host the site's JS already
// talks to (site/js/darb.js API_BASE).
const DEFAULT_BOT_API_BASE = 'https://bot.empireenglish.online';

// How long a "this session is still valid" answer is cached at the edge.
// A revoked student keeps their pages for at most this long, which is the
// price of not making a subrequest on every single page view. 60s is short
// enough to feel immediate and long enough to keep the API load trivial.
const REVOCATION_CACHE_SECONDS = 60;

// Paths that are NEVER gated (public assets, the gate page itself, API)
const PUBLIC_PATHS = [
  '/gate.html',
  '/gate',
  '/guide',
  '/guide/',
  '/css/',
  '/js/',
  '/favicon.png',
  '/logo.png',
  '/manifest.json',
  '/sw.js',
  '/audio/',
  '/robots.txt',
];

// Paths that require a session but NOT level-scoping (homepage, dash, review)
const LEVEL_FREE_PATHS = [
  '/index.html',
  '/dash/',
  '/review/',
];

// SHA-256 of the owner/admin ops-guide passcode.
// The plaintext passcode is NEVER stored in this repo — only its hash.
// Knowing the hash does not grant access (it can't be reversed to the passcode).
// To rotate: run `printf 'NEW_PASSCODE' | sha256sum` and paste the hex here.
// May be overridden at runtime via env.OPS_GUIDE_PASSCODE_SHA256.
// Rotated 2026-08-27 — the previous passcode was lost. If you rotate again,
// only the hash goes here; the plaintext lives in your head, nowhere in git.
const OPS_GUIDE_PASSCODE_SHA256 =
  'f60888c2d61a8b61f781dd035896cdcd29ca397551cc92a41a7e8d3fb56607c8';

// How long a correct passcode keeps the ops guide unlocked on that device.
const OPS_COOKIE_MAX_AGE = 60 * 60 * 24 * 30; // 30 days

/**
 * Main middleware handler
 */
export async function onRequest(context) {
  const { request, env, next } = context;
  const url = new URL(request.url);
  const path = url.pathname;

  // 0. Owner/admin surfaces — passcode-gated, INDEPENDENT of student sessions.
  //    Intercept early so the student session logic never applies here.
  //
  //    /content-review/ is the curriculum sign-off surface. It deliberately
  //    shows the CORRECT ANSWER to every comprehension question, so it must not
  //    be reachable with a student session. Note it is NOT enough to add it to
  //    LEVEL_FREE_PATHS (where an earlier '/review/' entry sits): that only
  //    drops level-scoping and would let any linked student read every answer
  //    at every level. It needs the owner passcode, which is what this branch
  //    gives it, reusing the ops-guide cookie so the owner unlocks once.
  if (path === '/ops-guide' || path.startsWith('/ops-guide/') ||
      path.startsWith('/content-review')) {
    return handleOpsGuide(context);
  }

  // 0b. Guide screenshots were removed (owner request). Cloudflare Pages may
  //     still retain the old image assets and serve them at their direct URL.
  //     Return 404 for anything under /guide/img/ so those orphans are gone.
  if (path.startsWith('/guide/img/')) {
    return new Response('Not Found', {
      status: 404,
      headers: { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' },
    });
  }

  // 1. Public assets — always pass through
  if (path === '/' || PUBLIC_PATHS.some(p => path.startsWith(p) || path === p)) {
    // The homepage (/) is gated too — but we handle it via gate.html redirect below
    if (path !== '/') {
      return next();
    }
  }

  // 2. Get the session secret
  const secret = env.DARB_SESSION_SECRET;
  if (!secret) {
    // Fail-open: if secret isn't configured, let everything through
    // (prevents locking everyone out during initial setup)
    return next();
  }

  // 3. Extract token from cookie
  const cookieHeader = request.headers.get('Cookie') || '';
  const token = parseCookie(cookieHeader, 'empire_session');

  // 4. Verify token
  const payload = await verifyToken(token, secret);

  if (!payload) {
    // No valid session — serve gate page
    return serveGate(request, env, url);
  }

  // 5. Check expiry
  const now = Math.floor(Date.now() / 1000);
  if (payload.exp < now) {
    return serveGate(request, env, url);
  }

  // 5a. REVOCATION. A valid signature only proves the token was minted by us;
  //     it says nothing about whether the session has since been withdrawn.
  //     Without this check a suspended student keeps rendering lesson pages
  //     from their cookie for the remainder of the 60-day token lifetime, even
  //     though every API call already 401s. That gap is exactly what made
  //     "!suspend logs them out of the practice page" untrue before this.
  //
  //     Deliberately fails OPEN on a network/API error and CLOSED only on an
  //     explicit "not valid" answer: locking every paying student out of their
  //     lessons because the bot restarted would be a far worse outcome than a
  //     suspended student getting a few extra minutes of access.
  if (await checkRevoked(token, env)) {
    return serveGate(request, env, url);
  }

  // 5b. Legacy retirement: a valid session MUST carry a CEFR level (A1–C2).
  //     Pre-migration tokens carry lvl "L0".."L3"; treat them like an expired
  //     session so the student just re-links (friendly gate) — never a hard 403.
  //     This lets the legacy L0→A1 translation map be removed entirely.
  const CEFR_LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2'];
  const sessionLevel = String(payload.lvl || '').toUpperCase();
  if (!CEFR_LEVELS.includes(sessionLevel)) {
    return serveGate(request, env, url);
  }

  // 6. Level enforcement: CEFR content paths (/a1/…/c2/) require the session's
  //    level to match, so a student only ever sees their own level's zone.
  const levelMatch = path.match(/^\/([abc][12])\//i);
  if (levelMatch) {
    const pathLevel = levelMatch[1].toUpperCase();
    if (pathLevel !== sessionLevel) {
      return new Response(
        levelDeniedHTML(sessionLevel, pathLevel),
        {
          status: 403,
          headers: { 'Content-Type': 'text/html; charset=utf-8' },
        }
      );
    }
  }

  // 7. Inject watermark into HTML responses
  const response = await next();

  const contentType = response.headers.get('Content-Type') || '';
  if (contentType.includes('text/html')) {
    const body = await response.text();
    const watermarked = injectWatermark(body, payload);
    return new Response(watermarked, {
      status: response.status,
      headers: response.headers,
    });
  }

  return response;
}


/**
 * Has this session been revoked? Returns TRUE only when the bot explicitly
 * says the session is no longer valid.
 *
 * The bot's /api/session-status endpoint already exists and already does the
 * right thing (verify signature + expiry + device_sessions.revoked). It was
 * simply never called from the edge — the comment on it in api_server.py even
 * calls it the "edge revocation check". This closes that loop.
 *
 * Answers are cached per-token for REVOCATION_CACHE_SECONDS using the Workers
 * Cache API, so a student browsing 30 pages makes one subrequest, not 30.
 */
async function checkRevoked(token, env) {
  if (!token) return false;
  const base = (env && env.BOT_API_BASE) || DEFAULT_BOT_API_BASE;

  // Cache key must be a URL and must not leak the whole token; a hash of it is
  // enough to be unique per session while keeping the token out of cache keys.
  let cacheKey;
  try {
    const digest = await sha256hex(token);
    cacheKey = new Request(`https://darb-revocation.internal/${digest}`);
  } catch (_) {
    cacheKey = null;
  }

  if (cacheKey) {
    try {
      const hit = await caches.default.match(cacheKey);
      if (hit) {
        const cached = await hit.text();
        return cached === 'revoked';
      }
    } catch (_) { /* cache unavailable — fall through to a live check */ }
  }

  let verdict = 'valid';
  try {
    const res = await fetch(`${base}/api/session-status`, {
      method: 'GET',
      headers: { 'X-Darb-Session': token },
      // Never let a slow API stall page delivery.
      signal: AbortSignal.timeout ? AbortSignal.timeout(3000) : undefined,
    });
    if (res.status === 401) {
      verdict = 'revoked';
    } else if (!res.ok) {
      // 5xx / unexpected — treat as valid (fail open) and do NOT cache, so the
      // next request retries rather than trusting a bad answer for a minute.
      return false;
    }
  } catch (_) {
    return false; // network error / timeout — fail open, don't cache
  }

  if (cacheKey) {
    try {
      await caches.default.put(cacheKey, new Response(verdict, {
        headers: { 'Cache-Control': `max-age=${REVOCATION_CACHE_SECONDS}` },
      }));
    } catch (_) { /* best effort */ }
  }
  return verdict === 'revoked';
}


// ============================================================
//  OPS GUIDE — PASSCODE GATE (owner/admin only)
// ============================================================
//
// Server-side gate: the guide HTML is NEVER served unless the request
// carries a cookie whose value hashes to the stored passcode hash.
// The plaintext passcode lives only in the visitor's cookie (client side)
// and in the owner's head — never in this repo.

async function handleOpsGuide(context) {
  const { request, env, next } = context;

  const expectedHash =
    (env && env.OPS_GUIDE_PASSCODE_SHA256) || OPS_GUIDE_PASSCODE_SHA256;

  const cookieHeader = request.headers.get('Cookie') || '';
  const supplied = parseCookie(cookieHeader, 'ops_pass');

  if (supplied) {
    const suppliedHash = await sha256hex(supplied);
    if (timingSafeEqual(suppliedHash, expectedHash)) {
      // Correct passcode — serve the actual guide (static asset).
      return next();
    }
  }

  // No/incorrect passcode — serve the passcode entry page (200, never cached).
  // `wrong=1` when a bad passcode was submitted, so we can show an error.
  const wrong = supplied ? '1' : '';
  return new Response(opsGateHTML(wrong), {
    status: 200,
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
    },
  });
}

// SHA-256 of a string -> lowercase hex (Web Crypto, available at the edge).
async function sha256hex(str) {
  const data = new TextEncoder().encode(str);
  const digest = await crypto.subtle.digest('SHA-256', data);
  const bytes = new Uint8Array(digest);
  let hex = '';
  for (const b of bytes) hex += b.toString(16).padStart(2, '0');
  return hex;
}

function opsGateHTML(wrong) {
  const err = wrong
    ? '<p style="color:#e74c3c;font-family:Cairo,sans-serif;margin-top:12px">رمز غير صحيح — حاول مرة أخرى.<br>Incorrect passcode — try again.</p>'
    : '';
  const maxAge = OPS_COOKIE_MAX_AGE;
  return `<!DOCTYPE html><html lang="ar" dir="rtl"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Empire English — Ops Guide</title>
<link rel="icon" type="image/png" href="/favicon.png">
<meta name="theme-color" content="#D4AF37">
<link rel="stylesheet" href="/css/empire.css">
<meta name="robots" content="noindex,nofollow">
</head><body>
<div class="container" style="max-width:440px;margin:0 auto;padding:60px 20px;text-align:center">
  <img src="/logo.png" alt="Empire English" style="width:64px;height:64px;border-radius:50%;box-shadow:0 0 15px rgba(212,175,55,0.3)">
  <h1 style="color:var(--accent);font-family:Cinzel,serif;margin-top:16px">Ops Guide</h1>
  <p style="color:var(--text-secondary);font-family:Cairo,sans-serif">هذه الصفحة للمالك والإداريين فقط.<br>Owner &amp; admins only — enter the passcode.</p>
  <form id="pf" style="margin-top:24px" onsubmit="return unlock(event)">
    <input id="pc" type="password" autocomplete="off" autofocus placeholder="Passcode"
      style="width:100%;padding:14px 16px;border-radius:12px;border:1px solid var(--border);
             background:var(--bg-primary);color:var(--text-primary);font-size:1.1rem;text-align:center;direction:ltr">
    <button class="btn" type="submit" style="margin-top:16px;width:100%">🔓 دخول / Unlock</button>
  </form>
  ${err}
  <p style="color:var(--text-muted);font-size:0.8rem;margin-top:22px;font-family:Cairo,sans-serif">Empire English Community — Common Sense First 🏛️</p>
</div>
<script>
function unlock(e){
  e.preventDefault();
  var v=document.getElementById('pc').value;
  if(!v)return false;
  // Store the passcode in a cookie; the edge verifies it by hash on reload.
  document.cookie='ops_pass='+encodeURIComponent(v)+';path=/;max-age=${maxAge};SameSite=Lax;Secure';
  location.reload();
  return false;
}
</script>
</body></html>`;
}


// ============================================================
//  TOKEN VERIFICATION (mirrors darb.py exactly)
// ============================================================

async function verifyToken(token, secret) {
  if (!token || !secret) return null;

  const dotIdx = token.indexOf('.');
  if (dotIdx < 0) return null;

  const body = token.substring(0, dotIdx);
  const sig = token.substring(dotIdx + 1);

  // Compute expected signature
  const expectedSig = await hmacSign(body, secret);

  // Constant-time comparison
  if (!timingSafeEqual(sig, expectedSig)) {
    return null;
  }

  // Decode payload
  try {
    const raw = base64urlDecode(body);
    const payload = JSON.parse(new TextDecoder().decode(raw));
    return payload;
  } catch (e) {
    return null;
  }
}

async function hmacSign(body, secret) {
  const encoder = new TextEncoder();
  const keyData = encoder.encode(secret);
  const key = await crypto.subtle.importKey(
    'raw', keyData, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
  );
  const signature = await crypto.subtle.sign('HMAC', key, encoder.encode(body));
  return base64urlEncode(new Uint8Array(signature));
}

function base64urlEncode(bytes) {
  let binary = '';
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function base64urlDecode(str) {
  str = str.replace(/-/g, '+').replace(/_/g, '/');
  const pad = (4 - str.length % 4) % 4;
  str += '='.repeat(pad);
  const binary = atob(str);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}


// ============================================================
//  GATE PAGE
// ============================================================

async function serveGate(request, env, url) {
  // Try to fetch the static gate.html from the same origin
  const gateUrl = new URL('/gate', url.origin);
  const gateResponse = await fetch(gateUrl.toString(), {
    headers: request.headers,
    cf: { cacheEverything: true, cacheTtl: 300 },
  });

  if (gateResponse.ok) {
    return new Response(gateResponse.body, {
      status: 200,
      headers: {
        'Content-Type': 'text/html; charset=utf-8',
        'Cache-Control': 'no-store',
      },
    });
  }

  // Fallback: inline minimal gate
  return new Response(fallbackGateHTML(), {
    status: 200,
    headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
  });
}


// ============================================================
//  LEVEL DENIED PAGE
// ============================================================

function levelDeniedHTML(sessionLevel, requestedLevel) {
  return `<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Access Denied | Empire English</title>
<link rel="stylesheet" href="/css/empire.css"></head><body>
<div class="container" style="text-align:center;padding:60px 20px">
<h1 style="color:var(--accent);font-family:Cinzel,serif">Access Denied</h1>
<p style="color:var(--text-secondary);margin:16px 0">Your session is for <strong>${sessionLevel}</strong>, but you requested <strong>${requestedLevel}</strong> content.</p>
<p style="font-family:Cairo,sans-serif;direction:rtl;color:var(--text-secondary)">جلستك مخصصة لمستوى ${sessionLevel} فقط</p>
<a href="/" class="btn" style="margin-top:24px">← Back to Calendar</a>
</div></body></html>`;
}


// ============================================================
//  WATERMARK (faint student overlay)
// ============================================================

function injectWatermark(html, payload) {
  const did = payload.did || '';
  const sid = (payload.sid || '').substring(0, 6);
  // Faint diagonal watermark — visible enough to trace leaks, not
  // intrusive enough to annoy legitimate students
  const watermarkCSS = `
<style id="darb-wm">.darb-wm{position:fixed;inset:0;pointer-events:none;z-index:99999;
opacity:0.025;font-size:1.8rem;font-family:monospace;color:var(--text-primary,#fff);
display:flex;align-items:center;justify-content:center;transform:rotate(-30deg);
user-select:none;-webkit-user-select:none;white-space:nowrap;
letter-spacing:0.3em;overflow:hidden}</style>
<div class="darb-wm">${did}-${sid}</div>`;

  // Inject before </body>
  if (html.includes('</body>')) {
    return html.replace('</body>', watermarkCSS + '</body>');
  }
  return html + watermarkCSS;
}


// ============================================================
//  HELPERS
// ============================================================

function parseCookie(header, name) {
  const match = header.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : '';
}

function fallbackGateHTML() {
  return `<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Empire English — Access</title><link rel="stylesheet" href="/css/empire.css"></head><body>
<div class="container" style="text-align:center;padding:60px 20px">
<h1 style="color:var(--accent);font-family:Cinzel,serif">Empire English Practice</h1>
<p style="color:var(--text-secondary)">Access required. Run <code>!link</code> in Discord.</p>
</div></body></html>`;
}
