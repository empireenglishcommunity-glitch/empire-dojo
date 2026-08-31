#!/usr/bin/env node
/**
 * The header streak must show the student's REAL streak, or nothing.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * `Gamification._updateStreak()` used to keep its own streak in localStorage and
 * increment it every time `init()` ran — i.e. on every page load. The 🔥 counter
 * in the header, present on 6,303 pages, therefore went up for merely OPENING a
 * page: no exercise, no submission, no work at all. It was also per-device, and
 * it rolled over on the browser's UTC date while the programme's day is
 * `config.TIMEZONE` on the bot (Africa/Cairo since 2026-08-31).
 *
 * `verify_no_invented_streak.py` is the static guard against that pattern
 * returning. This file is the behavioural half: a static check cannot tell you
 * the element actually renders the right number, only that the bad code is gone.
 * "The forbidden pattern is absent" is also satisfied by deleting the feature.
 *
 * It loads the REAL `site/js/app.js` in a stubbed browser rather than
 * reimplementing the logic, so it fails if the function is renamed or rewired.
 *
 * Run: node scripts/test_streak_display.js
 */
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const APP = path.join(__dirname, '..', 'site', 'js', 'app.js');

function makeEnv() {
  const el = {
    hidden: false,
    textContent: 'PRESET-SHOULD-BE-REPLACED',
    _attrs: {},
    setAttribute(k, v) { this._attrs[k] = v; },
    removeAttribute(k) { delete this._attrs[k]; },
    get title() { return this._attrs.title; },
    set title(v) { this._attrs.title = v; },
  };
  const store = {};
  const ctx = {
    console,
    document: {
      getElementById: (id) => (id === 'streak-display' ? el : null),
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener: () => {},
      createElement: () => ({ style: {}, setAttribute() {}, appendChild() {}, classList: { add() {} } }),
      body: { appendChild() {}, classList: { add() {}, remove() {} } },
      documentElement: { style: {}, setAttribute() {}, classList: { add() {}, remove() {} } },
      readyState: 'complete',
    },
    window: {
      addEventListener: () => {},
      dispatchEvent: () => {},
      location: { pathname: '/a1/week1/day1/grammar.html', href: 'https://x/', search: '' },
      matchMedia: () => ({ matches: false, addEventListener() {} }),
    },
    localStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
    },
    navigator: { userAgent: 'node', language: 'en' },
    fetch: () => Promise.resolve({ ok: false, status: 0, json: async () => ({}) }),
    setTimeout, clearTimeout, setInterval, clearInterval,
    CustomEvent: function (n, o) { this.type = n; Object.assign(this, o); },
    Audio: function () { return { play() {}, pause() {}, addEventListener() {} }; },
    AudioContext: function () { return {}; },
    speechSynthesis: { speak() {}, cancel() {}, getVoices: () => [] },
  };
  ctx.window.localStorage = ctx.localStorage;
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(APP, 'utf8'), ctx, { filename: 'app.js' });
  // `const` at script top level lives in the script's lexical scope, not on the
  // context object, so bridge the two objects out explicitly.
  vm.runInContext('var __CP = ConnectedProgress; var __G = Gamification;', ctx);
  return { el, store, CP: ctx.__CP, G: ctx.__G };
}

let fails = 0;
function check(label, cond, detail) {
  if (cond) { console.log(`  PASS  ${label}`); }
  else { console.log(`  FAIL  ${label}\n          ${detail}`); fails++; }
}

console.log('test_streak_display: exercising the real _updateStreak()\n');

// 1) Not linked — must show NOTHING rather than a guess.
{
  const { CP, G, el } = makeEnv();
  CP.data = null;
  G._updateStreak();
  check('not linked -> element hidden', el.hidden === true, `hidden=${el.hidden}`);
  check('not linked -> no number rendered', el.textContent === '', `text=${JSON.stringify(el.textContent)}`);
}

// 2) Linked with a real streak.
{
  const { CP, G, el } = makeEnv();
  CP.data = { streak: 43, level: 'a1' };
  G._updateStreak();
  check('streak 43 -> renders "🔥 43"', el.textContent === '🔥 43', `text=${JSON.stringify(el.textContent)}`);
  check('streak 43 -> visible', el.hidden === false, `hidden=${el.hidden}`);
  check('title names the source of truth', /Discord record/.test(el.title || ''), `title=${el.title}`);
}

// 3) A real zero is shown, not hidden — 0 is information, absence is not.
{
  const { CP, G, el } = makeEnv();
  CP.data = { streak: 0 };
  G._updateStreak();
  check('streak 0 -> renders "🔥 0" and stays visible',
    el.textContent === '🔥 0' && el.hidden === false,
    `text=${JSON.stringify(el.textContent)} hidden=${el.hidden}`);
}

// 4) Malformed API payloads must never reach the student as NaN/undefined.
for (const bad of [undefined, null, 'seven', NaN, -3, {}, []]) {
  const { CP, G, el } = makeEnv();
  CP.data = { streak: bad };
  G._updateStreak();
  check(`streak=${JSON.stringify(bad)} -> hidden, nothing rendered`,
    el.hidden === true && el.textContent === '',
    `hidden=${el.hidden} text=${JSON.stringify(el.textContent)}`);
}

// 5) THE ORIGINAL DEFECT, pinned: page loads alone must not create a streak.
{
  const { CP, G, el, store } = makeEnv();
  CP.data = null;
  for (let i = 0; i < 5; i++) G._updateStreak();
  const wrote = Object.keys(store).filter((k) => /streak|last_active/.test(k));
  check('5 page loads -> nothing written to localStorage', wrote.length === 0,
    `keys=${JSON.stringify(wrote)}`);
  check('5 page loads -> still no invented number', el.textContent === '',
    `text=${JSON.stringify(el.textContent)}`);
}

// 6) A missing element must not throw — most pages have it, some may not.
{
  const { G } = makeEnv();
  const doc = { getElementById: () => null };
  let threw = null;
  try { G._updateStreak.call({ ...G, document: doc }); } catch (e) { threw = e; }
  check('no #streak-display -> does not throw', threw === null, String(threw));
}

console.log(fails === 0
  ? '\nALL BEHAVIOUR CHECKS PASSED'
  : `\n${fails} CHECK(S) FAILED`);
process.exit(fails === 0 ? 0 : 1);
