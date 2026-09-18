#!/usr/bin/env node
/**
 * Regression suite for the Citation & Claim Gate.
 *
 * Tests the GENERATED ARTIFACT: the gate's jsCode is pulled out of
 * content.workflow.json, so the test cannot drift from what deploys. n8n's
 * globals are mocked; $input THROWS, because the gate must read named nodes and
 * a helpful $input mock would hide a wiring mistake.
 *
 * Includes negative cases on purpose: a gate that rejects everything passes a
 * positive-only suite and is just as useless as one that rejects nothing.
 *
 *   node scripts/test-gate.js
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const wf = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'content.workflow.json'), 'utf8'));
const gateNode = wf.nodes.find((n) => n.name === 'Citation & Claim Gate');
assert(gateNode, 'Citation & Claim Gate node missing from content.workflow.json');

// Wiring: the gate must sit directly after Write Assessments.
const into = Object.entries(wf.connections).filter(([, c]) => (c.main || []).flat().some((t) => t.node === gateNode.name)).map(([f]) => f);
assert.deepStrictEqual(into, ['Write Assessments'], 'gate is fed by ' + into.join(', '));

const EVIDENCE = [
  { marker: 'E01', source_id: 101, citation: 'Alpha, A. (2022). Study one. J Test. https://doi.org/10.1/a', url: 'https://doi.org/10.1/a' },
  { marker: 'E02', source_id: 102, citation: 'Beta, B. (2023). Study two. J Test. https://doi.org/10.1/b', url: 'https://doi.org/10.1/b' },
  { marker: 'E03', source_id: 103, citation: 'Gamma, C. (2024). Study three. J Test. https://doi.org/10.1/c', url: 'https://doi.org/10.1/c' },
];

const q = (answer_index = 0, markers = ['E01']) => ({
  question: 'Which is correct?', options: ['A one', 'B two', 'C three', 'D four'], answer_index, rationale: 'Because.', markers,
});

function baseScript() {
  return {
    title: 'Red Light Therapy for Recovery',
    subtitle: 'Evidence and practice',
    learning_objectives: ['Explain PBM', 'Screen members', 'Describe evidence'],
    intro_notes: 'Welcome to this course on red light therapy.',
    slides: [
      { title: 'What it is', bullets: ['Red and near-infrared light [E02]', 'Applied to skin'], notes: 'Photobiomodulation applies red or near-infrared light to tissue [E02].' },
      { title: 'Evidence', bullets: ['Findings are mixed', 'Protocols vary'], notes: 'Some trials reported less muscle soreness after exercise [E01, E03]. Results differ between studies [E01].' },
      { title: 'Safety', bullets: ['Screen for photosensitivity', 'Refer medical questions'], notes: 'Ask members about light sensitivity and refer medical questions to a clinician.' },
    ],
    takeaways: ['Evidence is promising but mixed', 'Screen before use', 'Stay in scope'],
    takeaways_notes: 'Evidence is promising but mixed, so describe it honestly.',
  };
}
function baseAssess() {
  return {
    worksheet: { title: 'Worksheet', instructions: 'Answer.', sections: [{ heading: 'Understanding', prompts: ['Define PBM.'] }] },
    quiz: { title: 'Quiz', instructions: 'Choose one.', questions: [q(0), q(1, [])] },
    exam: { title: 'Exam', instructions: 'Choose one.', pass_mark_percent: 80, questions: [q(2, ['E02']), q(3)] },
  };
}

function runGate(script, assess, cfg = {}) {
  const nodes = {
    Start: { topic: 'Red light therapy', slug: 'red-light', version: 1, audience: 'Trainers', evidence: EVIDENCE, config: { max_tts_chars: 3000, ...cfg } },
    'Write Course Script': script,
    'Write Assessments': assess,
  };
  const $ = (name) => {
    if (!(name in nodes)) throw new Error('gate referenced unexpected node ' + name);
    return { first: () => ({ json: nodes[name] }), isExecuted: true };
  };
  const $input = { first() { throw new Error('gate must not read $input'); }, all() { throw new Error('gate must not read $input'); } };
  const fn = new Function('$', '$input', gateNode.parameters.jsCode);
  return fn($, $input)[0].json;
}

const codes = (out) => out.gate.blocking.map((b) => b.code);
let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log('  ok   ' + name); }
  catch (e) { console.log('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; }
}

console.log('Citation & Claim Gate');

test('clean course passes', () => {
  const out = runGate(baseScript(), baseAssess());
  assert.deepStrictEqual(out.gate.blocking, [], JSON.stringify(out.gate.blocking));
  assert.strictEqual(out.gate.passed, true);
});

test('markers renumber by first appearance and references are computed', () => {
  const out = runGate(baseScript(), baseAssess());
  assert.deepStrictEqual(out.references.map((r) => r.marker), ['E02', 'E01', 'E03']);
  assert.strictEqual(out.package.slides[0].bullets[0], 'Red and near-infrared light [1]');
  assert.strictEqual(out.package.slides[1].notes, 'Some trials reported less muscle soreness after exercise [2, 3]. Results differ between studies [2].');
  assert.deepStrictEqual(out.package.slides[1].refs, [2, 3]);
  assert.strictEqual(out.package.references[0].citation, EVIDENCE[1].citation);
});

test('output nested under .output (Agent shape) is read too', () => {
  const out = runGate({ output: baseScript() }, { output: baseAssess() });
  assert.strictEqual(out.gate.passed, true);
  assert.strictEqual(out.package.slides.length, 3);
});

test('claims are recorded with their source markers', () => {
  const out = runGate(baseScript(), baseAssess());
  const cited = out.claims.filter((c) => c.status === 'cited');
  assert(cited.some((c) => c.slide_no === 2 && c.markers.join() === 'E01,E03'));
});

const mutate = (fn) => { const s = baseScript(); fn(s); return s; };

test('BLOCKS an unknown marker', () => {
  const out = runGate(mutate((s) => { s.slides[0].notes += ' It also improves sleep [E09].'; }), baseAssess());
  assert(codes(out).includes('UNKNOWN_MARKER'), codes(out).join());
  assert(!out.package.slides[0].notes.includes('E09'));
});

test('BLOCKS an uncited statistic', () => {
  const out = runGate(mutate((s) => { s.slides[1].notes = 'Soreness dropped by 30% after sessions.'; }), baseAssess());
  assert(codes(out).includes('UNCITED_STATISTIC'), codes(out).join());
});

test('allows a CITED statistic', () => {
  const out = runGate(mutate((s) => { s.slides[1].notes = 'One trial reported 30% less soreness [E01].'; }), baseAssess());
  assert(!codes(out).includes('UNCITED_STATISTIC'), codes(out).join());
});

test('BLOCKS a cure promise even when cited', () => {
  const out = runGate(mutate((s) => { s.slides[1].notes = 'Red light cures tendon pain [E01].'; }), baseAssess());
  assert(codes(out).includes('CURE_PROMISE'), codes(out).join());
});

test('BLOCKS invented first-person experience', () => {
  const out = runGate(mutate((s) => { s.slides[2].notes = 'Our members recover twice as fast.'; }), baseAssess());
  assert(codes(out).includes('INVENTED_EXPERIENCE'), codes(out).join());
});

test('BLOCKS an author-year citation the writer made up', () => {
  const out = runGate(mutate((s) => { s.slides[1].notes = 'Soreness was lower (Smith et al., 2020).'; }), baseAssess());
  assert(codes(out).includes('FREETEXT_CITATION'), codes(out).join());
});

test('BLOCKS a medication instruction', () => {
  const out = runGate(mutate((s) => { s.slides[2].notes = 'Clients should stop taking medication before sessions.'; }), baseAssess());
  assert(codes(out).includes('MEDICATION_INSTRUCTION'), codes(out).join());
});

test('BLOCKS an uncited dose, advises on a cited one', () => {
  const blocked = runGate(mutate((s) => { s.slides[2].notes = 'Give 500 mg of vitamin C first.'; }), baseAssess());
  assert(codes(blocked).includes('DOSE_STATED'), codes(blocked).join());
  const cited = runGate(mutate((s) => { s.slides[2].notes = 'One study gave 500 mg of vitamin C [E01].'; }), baseAssess());
  assert(!codes(cited).includes('DOSE_STATED'));
  assert(cited.gate.advisory.some((a) => a.code === 'DOSE_STATED'));
});

test('BLOCKS narration over the TTS budget before any spend', () => {
  const out = runGate(mutate((s) => { s.slides[2].notes = 'Refer medical questions to a clinician. '.repeat(90); }), baseAssess());
  assert(codes(out).includes('NARRATION_TOO_LONG'), codes(out).join());
});

test('BLOCKS an out-of-range answer index', () => {
  const a = baseAssess();
  a.exam.questions[0].answer_index = 7;
  assert(codes(runGate(baseScript(), a)).includes('QUESTION_INVALID'));
});

test('BLOCKS a course that cites nothing', () => {
  const s = mutate((x) => { x.slides.forEach((sl) => { sl.notes = 'Refer medical questions to a clinician.'; sl.bullets = ['Screen members', 'Stay in scope']; }); });
  const a = baseAssess();
  [...a.quiz.questions, ...a.exam.questions].forEach((qq) => { qq.markers = []; });
  assert(codes(runGate(s, a)).includes('NO_CITATIONS'));
});

test('flags an uncited outcome claim as ADVISORY, not blocking', () => {
  const out = runGate(mutate((s) => { s.slides[2].notes = 'Many people find it improves how they feel.'; }), baseAssess());
  assert(out.gate.passed, codes(out).join());
  assert(out.gate.advisory.some((a) => a.code === 'UNCITED_CLAIM'));
});

test('allows a NEGATED cure statement', () => {
  const out = runGate(mutate((s) => { s.slides[2].bullets[0] = 'Describe PBM as a recovery service, not a cure'; }), baseAssess());
  assert(!codes(out).includes('CURE_PROMISE'), codes(out).join());
});

test('allows NOT GUARANTEED (live run 2 false positive)', () => {
  const out = runGate(mutate((s) => { s.slides[1].bullets[0] = 'Benefits are not guaranteed across outcomes [E03, E01]'; }), baseAssess());
  assert(!codes(out).includes('CURE_PROMISE'), codes(out).join());
  const bad = runGate(mutate((s) => { s.slides[1].bullets[0] = 'Results are guaranteed for every client'; }), baseAssess());
  assert(codes(bad).includes('CURE_PROMISE'), 'an unnegated guarantee must still block');
});

test('a marker placed after the full stop stays with its own sentence', () => {
  const out = runGate(mutate((s) => { s.slides[1].notes = 'Some trials reported less soreness. [E01] Results differ between studies. [E03]'; }), baseAssess());
  assert.strictEqual(out.package.slides[1].notes, 'Some trials reported less soreness [2]. Results differ between studies [3].');
  assert(!out.gate.advisory.some((a) => a.code === 'UNCITED_CLAIM' && a.where === 'slide 2'), JSON.stringify(out.gate.advisory));
});

// ---- real payload: execution 711, the first live run of Build Course Content ----
const FIX = path.join(__dirname, '..', 'fixtures');
if (fs.existsSync(path.join(FIX, 'real-write-course-script.json'))) {
  const real = (f) => JSON.parse(fs.readFileSync(path.join(FIX, f), 'utf8'));
  test('REAL payload (exec 711): passes, cites real sources, every slide narrated', () => {
    const start = real('real-content-start.json');
    const nodes = { Start: start, 'Write Course Script': real('real-write-course-script.json'), 'Write Assessments': real('real-write-assessments.json') };
    const $ = (name) => ({ first: () => ({ json: nodes[name] }), isExecuted: true });
    const out = new Function('$', '$input', gateNode.parameters.jsCode)($, { first() { throw new Error('no $input'); } })[0].json;
    assert.deepStrictEqual(out.gate.blocking, [], JSON.stringify(out.gate.blocking));
    const known = new Set(start.evidence.map((e) => e.marker));
    assert(out.references.length >= 3 && out.references.every((r) => known.has(r.marker)));
    assert(out.package.slides.every((s) => s.notes.length > 0));
    // The trailing-marker fix: on the raw payload 4 slides looked uncited.
    const uncited = out.gate.advisory.filter((a) => a.code === 'UNCITED_CLAIM').length;
    assert(uncited <= 1, uncited + ' uncited-claim advisories: ' + JSON.stringify(out.gate.advisory));
  });
}

if (fs.existsSync(path.join(FIX, 'real2-content-nodes.json'))) {
  test('REAL payload (exec 716, first end-to-end run): passes after the "not guaranteed" fix', () => {
    const nodes = JSON.parse(fs.readFileSync(path.join(FIX, 'real2-content-nodes.json'), 'utf8'));
    const $ = (name) => ({ first: () => ({ json: nodes[name] }), isExecuted: true });
    const out = new Function('$', '$input', gateNode.parameters.jsCode)($, { first() { throw new Error('no $input'); } })[0].json;
    assert.deepStrictEqual(out.gate.blocking, [], JSON.stringify(out.gate.blocking));
    assert(out.gate.stats.narration_chars <= 3000);
  });
}

console.log('\n' + passed + ' passed' + (process.exitCode ? ', some FAILED' : ''));
