#!/usr/bin/env node
/**
 * The weekly-assessment REVIEW must show the student's own answer, and must
 * never print the correct answer twice.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * A student (Esraa, A1) reported answers that "looked correct" being marked
 * wrong. The grading was never the problem — a live audit found zero cases
 * across the whole database where a canonically-equal answer was scored wrong.
 * The problem was purely in the REVIEW rendering here:
 *
 *   old:  detail = `Correct answer: ${it.expected}` + ` — ${it.feedback}`
 *   and the server `feedback` for objective items was ITSELF
 *         `Correct answer: ${it.expected}`
 *
 * so the review printed  "Correct answer: has — Correct answer: has"  — the
 * correct word twice — and NEVER showed what the student actually typed. A
 * student who typed a genuinely wrong word (e.g. "night" for "evening") just
 * saw the right answer doubled and concluded her correct answer was rejected.
 *
 * `ItqanAssessment._reviewDetail(it, ok)` is the one place that builds the
 * per-item line. This test loads the REAL site/js/assessment.js in a stubbed
 * browser and pins the contract, so the doubling / answer-hiding cannot return:
 *
 *   1. The correct answer appears AT MOST ONCE in a wrong-item line.
 *   2. A wrong objective item shows the student's OWN answer.
 *   3. The correct answer is taken from `expected`, never re-derived from
 *      `feedback` (which no longer carries it).
 *   4. Graceful with older payloads (missing answer/expected) and with
 *      audio/writing items that have no single expected word.
 *   5. Output is HTML-escaped (no raw < > from a student's answer).
 *
 * Run: node scripts/test_assessment_review_detail.js
 */
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const SRC = path.join(__dirname, '..', 'site', 'js', 'assessment.js');

function loadItqan() {
  const ctx = {
    console,
    document: {
      getElementById: () => null,
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener: () => {},
      createElement: () => ({ style: {}, setAttribute() {}, appendChild() {}, classList: { add() {} } }),
      body: { appendChild() {} },
    },
    window: { addEventListener: () => {}, location: { search: '' } },
    setTimeout, clearTimeout, setInterval, clearInterval,
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(SRC, 'utf8'), ctx, { filename: 'assessment.js' });
  vm.runInContext('var __ITQAN = ItqanAssessment;', ctx);
  return ctx.__ITQAN;
}

let fails = 0;
function check(label, cond, detail) {
  if (cond) { console.log(`  PASS  ${label}`); }
  else { console.log(`  FAIL  ${label}\n          ${detail}`); fails++; }
}
// Count non-overlapping occurrences of a substring.
function count(hay, needle) {
  let n = 0, i = 0;
  while ((i = hay.indexOf(needle, i)) !== -1) { n++; i += needle.length; }
  return n;
}

console.log('test_assessment_review_detail: exercising the real _reviewDetail()\n');

const I = loadItqan();

// ── 1. THE EXACT ESRAA BUG: a wrong objective item ──────────────────────────
// Server now sends feedback="" for objective items; expected + answer are
// structured fields. (Also test the WORST case: an old/other surface still
// putting "Correct answer: X" in feedback must STILL not double it, because
// the client no longer trusts feedback for the answer.)
{
  const it = { skill: 'vocab', correct: 0, expected: 'evening', answer: 'night', feedback: '' };
  const out = I._reviewDetail(it, false);
  check('wrong item: correct answer appears exactly once',
    count(out, 'evening') === 1, out);
  check('wrong item: shows the student\'s own answer', out.includes('night'), out);
  check('wrong item: labels the student answer ("Your answer")', /Your answer/i.test(out), out);
  check('wrong item: labels the correct answer ("Correct answer")', /Correct answer/i.test(out), out);
  check('wrong item: NOT the doubled "Correct answer: X — Correct answer: X"',
    !/Correct answer.*Correct answer/i.test(out), out);
}

// ── 1b. The literal reported string can never render again ───────────────────
{
  // Simulate the OLD server payload that still embeds the answer in feedback.
  const it = { skill: 'vocab', correct: 0, expected: 'has', answer: 'have', feedback: 'Correct answer: has' };
  const out = I._reviewDetail(it, false);
  check('legacy feedback carrying the answer does NOT double it',
    count(out, '>has<') <= 1 && !/Correct answer:\s*<bdi[^>]*>has<\/bdi>\s*—\s*Correct answer:\s*has/i.test(out),
    out);
  check('legacy case still shows the student answer "have"', out.includes('have'), out);
}

// ── 2. A correct item ────────────────────────────────────────────────────────
{
  const it = { skill: 'vocab', correct: 1, expected: 'name', answer: 'name', feedback: '' };
  const out = I._reviewDetail(it, true);
  check('correct item: friendly confirmation, no "Correct answer:" label',
    /صح|Correct!/.test(out) && !/Correct answer/i.test(out), out);
}

// ── 3. Audio / writing items (no single expected word) ───────────────────────
{
  const sp = { skill: 'speaking', correct: 1, expected: '', answer: 'I wake up at 7.',
               feedback: "Nice effort — keep using this week's words." };
  const out = I._reviewDetail(sp, true);
  check('speaking: shows the supplementary note', out.includes('Nice effort'), out);
  check('speaking: does not fabricate a "Correct answer" line',
    !/Correct answer/i.test(out), out);
}
{
  const pend = { skill: 'pronunciation', correct: 0, expected: '', answer: '',
                 feedback: '__pending_review__' };
  const out = I._reviewDetail(pend, false);
  check('pending-review sentinel is never shown to the student',
    !out.includes('__pending_review__'), out);
}

// ── 4. Graceful with older payloads that lack `answer` ───────────────────────
{
  const it = { skill: 'listening', correct: 0, expected: 'eleven' }; // no answer field
  const out = I._reviewDetail(it, false);
  check('missing answer: still shows the correct answer once',
    count(out, 'eleven') === 1 && /Correct answer/i.test(out), out);
  check('missing answer: does not print "Your answer:" with nothing',
    !/Your answer[^<]*:\s*<bdi[^>]*><\/bdi>/i.test(out), out);
}

// ── 5. HTML in a student's answer must be escaped ────────────────────────────
{
  const it = { skill: 'vocab', correct: 0, expected: 'cat', answer: '<img src=x onerror=alert(1)>', feedback: '' };
  const out = I._reviewDetail(it, false);
  check('student answer is HTML-escaped (no raw <img)',
    !out.includes('<img') && out.includes('&lt;img'), out);
}

console.log(fails === 0
  ? '\nALL REVIEW-DETAIL CHECKS PASSED'
  : `\n${fails} CHECK(S) FAILED`);
process.exit(fails === 0 ? 0 : 1);
