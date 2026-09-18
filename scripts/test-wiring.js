#!/usr/bin/env node
/**
 * Structural checks that validate_workflow does not make, run on every export:
 *
 *   - every node with onError=continueErrorOutput has its error output (main[1]) wired;
 *   - every Switch with fallbackOutput 'extra' has rules + 1 outputs, all wired;
 *   - every IF has its true output wired;
 *   - no orphan nodes (AI sub-nodes count as wired through their ai_* links);
 *   - the Course Factory reaches human review before anything can be published.
 *
 *   node scripts/test-wiring.js
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
let failures = 0;
const fail = (wf, msg) => { failures++; console.log('  FAIL ' + wf + ': ' + msg); };

for (const file of fs.readdirSync(ROOT).filter((f) => f.endsWith('.workflow.json'))) {
  const wf = JSON.parse(fs.readFileSync(path.join(ROOT, file), 'utf8'));
  const out = (name) => wf.connections[name] || {};
  const wired = new Set();
  for (const [from, byType] of Object.entries(wf.connections)) {
    for (const ports of Object.values(byType)) for (const port of ports) for (const t of port) { wired.add(from); wired.add(t.node); }
  }

  for (const n of wf.nodes) {
    const main = out(n.name).main || [];
    if (!wired.has(n.name)) fail(wf.name, 'orphan node "' + n.name + '"');
    if (n.onError === 'continueErrorOutput' && !(main[1] && main[1].length)) {
      fail(wf.name, '"' + n.name + '" has continueErrorOutput but main[1] is not wired');
    }
    if (n.type === 'n8n-nodes-base.switch') {
      const rules = n.parameters.rules.values.length;
      const expected = rules + (n.parameters.options.fallbackOutput === 'extra' ? 1 : 0);
      for (let i = 0; i < expected; i++) if (!(main[i] && main[i].length)) fail(wf.name, 'Switch "' + n.name + '" output ' + i + ' of ' + expected + ' not wired');
    }
    if (n.type === 'n8n-nodes-base.if' && !(main[0] && main[0].length)) fail(wf.name, 'IF "' + n.name + '" true output not wired');
  }

  if (wf.name === 'GymRamp HF · Course Factory') {
    // Walk forward from the triggers WITHOUT passing through the approval nodes. If the
    // LMS publish is still reachable, something can publish without a human.
    const blocked = new Set(['Wait For Decision']);
    const seen = new Set();
    const stack = ['Course Request Webhook', 'Course Request Form', 'Called By Radar'];
    while (stack.length) {
      const name = stack.pop();
      if (seen.has(name) || blocked.has(name)) continue;
      seen.add(name);
      for (const port of out(name).main || []) for (const t of port) stack.push(t.node);
    }
    if (seen.has('Publish To LMS (Mock)')) fail(wf.name, 'Publish To LMS is reachable without passing human approval');
  }
  console.log('  checked ' + file.padEnd(26) + wf.nodes.length + ' nodes');
}

console.log(failures ? '\n' + failures + ' wiring failure(s)' : '\nwiring ok');
process.exitCode = failures ? 1 : 0;
