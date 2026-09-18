/**
 * Shared helpers for the GymRamp scripts: n8n API access and project paths.
 * One copy, so a fix lands everywhere at once.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const MCP_JSON = path.join(ROOT, '..', '..', '.mcp.json');
const CONFIG = path.join(ROOT, 'config', 'deploy.config.json');
const DEPLOYED = path.join(ROOT, 'config', 'deployed.json');

function n8nConfig() {
  if (process.env.N8N_API_URL && process.env.N8N_API_KEY) {
    return { url: process.env.N8N_API_URL, key: process.env.N8N_API_KEY };
  }
  if (!fs.existsSync(MCP_JSON)) {
    throw new Error('Set N8N_API_URL and N8N_API_KEY (no ' + MCP_JSON + ' to fall back on).');
  }
  const e = JSON.parse(fs.readFileSync(MCP_JSON, 'utf8')).mcpServers['n8n-local'].env;
  return { url: e.N8N_API_URL, key: e.N8N_API_KEY };
}

async function api(cfg, method, route, body) {
  const res = await fetch(cfg.url + route, {
    method,
    headers: { 'X-N8N-API-KEY': cfg.key, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(method + ' ' + route + ' -> ' + res.status + ': ' + text.slice(0, 800));
  return text ? JSON.parse(text) : null;
}

function readJson(file, fallback) {
  return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : fallback;
}

module.exports = { ROOT, CONFIG, DEPLOYED, n8nConfig, api, readJson };
