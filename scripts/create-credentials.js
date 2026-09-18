#!/usr/bin/env node
/**
 * Creates the n8n credentials this project needs and records their IDs in
 * config/deploy.config.json. Secrets come from the environment and are never
 * written to any file here — the config holds opaque IDs only.
 *
 *   GYMRAMP_PG_PASSWORD=... node scripts/create-credentials.js            # local Postgres
 *   GYMRAMP_PG_HOST=db.xxx.supabase.co GYMRAMP_PG_PORT=6543 \
 *   GYMRAMP_PG_USER=postgres.xxx GYMRAMP_PG_DB=postgres GYMRAMP_PG_SSL=require \
 *   GYMRAMP_PG_PASSWORD=... node scripts/create-credentials.js            # Supabase
 *
 * Optional, for the Supabase Storage branch:
 *   SUPABASE_URL=https://xxx.supabase.co SUPABASE_SERVICE_ROLE_KEY=... node scripts/create-credentials.js --supabase-only
 *
 * Trigger secrets (webhook header token + form login), generated here, never typed:
 *   node scripts/create-credentials.js --triggers
 * writes them to config/secrets.local.env (gitignored) so you can call the webhook and
 * open the form. The credentials themselves hold the only other copy.
 *
 * Re-running creates duplicates: the public API cannot list credentials to dedupe.
 * Existing credentials reused, not created: OpenRouter and Gmail.
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { n8nConfig, api, CONFIG, ROOT } = require('./lib');

const EXISTING = {
  openRouter: { id: 'zrETA1O6eoO0xBUF', name: 'Lord Bruts OpenRouter' },
  gmail: { id: 'H7MFx0EeirSXxK8m', name: 'Bruts Almighty' },
};

function need(name) {
  const v = process.env[name];
  if (!v) {
    console.error('Missing required environment variable: ' + name);
    process.exit(1);
  }
  return v;
}

async function create(cfg, name, type, data) {
  const res = await api(cfg, 'POST', '/api/v1/credentials', { name, type, data });
  console.log('  created ' + type.padEnd(12) + ' id=' + res.id + '  "' + name + '"');
  return { id: res.id, name };
}

async function main() {
  const cfg = n8nConfig();
  const out = fs.existsSync(CONFIG) ? JSON.parse(fs.readFileSync(CONFIG, 'utf8')) : {};
  Object.assign(out, EXISTING);

  if (process.argv.includes('--triggers')) {
    const token = crypto.randomBytes(24).toString('base64url');
    const password = crypto.randomBytes(12).toString('base64url');
    out.webhookToken = await create(cfg, 'GymRamp Webhook Token', 'httpHeaderAuth', { name: 'X-GymRamp-Token', value: token });
    out.formLogin = await create(cfg, 'GymRamp Form Login', 'httpBasicAuth', { user: 'gymramp', password });
    const file = path.join(ROOT, 'config', 'secrets.local.env');
    const lines = [
      '# GymRamp trigger secrets. Gitignored. The n8n credentials hold the only other copy.',
      'GYMRAMP_WEBHOOK_HEADER=X-GymRamp-Token',
      'GYMRAMP_WEBHOOK_TOKEN=' + token,
      'GYMRAMP_FORM_USER=gymramp',
      'GYMRAMP_FORM_PASSWORD=' + password,
    ];
    fs.writeFileSync(file, lines.join(String.fromCharCode(10)) + String.fromCharCode(10));
    console.log('wrote config/secrets.local.env');
  } else if (!process.argv.includes('--supabase-only')) {
    const host = process.env.GYMRAMP_PG_HOST || 'host.docker.internal';
    // GYMRAMP_PG_CRED_NAME lets this build (the -hyperframe duplicate) create its own
    // credential against database gymramp_hf without touching the original's.
    out.postgres = await create(cfg, process.env.GYMRAMP_PG_CRED_NAME || 'GymRamp Postgres', 'postgres', {
      host,
      // 5433 is the host-side mapping of the local postgres-db container.
      port: Number(process.env.GYMRAMP_PG_PORT || 5433),
      database: process.env.GYMRAMP_PG_DB || 'gymramp',
      user: process.env.GYMRAMP_PG_USER || 'gymramp',
      password: need('GYMRAMP_PG_PASSWORD'),
      ssl: process.env.GYMRAMP_PG_SSL || 'disable',
    });
  }

  if (process.env.SUPABASE_URL && process.env.SUPABASE_SERVICE_ROLE_KEY) {
    out.supabase = await create(cfg, 'GymRamp Supabase', 'supabaseApi', {
      host: process.env.SUPABASE_URL,
      serviceRole: process.env.SUPABASE_SERVICE_ROLE_KEY,
    });
  }

  out.updatedAt = new Date().toISOString();
  fs.mkdirSync(path.dirname(CONFIG), { recursive: true });
  fs.writeFileSync(CONFIG, JSON.stringify(out, null, 2) + '\n');
  console.log('wrote ' + path.relative(process.cwd(), CONFIG));
}

main().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
