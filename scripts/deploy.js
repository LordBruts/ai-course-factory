#!/usr/bin/env node
/**
 * Deploys the seven GymRamp workflows to the local n8n instance. All stay INACTIVE.
 *
 *   node scripts/deploy.js            # create or update, in dependency order
 *   node scripts/deploy.js --verify   # read the live workflows back and audit them
 *
 * Dependency order, because an Execute Workflow node needs an id that exists:
 *   errors -> research, analysis, content, media -> factory -> radar
 * n8n accepts a literal "__WF_RESEARCH__" as a workflow id and fails only at runtime,
 * so nothing is sent while a placeholder remains.
 *
 * Credentials are attached here by node TYPE (exports carry none). A full update
 * replaces the nodes array and silently drops any credential missing from the
 * payload, which is why every deploy re-attaches all of them.
 *
 * Optional integrations (Slack review, Supabase Storage) deploy without a credential
 * until one exists in config/deploy.config.json; they are reported, not fatal, because
 * their branches are switched off in Config.
 */

const fs = require('fs');
const path = require('path');
const { ROOT, CONFIG, DEPLOYED, n8nConfig, api, readJson } = require('./lib');

const ORDER = ['errors', 'research', 'analysis', 'content', 'media', 'factory', 'radar'];
const PLACEHOLDER = {
  __WF_ERRORS__: 'errors', __WF_RESEARCH__: 'research', __WF_ANALYSIS__: 'analysis',
  __WF_CONTENT__: 'content', __WF_MEDIA__: 'media', __WF_FACTORY__: 'factory',
};
const OPTIONAL = Symbol('optional');

function credentialsFor(node, c) {
  const p = node.parameters || {};
  switch (node.type) {
    case 'n8n-nodes-base.postgres': return { postgres: c.postgres };
    case '@n8n/n8n-nodes-langchain.lmChatOpenRouter': return { openRouterApi: c.openRouter };
    case 'n8n-nodes-base.gmail': return { gmailOAuth2: c.gmail };
    case 'n8n-nodes-base.webhook': return p.authentication === 'headerAuth' ? { httpHeaderAuth: c.webhookToken } : null;
    case 'n8n-nodes-base.formTrigger': return p.authentication === 'basicAuth' ? { httpBasicAuth: c.formLogin } : null;
    // The review form behind the approval email is protected by the same login as the request form.
    case 'n8n-nodes-base.wait': return p.incomingAuthentication === 'basicAuth' ? { httpBasicAuth: c.formLogin } : null;
    case 'n8n-nodes-base.slack': return c.slack ? { slackApi: c.slack } : OPTIONAL;
    case 'n8n-nodes-base.httpRequest':
      if (p.nodeCredentialType === 'supabaseApi') return c.supabase ? { supabaseApi: c.supabase } : OPTIONAL;
      return null;
    default: return null;
  }
}

function prepare(key, ids, creds) {
  let text = fs.readFileSync(path.join(ROOT, key + '.workflow.json'), 'utf8');
  for (const [ph, dep] of Object.entries(PLACEHOLDER)) {
    if (text.includes(ph)) {
      if (!ids[dep]) throw new Error(key + ' needs ' + dep + ' deployed first (' + ph + ')');
      text = text.split(ph).join(ids[dep]);
    }
  }
  const left = text.match(/__WF_[A-Z]+__/g);
  if (left) throw new Error(key + ': unsubstituted placeholders ' + [...new Set(left)].join(', '));
  const wf = JSON.parse(text);
  const optionalMissing = [];
  for (const node of wf.nodes) {
    const want = credentialsFor(node, creds);
    if (want === OPTIONAL) {
      optionalMissing.push(node.name);
      // n8n refuses to PUBLISH a workflow containing a Slack node with no credential
      // ("Missing required credential: slackApi"), even when its branch never runs.
      // Disabled until a credential exists. This fails closed: a disabled Slack node sends no
      // review link, so the Wait form is never submitted and the review expires, never approves.
      if (node.type === 'n8n-nodes-base.slack') node.disabled = true;
      continue;
    }
    if (!want) continue;
    for (const [type, ref] of Object.entries(want)) {
      if (!ref || !ref.id) throw new Error(key + ': no credential id for ' + type + ' (node "' + node.name + '")');
    }
    node.credentials = Object.fromEntries(Object.entries(want).map(([t, r]) => [t, { id: r.id, name: r.name }]));
  }
  return { wf, optionalMissing };
}

function audit(live, creds) {
  const problems = [];
  const optional = [];
  for (const n of live.nodes) {
    const want = credentialsFor(n, creds);
    const has = n.credentials && Object.keys(n.credentials).length;
    if (want === OPTIONAL) { if (!has) optional.push(n.name); continue; }
    if (want && !has) problems.push('no credential on "' + n.name + '"');
  }
  const text = JSON.stringify(live);
  const left = text.match(/__WF_[A-Z]+__/g);
  if (left) problems.push('placeholder left: ' + [...new Set(left)].join(', '));
  return { problems, optional };
}

async function main() {
  const cfg = n8nConfig();
  const creds = readJson(CONFIG, null);
  if (!creds) throw new Error('config/deploy.config.json missing -- run scripts/create-credentials.js first');
  const ids = readJson(DEPLOYED, {});
  const verify = process.argv.includes('--verify');
  let failed = false;

  for (const key of ORDER) {
    if (verify) {
      if (!ids[key]) { console.log(key.padEnd(9) + ' not deployed'); failed = true; continue; }
      const live = await api(cfg, 'GET', '/api/v1/workflows/' + ids[key]);
      const links = Object.values(live.connections).reduce((n, byType) => n + Object.values(byType).flat(2).length, 0);
      const { problems, optional } = audit(live, creds);
      console.log(key.padEnd(9) + ' ' + ids[key] + '  ' + String(live.nodes.length).padStart(2) + ' nodes ' +
        String(links).padStart(2) + ' links  active=' + live.active + '  ' + live.name);
      problems.forEach((p) => console.log('          PROBLEM ' + p));
      if (optional.length) console.log('          optional, no credential yet: ' + optional.join(', '));
      if (problems.length) failed = true;
      continue;
    }

    const { wf, optionalMissing } = prepare(key, ids, creds);
    const payload = { name: wf.name, nodes: wf.nodes, connections: wf.connections, settings: wf.settings };
    let live;
    if (ids[key]) {
      live = await api(cfg, 'PUT', '/api/v1/workflows/' + ids[key], payload);
      console.log('updated ' + key.padEnd(9) + live.id + '  ' + live.name);
    } else {
      live = await api(cfg, 'POST', '/api/v1/workflows', payload);
      ids[key] = live.id;
      fs.writeFileSync(DEPLOYED, JSON.stringify(ids, null, 2) + '\n');
      console.log('created ' + key.padEnd(9) + live.id + '  ' + live.name);
    }
    const back = await api(cfg, 'GET', '/api/v1/workflows/' + ids[key]);
    const { problems } = audit(back, creds);
    if (back.nodes.length !== wf.nodes.length) problems.push('node count ' + back.nodes.length + ' != ' + wf.nodes.length);
    problems.forEach((p) => console.log('          PROBLEM ' + p));
    if (optionalMissing.length) console.log('          optional, no credential yet: ' + optionalMissing.join(', '));
    if (problems.length) failed = true;
  }
  process.exitCode = failed ? 1 : 0;
}

module.exports = { prepare, ORDER };

if (require.main === module) {
  main().catch((e) => { console.error(e.message); process.exit(1); });
}
