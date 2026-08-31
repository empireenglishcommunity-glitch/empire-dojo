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

  return { norm: norm, clipId: clipId };
}));
