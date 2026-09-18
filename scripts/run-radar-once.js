#!/usr/bin/env node
/**
 * Runs the Research Radar ONCE, now, without activating the real (schedule-only) workflow.
 *
 *   node scripts/run-radar-once.js
 *
 * There is no "execute workflow" endpoint in the public API, and n8n_test_workflow only
 * drives webhook/form/chat triggers. So this deploys a temporary copy of the radar with
 * its Schedule trigger swapped for a Webhook, runs it to completion, prints what the
 * database recorded, and deletes the copy. The real radar is never touched or activated.
 *
 * Side effects are real: Europe PMC / ClinicalTrials.gov searches, OpenRouter calls
 * (planner + analyst, per topic), rows in sources / research_runs / research_findings,
 * and the digest email.
 *
 * Proof of dedupe: run it twice. The second run should report 0 new sources.
 */

const { execFileSync } = require('child_process');
const { CONFIG, DEPLOYED, n8nConfig, api, readJson } = require('./lib');
const { prepare } = require('./deploy');

async function main() {
  const cfg = n8nConfig();
  const { wf } = prepare('radar', readJson(DEPLOYED, {}), readJson(CONFIG, {}));
  const trigger = wf.nodes.find((n) => n.type === 'n8n-nodes-base.scheduleTrigger');
  const hookPath = 'gymramp-radar-once-' + Date.now();
  Object.assign(trigger, {
    type: 'n8n-nodes-base.webhook', typeVersion: 2.1, webhookId: hookPath,
    parameters: { httpMethod: 'POST', path: hookPath, responseMode: 'lastNode', responseData: 'firstEntryJson', options: {} },
  });
  const { errorWorkflow, ...settings } = wf.settings;
  const copy = await api(cfg, 'POST', '/api/v1/workflows', { name: '[RUN ONCE] ' + wf.name, nodes: wf.nodes, connections: wf.connections, settings });
  const t0 = Date.now();
  try {
    await api(cfg, 'POST', '/api/v1/workflows/' + copy.id + '/activate');
    console.log('running radar copy ' + copy.id + ' ...');
    execFileSync('curl', ['-s', '-X', 'POST', cfg.url + '/webhook/' + hookPath, '-H', 'Content-Type: application/json', '-d', '{}', '--max-time', '3000'], { encoding: 'utf8' });
    console.log('finished in ' + Math.round((Date.now() - t0) / 1000) + ' s');
  } finally {
    await api(cfg, 'POST', '/api/v1/workflows/' + copy.id + '/deactivate').catch(() => {});
    if (process.env.KEEP_TEST !== '1') await api(cfg, 'DELETE', '/api/v1/workflows/' + copy.id).catch(() => {});
  }
  const since = new Date(t0 - 5000).toISOString();
  const sql =
    "SELECT topic, found, new_sources FROM research_runs WHERE trigger = 'radar' AND started_at >= '" + since + "' ORDER BY id;" +
    "SELECT decision, topic FROM research_findings WHERE created_at >= '" + since + "' ORDER BY id;";
  console.log(execFileSync('docker', ['exec', 'postgres-db', 'psql', '-U', 'postgres', '-d', 'gymramp', '-c', sql], { encoding: 'utf8' }));
}

main().catch((e) => { console.error(e.message); process.exit(1); });
