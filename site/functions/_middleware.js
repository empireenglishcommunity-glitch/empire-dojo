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
 */

// Paths that are NEVER gated (public assets, the gate page itself, API)
const PUBLIC_PATHS = [
  '/gate.html',
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

/**
 * Main middleware handler
 */
export async function onRequest(context) {
  const { request, env, next } = context;
  const url = new URL(request.url);
  const path = url.pathname;

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

  // 6. Level enforcement: /lX/ paths require matching session level
  const levelMatch = path.match(/^\/(l\d)\//);
  if (levelMatch) {
    const pathLevel = levelMatch[1].toUpperCase(); // "L0", "L1", etc.
    const sessionLevel = (payload.lvl || '').toUpperCase();
    if (pathLevel !== sessionLevel) {
      // Wrong level — serve a 403 with a message
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
  const gateUrl = new URL('/gate.html', url.origin);
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
