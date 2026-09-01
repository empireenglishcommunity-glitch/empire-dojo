/**
 * Empire English Practice — content-addressed speech clip ids.
 *
 * WHY THIS FILE EXISTS SEPARATELY
 * ------------------------------------------------------------------
 * The practice site is moving off the browser's speechSynthesis (the robotic
 * device voice) onto pre-rendered Kokoro clips. Rather than rewrite all 25
 * TTS.speak() call sites to pass a clip id, `TTS.speak(text)` becomes
 * content-addressed: it hashes the text it was handed and plays the matching
 * clip. Dynamic text (vocabulary words, dictation sentences read out of JSON
 * embedded in the page) then works identically to static text.
 *
 * That only holds if the id computed in the BROWSER is byte-identical to the id
 * computed in PYTHON by scripts/speech_registry.py, which names the rendered
 * files. A one-character disagreement does not degrade — it means every clip is
 * requested under a name that does not exist. So this logic lives in one small
 * file with no dependencies, usable from both the browser and node, and
 * scripts/verify_clip_id_parity.py runs BOTH implementations over every real
 * utterance and fails the build if any id differs.
 *
 * THE CONTRACT (must match speech_registry.py exactly)
 * ------------------------------------------------------------------
 *   norm(text)         collapse every whitespace run to one space, trim ends
 *   clipId(voice,text) "sp-" + sha256(`${voice}|${norm(text)}`).hex[:16]
 *
 * THE VOICE IS PART OF THE ID, deliberately. Hashing text alone collapsed every
 * repeat of a word into a single clip, so a word appearing both as vocabulary
 * and as a dictation item could only ever have ONE voice — which silently
 * defeated the requirement to hear different speakers. Keying on voice+text
 * costs more clips and actually delivers the cast.
 *
 * A NOTE ON WHITESPACE, which is the one place these two languages disagree.
 * Python's str.split() and JavaScript's /\s+/ do not cover the same set:
 *   - Python splits on \x1c-\x1f and \x85; JS /\s+/ does not match them.
 *   - JS /\s+/ matches \ufeff (BOM); Python's split() does not treat it as
 *     whitespace.
 * Every one of those characters would produce a different id on each side. No
 * utterance currently contains any of them (measured: the only whitespace in
 * all 9,360 texts is the plain space), so the simple implementation is correct
 * today — and speech_registry.py --check fails the build if one ever appears,
 * instead of letting it become a silently missing clip.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;   // node
  else root.SpeechId = api;                                                // browser
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /** Collapse whitespace runs to a single space and trim. Mirrors Python's
   *  " ".join(text.split()) — note that ''.split(/\s+/) yields [''] in JS, so
   *  trim() must come FIRST or empty input would produce a stray space. */
  function norm(text) {
    return String(text === null || text === undefined ? '' : text)
      .trim()
      .split(/\s+/)
      .join(' ');
  }

  function hex(buffer) {
    const bytes = new Uint8Array(buffer);
    let out = '';
    for (let i = 0; i < bytes.length; i++) {
      out += bytes[i].toString(16).padStart(2, '0');
    }
    return out;
  }

  /** "sp-" + first 16 hex chars of sha256("voice|normalised text").
   *  Async because SubtleCrypto is async; callers await it. */
  async function clipId(voice, text) {
    const key = String(voice) + '|' + norm(text);
    const data = new TextEncoder().encode(key);          // utf-8, same as Python
    const digest = await crypto.subtle.digest('SHA-256', data);
    return 'sp-' + hex(digest).slice(0, 16);
  }

  /* ------------------------------------------------------------------
   *  WHICH VOICE THIS PAGE SPEAKS IN
   *
   *  Derived from the page's own URL rather than written into the page by
   *  the generator. The generator has ~15 separate page templates, so
   *  emitting a window.SPEECH_VOICE into each means 15 edits where missing
   *  ONE silently leaves that surface on the wrong voice — and a wrong voice
   *  is a wrong clip id, which is a 404, which is silence. The URL already
   *  encodes everything the rule needs, so there is nothing to forget.
   *
   *  Mirrors speech_registry.py:
   *      surface = path.stem                  (the filename, no extension)
   *      index   = sum of every \d+ run in the path
   *      voice   = rotation[index % 5] for listening/broadcast, else cast
   *  verify_clip_id_parity.py checks this against Python for every real page
   *  path in site/, which is what catches the edge cases ("/" -> index, clean
   *  URLs with no .html, trailing slashes).
   *
   *  The cast is duplicated here because the browser cannot read
   *  scripts/voice_cast.json. The parity test asserts the two are identical,
   *  so the duplication cannot drift silently.
   * ------------------------------------------------------------------ */
  const CAST = {
    index: 'af_aoede',
    accent: 'am_adam',
    shadowing: 'af_heart',
    vocab: 'af_bella',
    reading: 'af_sarah',
    grammar: 'am_eric',
    mediation: 'am_adam',
    review: 'af_kore'
  };
  // Chosen on ISOLATED-WORD accuracy, not sentence accuracy — the listening
  // surface is 86.8% single words (3,153 of 3,633 clips), and the two rankings
  // disagree sharply. Measured 2026-09-01 over 87 real words from the site,
  // transcribed with faster-whisper: am_adam 97.7%, af_heart 95.4%,
  // af_bella 94.3%, af_nicole 94.3%, am_fenrir 88.5%.
  //
  // am_eric was removed: 66.7%, worst of the twelve shortlisted, 31 points below
  // am_adam. It was serving the page a student reported as unclear, and on her
  // own three words it produced 'pound'->"Boundy", 'cheap'->"Jeeba", 'cut'->"God".
  // It stays the grammar voice, which is all sentences and where it is strong.
  // Full data and reasoning: scripts/voice_cast.json.
  const LISTENING_ROTATION =
    ['am_adam', 'af_heart', 'af_bella', 'af_nicole', 'am_fenrir'];
  const DEFAULT_VOICE = 'af_heart';

  function surfaceOf(pathname) {
    let p = String(pathname || '').split('?')[0].split('#')[0];
    // "/a1/week1/day1/" and "/" are served as index.html, and Python sees a
    // stem of "index" for those — without this they would fall through to the
    // default voice instead of the index voice.
    if (p === '' || p.endsWith('/')) return 'index';
    const last = p.split('/').pop();
    return last.replace(/\.html?$/i, '');
  }

  function rotationIndex(pathname) {
    const p = String(pathname || '').split('?')[0].split('#')[0];
    const nums = p.match(/\d+/g);
    if (!nums) return 0;
    return nums.reduce((a, n) => a + parseInt(n, 10), 0);
  }

  function voiceForPath(pathname) {
    const surface = surfaceOf(pathname);
    if (surface === 'listening' || surface === 'broadcast') {
      return LISTENING_ROTATION[
        rotationIndex(pathname) % LISTENING_ROTATION.length];
    }
    return CAST[surface] || DEFAULT_VOICE;
  }

  return {
    norm: norm,
    clipId: clipId,
    surfaceOf: surfaceOf,
    rotationIndex: rotationIndex,
    voiceForPath: voiceForPath,
    _cast: CAST,
    _rotation: LISTENING_ROTATION,
    _default: DEFAULT_VOICE
  };
}));
