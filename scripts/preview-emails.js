#!/usr/bin/env node
/**
 * Renders every email the factory can send, from the GENERATED workflow JSON and the
 * real fixtures captured from live runs, into previews/*.html. Open them in a browser.
 * Doubles as a test: any composer that throws on real data fails here, not at 3 a.m.
 *
 *   node scripts/preview-emails.js
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..');
const OUT = path.join(ROOT, 'previews');
const fx = (f) => JSON.parse(fs.readFileSync(path.join(ROOT, 'fixtures', f), 'utf8'));
const wfCode = (file, node) => {
  const wf = JSON.parse(fs.readFileSync(path.join(ROOT, file), 'utf8'));
  const n = wf.nodes.find((x) => x.name === node);
  assert(n, node + ' missing from ' + file);
  return n.parameters.jsCode;
};

const analysis = fx('analysis-output.json');
const content = fx('content-output.json');
const media = fx('media-output.json');
const cfg = fx('research-input.json').config;

const nodes = {
  'Normalize Request': { topic: 'Red light therapy (photobiomodulation) for exercise recovery' },
  Config: cfg,
  'Create Course': { version_id: 3, course_id: 1, version: 3, slug: 'red-light-therapy-photobiomodulation-for-exercise-recovery' },
  'Analyse Evidence': analysis,
  'Build Course Content': content,
  'Produce Media': media,
  'Normalize Decision': { decision: 'approved', comments: 'Looks good. Please add a slide on contraindications for pregnancy next time.', channel: 'gmail' },
  'Mark Failed': { failure: 'Course render failed: narration is 3412 characters, over MAX_TTS_CHARS=3000.' },
  'Keep New Sources': { failed: [] },
  'Error Trigger': { workflow: { name: 'GymRamp · Course Factory' }, execution: { id: 812, lastNodeExecuted: 'Produce Media', url: 'http://localhost:5678/workflow/x/executions/812', error: { message: 'Worker unreachable: connect ECONNREFUSED 127.0.0.1:8100' } } },
};

function run(code, input, overrides = {}) {
  const all = { ...nodes, ...overrides };
  const $ = (name) => ({ first: () => ({ json: all[name] }), isExecuted: name in all });
  const $input = { first: () => ({ json: input }), all: () => [{ json: input }] };
  return new Function('$', '$input', '$workflow', '$execution', code)($, $input, { id: 'wf1' }, { id: 812 })[0].json;
}

fs.mkdirSync(OUT, { recursive: true });
const write = (name, out) => {
  assert(out.subject && out.html && out.html.startsWith('<!DOCTYPE html>'), name + ': missing subject or html');
  assert(!/undefined|NaN|\[object Object\]/.test(out.html), name + ': leaked undefined/NaN/[object Object]');
  const html = out.html.replace('%%REVIEW_URL%%', 'https://example.invalid/form-waiting/812');
  fs.writeFileSync(path.join(OUT, name + '.html'), html);
  console.log('  ' + name.padEnd(16) + (Buffer.byteLength(html) / 1024).toFixed(1).padStart(6) + ' KB  ' + out.subject);
};

// Flag the analysis for the review preview, so the warning banner is rendered too.
const flagged = { ...analysis, analysis: { ...analysis.analysis, decision: 'flag_review' } };
write('review', run(wfCode('factory.workflow.json', 'Build Review Message'), {}, { 'Analyse Evidence': flagged }));
write('not-produced', run(wfCode('factory.workflow.json', 'Write Not Produced Email'), {}, { 'Analyse Evidence': flagged }));
write('gate-blocked', run(wfCode('factory.workflow.json', 'Write Gate Blocked Email'), {}));
write('published', run(wfCode('factory.workflow.json', 'Write Published Email'), {}));
write('failure', run(wfCode('factory.workflow.json', 'Write Failure Email'), {}));
write('radar-digest', run(wfCode('radar.workflow.json', 'Build Digest'), {
  runs: [{ topic: 'Red light therapy / photobiomodulation', found: 42, new: 6 }, { topic: 'Sauna and thermal therapy', found: 38, new: 0 }],
  findings: [{ topic: 'Red light therapy / photobiomodulation', decision: 'update_course', rationale: 'Two new randomised trials in trained athletes add delayed-recovery data the current course does not cover.' }],
}));
write('workflow-error', run(wfCode('errors.workflow.json', 'Write Error Email'), { marked: 1 }));
console.log('\npreviews written to ' + OUT);
