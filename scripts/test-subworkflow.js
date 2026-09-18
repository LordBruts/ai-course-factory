#!/usr/bin/env node
/**
 * Runs ONE sub-workflow in isolation against a JSON input and saves its real output.
 *
 *   node scripts/test-subworkflow.js research fixtures/research-input.json fixtures/research-output.json
 *
 * n8n_test_workflow drives only webhook/form/chat triggers, and a sub-workflow starts
 * with an Execute Workflow trigger. So this deploys a temporary copy whose `Start` is a
 * Code node fed by a Webhook, activates it, POSTs the input, saves the response, and
 * deletes the copy -- even when the run fails.
 *
 * Real nodes fire: LLM calls cost money and Postgres writes land. The output file is
 * the fixture for the next stage, copied from a real payload rather than hand-written,
 * because a hand-written fixture agrees with whatever shape the code already assumes.
 *
 * curl, not fetch: Node's fetch gives up on response headers after 300 s, and the
 * content writer can take longer than that.
 */

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { ROOT, CONFIG, DEPLOYED, n8nConfig, api, readJson } = require('./lib');
const { prepare } = require('./deploy');

async function main() {
  const [key, inputFile, outputFile] = process.argv.slice(2);
  if (!key || !inputFile) throw new Error('usage: test-subworkflow.js <key> <input.json> [output.json]');
  const cfg = n8nConfig();
  const { wf } = prepare(key, readJson(DEPLOYED, {}), readJson(CONFIG, {}));

  const start = wf.nodes.find((n) => n.name === 'Start');
  if (!start || start.type !== 'n8n-nodes-base.executeWorkflowTrigger') throw new Error(key + ' has no Execute Workflow Start node');
  const hookPath = 'gymramp-test-' + key + '-' + Date.now();
  start.type = 'n8n-nodes-base.code';
  start.typeVersion = 2;
  start.parameters = { jsCode: 'return [{ json: $input.first().json.body, pairedItem: { item: 0 } }];' };
  wf.nodes.push({
    id: 'test-webhook', name: 'Test Webhook', type: 'n8n-nodes-base.webhook', typeVersion: 2.1,
    position: [start.position[0] - 240, start.position[1]], webhookId: hookPath,
    parameters: { httpMethod: 'POST', path: hookPath, responseMode: 'lastNode', responseData: 'firstEntryJson', options: {} },
  });
  wf.connections['Test Webhook'] = { main: [[{ node: 'Start', type: 'main', index: 0 }]] };

  const { errorWorkflow, ...settings } = wf.settings || {};
  const created = await api(cfg, 'POST', '/api/v1/workflows', {
    name: '[TEST] ' + wf.name, nodes: wf.nodes, connections: wf.connections, settings,
  });
  console.log('temporary workflow ' + created.id);
  const t0 = Date.now();
  try {
    await api(cfg, 'POST', '/api/v1/workflows/' + created.id + '/activate');
    const body = execFileSync('curl', [
      '-s', '-X', 'POST', cfg.url + '/webhook/' + hookPath,
      '-H', 'Content-Type: application/json',
      '--data-binary', '@' + path.resolve(inputFile),
      '--max-time', '1500',
    ], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
    const secs = ((Date.now() - t0) / 1000).toFixed(1);
    let parsed;
    try { parsed = JSON.parse(body); } catch (e) { parsed = { raw: body }; }
    if (outputFile) fs.writeFileSync(outputFile, JSON.stringify(parsed, null, 2) + '\n');
    console.log('finished in ' + secs + ' s' + (outputFile ? ' -> ' + outputFile : ''));
    console.log(JSON.stringify(parsed).slice(0, 600));
  } finally {
    await api(cfg, 'POST', '/api/v1/workflows/' + created.id + '/deactivate').catch(() => {});
    // Kept when KEEP_TEST=1 so a failed execution can be inspected -- deleting a workflow
    // deletes its execution records too, which makes a failure look like it never ran.
    if (process.env.KEEP_TEST !== '1') await api(cfg, 'DELETE', '/api/v1/workflows/' + created.id).catch(() => {});
    else console.log('kept temporary workflow ' + created.id + ' for inspection');
  }
}

main().catch((e) => { console.error(e.message); process.exit(1); });
