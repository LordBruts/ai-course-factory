#!/usr/bin/env node
/**
 * Generates the GymRamp AI Course Factory workflows.   Edit THIS, not the JSON.
 *
 *   node scripts/build-workflows.js
 *
 * Writes one <name>.workflow.json per workflow into the project folder. Code-node
 * bodies come from code/*.js and system prompts from prompts/*.txt, so neither
 * lives as an escaped string inside a JSON blob.
 *
 * Every typeVersion was read off the live n8n 2.32.6 container, not from memory:
 *   postgres 2.7, gmail 2.2, slack 2.5, formTrigger 2.6, webhook 2.1,
 *   executeWorkflow 1.3, executeWorkflowTrigger 1.1, wait 1.1, code 2,
 *   scheduleTrigger 1.3, httpRequest 4.4, if 2.3, switch 3.4, set 3.5,
 *   chainLlm 1.9, lmChatOpenRouter 1, outputParserStructured 1.3.
 *
 * No credentials blocks are emitted -- credential ids are instance-specific and
 * scripts/deploy.js attaches them by node type. Sub-workflow ids are
 * placeholders (__WF_*__) that deploy.js substitutes in dependency order.
 *
 * Build guards (the build refuses to write when any fails):
 *   - a system prompt containing { or } after substitution (LangChain templates);
 *   - a cross-node `).item.json` outside the per-item Supabase branch;
 *   - a connection naming a node that does not exist.
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.join(__dirname, '..');
const CFG = JSON.parse(fs.readFileSync(path.join(ROOT, 'config', 'factory.config.json'), 'utf8'));
const RUNTIME = CFG.runtime;
const MODELS = CFG.models;
const CONTENT = CFG.content;

const readCode = (f) => fs.readFileSync(path.join(ROOT, 'code', f), 'utf8');
const uuid = (seed) => {
  const h = crypto.createHash('sha1').update('gymramp:' + seed).digest('hex');
  return [h.slice(0, 8), h.slice(8, 12), '5' + h.slice(13, 16), '8' + h.slice(17, 20), h.slice(20, 32)].join('-');
};

function prompt(name, vars = {}) {
  let text = fs.readFileSync(path.join(ROOT, 'prompts', name + '.txt'), 'utf8').trim();
  for (const [k, v] of Object.entries(vars)) text = text.split('$$' + k + '$$').join(String(v));
  const left = text.match(/\$\$[A-Z]+\$\$/g);
  if (left) throw new Error('prompt ' + name + ': unsubstituted ' + left.join(', '));
  // n8n evaluates {{ expressions }} before LangChain ever sees the text, so only braces
  // left after removing them are a problem.
  if (/[{}]/.test(text.replace(/{{[^}]*}}/g, ''))) throw new Error('prompt ' + name + ' contains { or } -- LangChain would read it as a template variable');
  return text;
}

// ================================================================ builder ===
function workflow(name, description) {
  const wf = { name, nodes: [], connections: {}, settings: { executionOrder: 'v1' }, _description: description };
  const add = (node) => {
    if (wf.nodes.some((n) => n.name === node.name)) throw new Error(name + ': duplicate node ' + node.name);
    node.id = uuid(name + '/' + node.name);
    wf.nodes.push(node);
    return node.name;
  };
  const link = (from, to, fromIndex = 0, type = 'main') => {
    const c = (wf.connections[from] = wf.connections[from] || {});
    c[type] = c[type] || [];
    while (c[type].length <= fromIndex) c[type].push([]);
    c[type][fromIndex].push({ node: to, type, index: 0 });
  };
  return { wf, add, link };
}

const P = (x, y) => [x * 240, y * 200];

const code = (name, pos, file, extra = {}) => ({
  name, type: 'n8n-nodes-base.code', typeVersion: 2, position: pos,
  parameters: { jsCode: file.endsWith('.js') ? readCode(file) : file }, ...extra,
});

const startTrigger = (pos) => ({
  name: 'Start', type: 'n8n-nodes-base.executeWorkflowTrigger', typeVersion: 1.1, position: pos,
  // passthrough, deliberately: a declared input schema acts as a FILTER that drops any
  // field the caller sends that is not on the list, with no warning. Each caller maps
  // every field explicitly, and the contract is in the workflow description.
  parameters: { inputSource: 'passthrough' },
});

// A single expression resolving to an ARRAY: each element becomes one $n. A plain
// comma-separated string would shred free text (titles, rationales) into extra params.
const pg = (name, pos, query, params, extra = {}) => ({
  name, type: 'n8n-nodes-base.postgres', typeVersion: 2.7, position: pos,
  parameters: {
    operation: 'executeQuery',
    query: Array.isArray(query) ? query.join('\n') : query,
    options: params ? { queryReplacement: '={{ [' + params.map((p) => '(' + p + ') ?? null').join(', ') + '] }}' } : {},
  },
  retryOnFail: true, maxTries: 2, waitBetweenTries: 3000,
  ...extra,
});

const http = (name, pos, parameters, extra = {}) => ({
  name, type: 'n8n-nodes-base.httpRequest', typeVersion: 4.4, position: pos,
  parameters, retryOnFail: true, maxTries: 3, waitBetweenTries: 3000, ...extra,
});

const setRaw = (name, pos, obj) => ({
  name, type: 'n8n-nodes-base.set', typeVersion: 3.5, position: pos,
  parameters: { mode: 'raw', jsonOutput: JSON.stringify(obj, null, 2), options: {} },
});

const setFields = (name, pos, fields, extra = {}) => ({
  name, type: 'n8n-nodes-base.set', typeVersion: 3.5, position: pos,
  parameters: {
    mode: 'manual',
    assignments: { assignments: fields.map(([n, value, type], i) => ({ id: 'f' + i, name: n, value, type })) },
    includeOtherFields: false,
    options: {},
  },
  ...extra,
});

const ifTrue = (name, pos, leftExpr) => ({
  name, type: 'n8n-nodes-base.if', typeVersion: 2.3, position: pos,
  parameters: {
    conditions: {
      options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 3 },
      combinator: 'and',
      conditions: [{ id: 'c0', leftValue: leftExpr, rightValue: '', operator: { type: 'boolean', operation: 'true', singleValue: true } }],
    },
    looseTypeValidation: true,
    options: {},
  },
});

// fallbackOutput 'extra' puts unmatched items on a real port at index rules.length
// instead of the default 'none', which DROPS them silently.
const switchEq = (name, pos, rules) => ({
  name, type: 'n8n-nodes-base.switch', typeVersion: 3.4, position: pos,
  parameters: {
    mode: 'rules',
    rules: {
      values: rules.map((r) => ({
        conditions: {
          options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 3 },
          combinator: 'and',
          conditions: [{ id: r.key, leftValue: r.left, rightValue: r.right, operator: { type: 'string', operation: 'equals' } }],
        },
        renameOutput: true,
        outputKey: r.key,
      })),
    },
    looseTypeValidation: true,
    options: { fallbackOutput: 'extra' },
  },
});

const execWf = (name, pos, placeholder, inputs, extra = {}) => ({
  name, type: 'n8n-nodes-base.executeWorkflow', typeVersion: 1.3, position: pos,
  parameters: {
    workflowId: { __rl: true, mode: 'id', value: placeholder },
    workflowInputs: {
      mappingMode: 'defineBelow',
      value: inputs,
      matchingColumns: [], schema: [], attemptToConvertTypes: false, convertFieldsToString: false,
    },
    mode: extra.mode || 'once',
    options: { waitForSubWorkflow: extra.wait !== false },
  },
  ...(extra.node || {}),
});

// Every email is HTML, composed upstream by a Code node that outputs { subject, html }.
// A notification that fails to send must not fail the run it reports on, hence
// continueRegularOutput by default.
const gmailSend = (name, pos, to, message = '={{ $json.html }}', extra = { onError: 'continueRegularOutput' }) => ({
  name, type: 'n8n-nodes-base.gmail', typeVersion: 2.2, position: pos,
  parameters: {
    sendTo: to, subject: '={{ $json.subject }}', emailType: 'html', message,
    options: { appendAttribution: false, senderName: 'GymRamp Course Factory' },
  },
  retryOnFail: true, maxTries: 3, waitBetweenTries: 5000, ...extra,
});

// Code node with the shared email kit prepended (one look for every message).
const codeKit = (name, pos, file) => code(name, pos, readCode('email-kit.js') + '\n' + readCode(file));
const emailWriter = (name, pos, kind) =>
  code(name, pos, readCode('email-kit.js') + '\n' + readCode('compose-email.js').replace("'__KIND__'", "'" + kind + "'"));

const stopError = (name, pos, message) => ({
  name, type: 'n8n-nodes-base.stopAndError', typeVersion: 1, position: pos, parameters: { errorMessage: message },
});

// LLM chain + model + structured parser (+ fixer model on the parser).
// autoFix makes the parser's ai_languageModel input REQUIRED -- the fixer model is wired
// to the PARSER, not just to the chain, or every run dies "A Model sub-node must be connected".
function llmChain(b, name, pos, { system, text, model, schema, temperature = 0.2 }) {
  b.add({
    name, type: '@n8n/n8n-nodes-langchain.chainLlm', typeVersion: 1.9, position: pos,
    parameters: {
      promptType: 'define',
      text,
      hasOutputParser: true,
      messages: { messageValues: [{ message: system }] },
      batching: {},
    },
    retryOnFail: true, maxTries: 2, waitBetweenTries: 5000,
  });
  const m = b.add({
    name: name + ' · Model', type: '@n8n/n8n-nodes-langchain.lmChatOpenRouter', typeVersion: 1,
    position: [pos[0] - 80, pos[1] + 220],
    parameters: { model, options: { temperature, timeout: 240000, maxRetries: 2 } },
  });
  const p = b.add({
    name: name + ' · Schema', type: '@n8n/n8n-nodes-langchain.outputParserStructured', typeVersion: 1.3,
    position: [pos[0] + 120, pos[1] + 220],
    parameters: { schemaType: 'manual', autoFix: true, inputSchema: JSON.stringify(schema, null, 2) },
  });
  const f = b.add({
    name: name + ' · Fixer', type: '@n8n/n8n-nodes-langchain.lmChatOpenRouter', typeVersion: 1,
    position: [pos[0] + 120, pos[1] + 420],
    parameters: { model: MODELS.fixer, options: { temperature: 0 } },
  });
  b.link(m, name, 0, 'ai_languageModel');
  b.link(p, name, 0, 'ai_outputParser');
  b.link(f, p, 0, 'ai_languageModel');
  return name;
}

// ================================================================ schemas ===
const str = { type: 'string' };
const arr = (items, extra = {}) => ({ type: 'array', items, ...extra });
const obj = (properties, required = Object.keys(properties)) => ({ type: 'object', properties, required, additionalProperties: false });

const PLAN_SCHEMA = obj({
  queries: arr(obj({ query: str, focus: str }), { minItems: 1, maxItems: 6 }),
  year_floor: { type: 'integer' },
  trials_query: str,
  core_terms: arr(str, { minItems: 1, maxItems: 8 }),
  context_terms: arr(str, { minItems: 1, maxItems: 10 }),
});

const ANALYSIS_SCHEMA = obj({
  sources: arr(obj({
    marker: str,
    evidence_level: { type: 'string', enum: ['systematic_review', 'rct', 'controlled_trial', 'observational', 'review', 'case_or_other', 'trial_registration'] },
    relevance: { type: 'string', enum: ['high', 'medium', 'low'] },
    key_findings: arr(obj({ claim: str, strength: { type: 'string', enum: ['strong', 'moderate', 'limited', 'conflicting'] } }), { maxItems: 3 }),
  })),
  decision: { type: 'string', enum: ['new_course', 'update_course', 'flag_review', 'no_action'] },
  target_course_slug: { type: ['string', 'null'] },
  rationale: str,
  safety_flags: arr(str),
  proposed_title: str,
  learning_objectives: arr(str, { minItems: 1, maxItems: 6 }),
});

const SCRIPT_SCHEMA = obj({
  title: str,
  subtitle: str,
  learning_objectives: arr(str, { minItems: 3, maxItems: 5 }),
  intro_notes: str,
  slides: arr(obj({ title: str, bullets: arr(str, { minItems: 2, maxItems: 4 }), notes: str }), { minItems: 3, maxItems: 12 }),
  takeaways: arr(str, { minItems: 3, maxItems: 4 }),
  takeaways_notes: str,
});

const QUESTION = obj({
  question: str,
  options: arr(str, { minItems: 4, maxItems: 4 }),
  answer_index: { type: 'integer', minimum: 0, maximum: 3 },
  rationale: str,
  markers: arr(str),
});
const ASSESS_SCHEMA = obj({
  worksheet: obj({ title: str, instructions: str, sections: arr(obj({ heading: str, prompts: arr(str, { minItems: 1, maxItems: 4 }) }), { minItems: 1, maxItems: 4 }) }),
  quiz: obj({ title: str, instructions: str, questions: arr(QUESTION, { minItems: 1 }) }),
  exam: obj({ title: str, instructions: str, pass_mark_percent: { type: 'integer' }, questions: arr(QUESTION, { minItems: 1 }) }),
});

// ============================================================ 1. research ===
function buildResearch() {
  const b = workflow('GymRamp HF · Research Topic',
    'Sub-workflow. Searches Europe PMC + ClinicalTrials.gov for a topic, ranks by evidence strength, ' +
    'upserts every source into Postgres (dedupe by DOI/PMID/NCT) and returns an evidence pack with ' +
    'E01.. markers and computed citations. IN: topic, audience, search_hint, since_date, trigger, ' +
    'max_sources, config. OUT: { topic, run_id, found_total, new_count, evidence[] }. Writes: sources, research_runs.');
  b.add(startTrigger(P(0, 0)));
  llmChain(b, 'Plan Searches', P(1, 0), {
    system: '=' + prompt('planner', { DATE: "{{ $now.toISODate() }}" }),
    text: "=Topic: {{ String($json.topic).replace(/[{}]/g, '') }}\nAudience: {{ String($json.audience || '').replace(/[{}]/g, '') }}\n" +
      "Administrator search terms: {{ String($json.search_hint || 'none').replace(/[{}]/g, '') }}\n" +
      "{{ $json.since_date ? 'Only records published since ' + $json.since_date + ' matter.' : '' }}\n\nReturn the json object.",
    model: MODELS.planner,
    schema: PLAN_SCHEMA,
  });
  b.add(code('Build Search Requests', P(2, 0), 'build-search-requests.js'));
  b.add(http('Fetch Evidence', P(3, 0), {
    url: '={{ $json.url }}',
    sendHeaders: true,
    headerParameters: { parameters: [{ name: 'Accept', value: 'application/json' }] },
    options: { timeout: 45000 },
  }, { onError: 'continueRegularOutput' }));
  b.add(code('Normalize & Rank', P(4, 0), 'normalize-rank.js'));
  b.add(pg('Upsert Sources', P(5, 0), [
    'WITH input AS (',
    '  SELECT * FROM jsonb_to_recordset($1::jsonb) AS x(',
    '    source_key text, source_type text, doi text, pmid text, pmcid text, nct_id text, title text,',
    '    authors jsonb, journal text, year int, pub_types jsonb, abstract text, url text, is_open_access boolean)',
    '),',
    'ins AS (',
    '  INSERT INTO sources (source_key, source_type, doi, pmid, pmcid, nct_id, title, authors, journal,',
    '                       year, pub_types, abstract, url, is_open_access, first_topic)',
    "  SELECT source_key, source_type, doi, pmid, pmcid, nct_id, title, COALESCE(authors, '[]'), journal,",
    "         year, COALESCE(pub_types, '[]'), abstract, url, COALESCE(is_open_access, false), $2",
    '  FROM input',
    '  ON CONFLICT DO NOTHING',          // any unique key: source_key, doi, pmid or nct_id
    '  RETURNING id, source_key',
    '),',
    'run AS (',
    '  INSERT INTO research_runs (topic, trigger, found, new_sources)',
    '  VALUES ($2, $3, (SELECT count(*) FROM input), (SELECT count(*) FROM ins))',
    '  RETURNING id',
    '),',
    // The outer snapshot cannot see rows `ins` just wrote, so new ids come from its
    // RETURNING and existing ids from the pre-statement table -- matched on ANY key,
    // because a conflict on DOI can come from a row stored under a different source_key.
    'resolved AS (',
    '  SELECT i.source_key, COALESCE(n.id, e.id) AS id, (n.id IS NOT NULL) AS is_new',
    '  FROM input i',
    '  LEFT JOIN ins n ON n.source_key = i.source_key',
    '  LEFT JOIN LATERAL (',
    '    SELECT s.id FROM sources s',
    '    WHERE s.source_key = i.source_key',
    '       OR (i.doi IS NOT NULL AND lower(s.doi) = lower(i.doi))',
    '       OR (i.pmid IS NOT NULL AND s.pmid = i.pmid)',
    '       OR (i.nct_id IS NOT NULL AND s.nct_id = i.nct_id)',
    '    LIMIT 1',
    '  ) e ON true',
    ')',
    // Always exactly one row: a Postgres node that returns zero rows stops the branch dead.
    'SELECT (SELECT id FROM run) AS run_id,',
    "       COALESCE((SELECT json_agg(row_to_json(r)) FROM resolved r), '[]'::json) AS rows,",
    '       (SELECT count(*) FROM ins) AS new_count;',
  ], [
    'JSON.stringify($json.candidates)',
    "$('Start').first().json.topic",
    "$('Start').first().json.trigger || 'course_factory'",
  ]));
  b.add(code('Return Evidence Pack', P(6, 0), 'build-evidence-pack.js'));

  b.link('Start', 'Plan Searches');
  b.link('Plan Searches', 'Build Search Requests');
  b.link('Build Search Requests', 'Fetch Evidence');
  b.link('Fetch Evidence', 'Normalize & Rank');
  b.link('Normalize & Rank', 'Upsert Sources');
  b.link('Upsert Sources', 'Return Evidence Pack');
  return b.wf;
}

// ============================================================ 2. analysis ===
function buildAnalysis() {
  const b = workflow('GymRamp HF · Evidence Analysis',
    'Sub-workflow. Grades each source (evidence level, relevance, key findings from the abstract only) and ' +
    'decides new_course | update_course | flag_review | no_action, with deterministic policy overrides. ' +
    'IN: topic, audience, slug, mode (course|radar), existing_version, run_id, evidence[], config. ' +
    'OUT: { topic, slug, run_id, analysis, evidence[], relevant_evidence[] }. Read-only.');
  b.add(startTrigger(P(0, 0)));
  b.add(pg('Load Existing Courses', P(1, 0), [
    "SELECT COALESCE(json_agg(json_build_object('slug', slug, 'title', title, 'status', status, 'version', current_version)",
    "         ORDER BY updated_at DESC), '[]'::json) AS courses",
    'FROM courses',
    "WHERE slug IS DISTINCT FROM $1::text AND status NOT IN ('failed', 'no_action');",
  ], ["$('Start').first().json.slug"]));
  b.add(code('Build Analysis Prompt', P(2, 0), 'build-analysis-prompt.js'));
  b.add(ifTrue('Has Evidence?', P(3, 0), '={{ $json.empty === false }}'));
  llmChain(b, 'Analyse Evidence', P(4, -0.5), {
    system: prompt('analyst'),
    text: '={{ $json.prompt }}',
    model: MODELS.analyst,
    schema: ANALYSIS_SCHEMA,
    temperature: 0.1,
  });
  b.add(code('Return Analysis', P(5, 0), 'apply-analysis.js'));

  b.link('Start', 'Load Existing Courses');
  b.link('Load Existing Courses', 'Build Analysis Prompt');
  b.link('Build Analysis Prompt', 'Has Evidence?');
  b.link('Has Evidence?', 'Analyse Evidence', 0);
  b.link('Has Evidence?', 'Return Analysis', 1);
  b.link('Analyse Evidence', 'Return Analysis');
  return b.wf;
}

// ============================================================= 3. content ===
function buildContent() {
  const b = workflow('GymRamp HF · Build Course Content',
    'Sub-workflow. Writes the course script (slides + narration citing evidence markers), worksheet, quiz and ' +
    'certification exam from the evidence brief only, then runs the Citation & Claim Gate. ' +
    'IN: topic, audience, slug, version, title, evidence[], analysis, config. ' +
    'OUT: { package, gate, claims[], references[], outline }. Read-only.');
  b.add(startTrigger(P(0, 0)));
  b.add(code('Prepare Evidence Brief', P(1, 0), 'prepare-evidence-brief.js'));
  llmChain(b, 'Write Course Script', P(2, 0), {
    system: prompt('writer', {
      SLIDES: CONTENT.slides_target, WMIN: CONTENT.notes_words_min, WMAX: CONTENT.notes_words_max,
      CHARS: CONTENT.narration_chars_target,
    }),
    text:
      "=COURSE TOPIC: {{ String($('Start').first().json.topic).replace(/[{}]/g, '') }}\n" +
      "AUDIENCE: {{ String($('Start').first().json.audience || '').replace(/[{}]/g, '') }}\n" +
      "WORKING TITLE: {{ String($('Start').first().json.title || '').replace(/[{}]/g, '') }}\n\n" +
      "LEARNING OBJECTIVES FROM THE EVIDENCE REVIEW:\n{{ $json.objectives.join('\\n') || 'none' }}\n\n" +
      "SAFETY FLAGS FROM THE EVIDENCE REVIEW:\n{{ $json.safety_flags.join('\\n') || 'none' }}\n\n" +
      'EVIDENCE BRIEF. Cite only these markers: {{ $json.markers.join(\', \') }}\n\n{{ $json.brief }}\n\n' +
      'Write the course and return the json object.',
    model: MODELS.writer,
    schema: SCRIPT_SCHEMA,
    temperature: 0.4,
  });
  b.add(code('Format Script For Assessor', P(3, 0), [
    '// Renders the written script as plain text for the assessment writer.',
    '// Plain text, not JSON: braces in the prompt would be read as template variables.',
    "const r = $input.first().json;",
    'const s = r.output && typeof r.output === "object" ? r.output : r;',
    "const clean = (t) => String(t == null ? '' : t).replace(/[{}]/g, '');",
    'const slides = (s.slides || []).map((x, i) =>',
    "  'SLIDE ' + (i + 1) + ': ' + clean(x.title) + '\\n' + (x.bullets || []).map((b) => '- ' + clean(b)).join('\\n') +",
    "  '\\nNARRATION: ' + clean(x.notes)).join('\\n\\n');",
    "const text = 'TITLE: ' + clean(s.title) + '\\n\\n' + slides + '\\n\\nTAKEAWAYS:\\n' + (s.takeaways || []).map(clean).join('\\n');",
    'return [{ json: { script_text: text }, pairedItem: { item: 0 } }];',
  ].join('\n')));
  llmChain(b, 'Write Assessments', P(4, 0), {
    system: prompt('assessor', { QUIZ: RUNTIME.quiz_questions, EXAM: RUNTIME.exam_questions, PASS: RUNTIME.exam_pass_mark }),
    text: '=COURSE SCRIPT\n\n{{ $json.script_text }}\n\nWrite the worksheet, quiz and certification exam and return the json object.',
    model: MODELS.writer,
    schema: ASSESS_SCHEMA,
    temperature: 0.3,
  });
  b.add(code('Citation & Claim Gate', P(5, 0), 'citation-gate.js'));

  b.link('Start', 'Prepare Evidence Brief');
  b.link('Prepare Evidence Brief', 'Write Course Script');
  b.link('Write Course Script', 'Format Script For Assessor');
  b.link('Format Script For Assessor', 'Write Assessments');
  b.link('Write Assessments', 'Citation & Claim Gate');
  return b.wf;
}

// =============================================================== 4. media ===
function buildMedia() {
  const b = workflow('GymRamp HF · Produce Media',
    'Sub-workflow. Sends a gated course package to the course-media worker (PPTX with speaker notes, narrated ' +
    'MP4, worksheet/quiz/exam/answer-key DOCX), polls until done, records assets, and optionally copies files ' +
    'to Supabase Storage. IN: version_id, package, config. OUT: { job_id, files[], video_seconds, tts_provider, ' +
    'tts_fallback_reason, slide_count, storage_backend }. Writes: assets, course_versions.media_job_id.');
  const S = "$('Start').first().json";
  b.add(startTrigger(P(0, 0)));
  b.add(http('Start Render', P(1, 0), {
    method: 'POST',
    url: '={{ $json.config.worker_url }}/courses/render',
    sendBody: true,
    specifyBody: 'json',
    jsonBody: '={{ JSON.stringify($json.package) }}',
    options: { timeout: 60000 },
  }));
  b.add({
    name: 'Wait For Render', type: 'n8n-nodes-base.wait', typeVersion: 1.1, position: P(2, 0),
    // Under 65 s a Wait sleeps in memory instead of parking the execution in the database.
    parameters: { amount: 20, unit: 'seconds' }, webhookId: uuid('media-wait'),
  });
  b.add(http('Check Render', P(3, 0), {
    url: '={{ ' + S + ".config.worker_url }}/jobs/{{ $('Start Render').first().json.job_id }}",
    options: { timeout: 30000 },
  }));
  b.add(switchEq('Render Status', P(4, 0), [
    { key: 'done', left: '={{ $json.status }}', right: 'done' },
    { key: 'failed', left: '={{ $json.status }}', right: 'failed' },
    // 90 polls x 20 s = 30 minutes. A job that is still running then is treated as hung.
    { key: 'timed_out', left: "={{ $runIndex >= 90 ? 'yes' : 'no' }}", right: 'yes' },
  ]));
  b.add(stopError('Render Failed', P(5, 1), "={{ 'Course render failed: ' + ($json.error || ('job ' + $json.job_id + ' still ' + $json.stage + ' after 30 minutes')) }}"));
  b.add(code('Render Complete', P(5, 0), [
    '// Anchors the finished job for everything downstream. The Switch before it ran once',
    '// per poll, so reading it by name would be ambiguous about which run is meant.',
    'return [{ json: $input.first().json, pairedItem: { item: 0 } }];',
  ].join('\n')));
  b.add(pg('Record Assets', P(6, 0), [
    'WITH a AS (',
    '  INSERT INTO assets (version_id, kind, filename, url, bytes, duration_seconds, storage_backend)',
    "  SELECT $1, x.kind, x.filename, x.url, x.bytes, x.duration_seconds, 'local'",
    '  FROM jsonb_to_recordset($2::jsonb) AS x(kind text, filename text, url text, bytes bigint, duration_seconds numeric)',
    '  ON CONFLICT (version_id, kind, storage_backend)',
    '  DO UPDATE SET url = EXCLUDED.url, bytes = EXCLUDED.bytes, duration_seconds = EXCLUDED.duration_seconds',
    '  RETURNING id',
    '),',
    "v AS (UPDATE course_versions SET media_job_id = $3, status = 'produced', updated_at = now() WHERE id = $1 RETURNING id)",
    'SELECT (SELECT count(*) FROM a) AS assets, (SELECT count(*) FROM v) AS versions;',
  ], [S + '.version_id', 'JSON.stringify($json.files)', '$json.job_id']));
  b.add(ifTrue('Use Supabase Storage?', P(7, 0), '={{ ' + S + ".config.storage_backend === 'supabase' }}"));
  b.add(code('Split Files For Upload', P(8, -1), [
    '// One item per produced file, with where to fetch it and where it goes in the bucket.',
    "const job = $('Render Complete').first().json;",
    "const s = $('Start').first().json;",
    "return (job.files || []).map((f) => ({",
    '  json: {',
    '    kind: f.kind, filename: f.filename, bytes: f.bytes,',
    '    download_url: s.config.worker_url + f.path,',
    "    object_path: s.package.course_slug + '/v' + s.package.version + '/' + f.filename,",
    '  },',
    '  pairedItem: { item: 0 },',
    '}));',
  ].join('\n')));
  b.add(http('Download Asset', P(9, -1), {
    url: '={{ $json.download_url }}',
    options: { timeout: 300000, response: { response: { responseFormat: 'file', outputPropertyName: 'data' } } },
  }));
  b.add(http('Upload To Supabase Storage', P(10, -1), {
    method: 'POST',
    url: '={{ ' + S + ".config.supabase_url }}/storage/v1/object/{{ " + S + ".config.supabase_bucket }}/{{ $('Split Files For Upload').item.json.object_path }}",
    authentication: 'predefinedCredentialType',
    nodeCredentialType: 'supabaseApi',
    sendHeaders: true,
    headerParameters: { parameters: [{ name: 'x-upsert', value: 'true' }] },
    sendBody: true,
    contentType: 'binaryData',
    inputDataFieldName: 'data',
    options: { timeout: 300000 },
  }));
  b.add(pg('Record Supabase Asset', P(11, -1), [
    'INSERT INTO assets (version_id, kind, filename, url, bytes, storage_backend)',
    "VALUES ($1, $2, $3, $4, $5, 'supabase')",
    'ON CONFLICT (version_id, kind, storage_backend) DO UPDATE SET url = EXCLUDED.url, bytes = EXCLUDED.bytes',
    'RETURNING id;',
  ], [
    S + '.version_id',
    "$('Split Files For Upload').item.json.kind",
    "$('Split Files For Upload').item.json.filename",
    S + ".config.supabase_url + '/storage/v1/object/' + " + S + ".config.supabase_bucket + '/' + $('Split Files For Upload').item.json.object_path",
    "$('Split Files For Upload').item.json.bytes",
  ]));
  b.add(setFields('Return Media', P(12, 0), [
    ['job_id', "={{ $('Render Complete').first().json.job_id }}", 'string'],
    ['files', "={{ $('Render Complete').first().json.files }}", 'array'],
    ['video_seconds', "={{ $('Render Complete').first().json.video_seconds }}", 'number'],
    ['slide_count', "={{ $('Render Complete').first().json.slide_count }}", 'number'],
    ['tts_provider', "={{ $('Render Complete').first().json.tts_provider }}", 'string'],
    ['tts_fallback_reason', "={{ $('Render Complete').first().json.tts_fallback_reason }}", 'string'],
    ['storage_backend', '={{ ' + S + '.config.storage_backend }}', 'string'],
  ], { executeOnce: true }));

  b.link('Start', 'Start Render');
  b.link('Start Render', 'Wait For Render');
  b.link('Wait For Render', 'Check Render');
  b.link('Check Render', 'Render Status');
  b.link('Render Status', 'Render Complete', 0);
  b.link('Render Status', 'Render Failed', 1);
  b.link('Render Status', 'Render Failed', 2);
  b.link('Render Status', 'Wait For Render', 3);
  b.link('Render Complete', 'Record Assets');
  b.link('Record Assets', 'Use Supabase Storage?');
  b.link('Use Supabase Storage?', 'Split Files For Upload', 0);
  b.link('Use Supabase Storage?', 'Return Media', 1);
  b.link('Split Files For Upload', 'Download Asset');
  b.link('Download Asset', 'Upload To Supabase Storage');
  b.link('Upload To Supabase Storage', 'Record Supabase Asset');
  b.link('Record Supabase Asset', 'Return Media');
  return b.wf;
}

// ============================================================= 5. factory ===
function buildFactory() {
  const b = workflow('GymRamp HF · Course Factory',
    'Main pipeline. Topic -> research -> evidence analysis -> course content + citation gate -> PPTX/MP4/' +
    'worksheet/exam -> human approval (Gmail or Slack) -> mock LMS publish. Triggers: webhook POST ' +
    '/webhook/gymramp/course (header auth), Course Request form (basic auth), or the Research Radar.');
  const CFGX = "$('Config').first().json";
  const COURSE = "$('Create Course').first().json";
  const REQ = "$('Normalize Request').first().json";
  const fail = (name) => b.link(name, 'Mark Failed', 1);
  const E = { onError: 'continueErrorOutput' };

  b.add({
    name: 'Course Request Webhook', type: 'n8n-nodes-base.webhook', typeVersion: 2.1, position: P(0, -1),
    parameters: { httpMethod: 'POST', path: 'gymramp/course', authentication: 'headerAuth', responseMode: 'onReceived', options: {} },
    webhookId: uuid('factory-webhook'),
  });
  b.add({
    name: 'Course Request Form', type: 'n8n-nodes-base.formTrigger', typeVersion: 2.6, position: P(0, 0),
    webhookId: uuid('factory-form'),
    parameters: {
      authentication: 'basicAuth',
      formTitle: 'Request a GymRamp course',
      formDescription: 'The factory researches the topic, writes and produces the course, and emails it for approval. Nothing is published without your sign-off.',
      formFields: {
        values: [
          { fieldLabel: 'Topic', placeholder: 'e.g. Red light therapy for exercise recovery', requiredField: true },
          { fieldLabel: 'Audience', placeholder: 'Leave blank for fitness, wellness and recovery professionals' },
          { fieldLabel: 'Search terms (optional)', placeholder: 'e.g. photobiomodulation OR "low-level laser therapy"' },
          { fieldLabel: 'Produce even if evidence is thin', fieldType: 'dropdown', fieldOptions: { values: [{ option: 'No' }, { option: 'Yes' }] } },
        ],
      },
      responseMode: 'onReceived',
      options: { appendAttribution: false, respondWithOptions: { values: { respondWith: 'text', formSubmittedText: 'Received. The course will be researched and produced, then emailed for review.' } } },
    },
  });
  b.add({ ...startTrigger(P(0, 1)), name: 'Called By Radar' });
  b.add(code('Normalize Request', P(1, 0), 'normalize-request.js'));
  b.add(setRaw('Config', P(2, 0), RUNTIME));
  b.add(pg('Create Course', P(3, 0), [
    'WITH c AS (',
    "  INSERT INTO courses (slug, title, topic, audience, status, current_version)",
    "  VALUES ($1, $2, $2, $3, 'researching', 1)",
    "  ON CONFLICT (slug) DO UPDATE SET status = 'researching', audience = EXCLUDED.audience,",
    '    current_version = courses.current_version + 1, updated_at = now()',
    '  RETURNING id, slug, topic, current_version',
    '),',
    'v AS (',
    '  INSERT INTO course_versions (course_id, version, status, n8n_execution_id)',
    "  SELECT id, current_version, 'researching', $4 FROM c",
    '  RETURNING id, course_id, version',
    ')',
    'SELECT v.id AS version_id, v.course_id, v.version, c.slug, c.topic FROM v JOIN c ON c.id = v.course_id;',
  ], [REQ + '.slug', REQ + '.topic', REQ + '.audience || ' + CFGX + '.default_audience', '$execution.id'], E));

  const common = {
    topic: '={{ ' + REQ + '.topic }}',
    audience: '={{ ' + REQ + '.audience || ' + CFGX + '.default_audience }}',
    slug: '={{ ' + COURSE + '.slug }}',
    config: '={{ ' + CFGX + ' }}',
  };
  b.add(execWf('Research Topic', P(4, 0), '__WF_RESEARCH__', {
    ...common,
    search_hint: '={{ ' + REQ + '.search_hint }}',
    trigger: 'course_factory',
    max_sources: '={{ ' + CFGX + '.max_sources }}',
  }, { node: E }));
  b.add(execWf('Analyse Evidence', P(5, 0), '__WF_ANALYSIS__', {
    ...common,
    mode: 'course',
    existing_version: '={{ ' + COURSE + '.version }}',
    run_id: '={{ $json.run_id }}',
    evidence: '={{ $json.evidence }}',
  }, { node: E }));
  b.add(pg('Save Analysis', P(6, 0), [
    "WITH v AS (UPDATE course_versions SET analysis = $2::jsonb, status = 'analysed', updated_at = now() WHERE id = $1 RETURNING id, course_id),",
    "c AS (UPDATE courses SET status = 'analysed', title = $3, updated_at = now() WHERE id = (SELECT course_id FROM v) RETURNING id),",
    'cs AS (',
    '  INSERT INTO course_sources (version_id, source_id, marker, evidence_level)',
    '  SELECT $1, x.source_id, x.marker, x.evidence_level',
    '  FROM jsonb_to_recordset($4::jsonb) AS x(source_id bigint, marker text, evidence_level text)',
    '  ON CONFLICT DO NOTHING RETURNING source_id',
    ')',
    'SELECT (SELECT count(*) FROM cs) AS linked_sources, (SELECT id FROM v) AS version_id;',
  ], [
    COURSE + '.version_id',
    'JSON.stringify($json.analysis)',
    '$json.analysis.proposed_title',
    'JSON.stringify($json.evidence)',
  ], E));
  // Policy (agreed 2026-09-14): an administrator-requested course is produced when the
  // analyst proposes new/update, OR flags it but at least min_relevant_sources are relevant
  // -- the flag then leads the approval email. no_action stops unless the request forces it.
  // The radar never reaches this node with a flag: it records findings instead.
  b.add(ifTrue('Produce Course?', P(7, 0),
    "={{ (() => { const a = $('Analyse Evidence').first().json; const d = a.analysis.decision; " +
    "const n = a.relevant_evidence.length; const min = " + CFGX + ".min_relevant_sources || 3; " +
    "return ['new_course', 'update_course'].includes(d) || (d === 'flag_review' && n >= min) || (" + REQ + ".force && n > 0); })() }}"));;
  b.add(pg('Record Not Produced', P(8, 2), [
    'WITH v AS (UPDATE course_versions SET status = $2, updated_at = now() WHERE id = $1 RETURNING course_id),',
    'c AS (UPDATE courses SET status = $2, updated_at = now() WHERE id = (SELECT course_id FROM v) RETURNING id),',
    'f AS (',
    '  INSERT INTO research_findings (topic, decision, rationale, course_id, source_ids)',
    '  SELECT $3, $4, $5, (SELECT course_id FROM v), $6::jsonb RETURNING id',
    ')',
    'SELECT (SELECT id FROM f) AS finding_id;',
  ], [
    COURSE + '.version_id',
    "$('Analyse Evidence').first().json.analysis.decision === 'flag_review' ? 'flagged' : 'no_action'",
    REQ + '.topic',
    "$('Analyse Evidence').first().json.analysis.decision",
    "$('Analyse Evidence').first().json.analysis.rationale",
    "JSON.stringify($('Analyse Evidence').first().json.relevant_evidence.map((e) => e.source_id))",
  ], E));
  b.add(emailWriter('Write Not Produced Email', P(9, 2), 'not_produced'));
  b.add(gmailSend('Email · Not Produced', P(10, 2), '={{ ' + CFGX + '.reviewer_email }}'));

  b.add(execWf('Build Course Content', P(8, 0), '__WF_CONTENT__', {
    ...common,
    version: '={{ ' + COURSE + '.version }}',
    title: "={{ $('Analyse Evidence').first().json.analysis.proposed_title }}",
    evidence: "={{ $('Analyse Evidence').first().json.relevant_evidence }}",
    analysis: "={{ $('Analyse Evidence').first().json.analysis }}",
  }, { node: E }));
  b.add(pg('Save Content', P(9, 0), [
    'WITH v AS (',
    '  UPDATE course_versions SET outline = $2::jsonb, slides = $3::jsonb, worksheet = $4::jsonb, quiz = $5::jsonb,',
    '    exam = $6::jsonb, gate_report = $7::jsonb, status = $8, updated_at = now()',
    '  WHERE id = $1 RETURNING id, course_id',
    '),',
    'c AS (UPDATE courses SET status = $8, title = $9, updated_at = now() WHERE id = (SELECT course_id FROM v) RETURNING id),',
    'cl AS (',
    '  INSERT INTO claims (version_id, slide_no, text, markers, status)',
    '  SELECT $1, x.slide_no, x.text, x.markers, x.status',
    '  FROM jsonb_to_recordset($10::jsonb) AS x(slide_no int, text text, markers jsonb, status text)',
    '  RETURNING id',
    '),',
    'cs AS (',
    '  UPDATE course_sources SET cited = true',
    '  WHERE version_id = $1 AND marker IN (SELECT jsonb_array_elements_text($11::jsonb))',
    '  RETURNING source_id',
    ')',
    'SELECT (SELECT count(*) FROM cl) AS claims, (SELECT count(*) FROM cs) AS cited_sources;',
  ], [
    COURSE + '.version_id',
    'JSON.stringify($json.outline)',
    'JSON.stringify($json.package.slides)',
    'JSON.stringify($json.package.worksheet)',
    'JSON.stringify($json.package.quiz)',
    'JSON.stringify($json.package.exam)',
    'JSON.stringify($json.gate)',
    "$json.gate.passed ? 'producing' : 'needs_revision'",
    '$json.package.title',
    'JSON.stringify($json.claims)',
    'JSON.stringify($json.references.map((r) => r.marker))',
  ], E));
  b.add(ifTrue('Gate Passed?', P(10, 0), "={{ $('Build Course Content').first().json.gate.passed }}"));
  b.add(emailWriter('Write Gate Blocked Email', P(11, 2), 'gate_blocked'));
  b.add(gmailSend('Email · Gate Blocked', P(12, 2), '={{ ' + CFGX + '.reviewer_email }}'));
  b.add(execWf('Produce Media', P(11, 0), '__WF_MEDIA__', {
    version_id: '={{ ' + COURSE + '.version_id }}',
    package: "={{ $('Build Course Content').first().json.package }}",
    config: '={{ ' + CFGX + ' }}',
  }, { node: E }));
  b.add(pg('Mark In Review', P(12, 0), [
    "WITH v AS (UPDATE course_versions SET status = 'in_review', updated_at = now() WHERE id = $1 RETURNING course_id),",
    "c AS (UPDATE courses SET status = 'in_review', updated_at = now() WHERE id = (SELECT course_id FROM v) RETURNING id)",
    'SELECT (SELECT count(*) FROM c) AS updated;',
  ], [COURSE + '.version_id'], E));
  b.add(codeKit('Build Review Message', P(13, 0), 'build-review-message.js'));
  b.add(switchEq('Review Channel', P(14, 0), [
    { key: 'gmail', left: '={{ $json.channel }}', right: 'gmail' },
    { key: 'slack', left: '={{ $json.channel }}', right: 'slack' },
  ]));
  b.add(stopError('Unknown Review Channel', P(15, 2), "={{ 'review_channel must be gmail or slack, got: ' + $json.channel }}"));

  // Review = a full HTML review pack (Gmail) or a short link (Slack), then ONE Wait node
  // whose form records the decision. Send-and-wait was dropped because it HTML-escapes the
  // message: the reviewer got a wall of plain text instead of a readable review pack.
  // The form is behind basic auth (the GymRamp Form Login credential); its URL exists only
  // at run time, so the message carries %%REVIEW_URL%% and is filled from resumeFormUrl.
  b.add(gmailSend('Gmail · Send Review Pack', P(15, -1), '={{ ' + CFGX + '.reviewer_email }}',
    "={{ $json.html.replace('%%REVIEW_URL%%', $execution.resumeFormUrl) }}", E));
  b.add({
    name: 'Slack · Send Review Link', type: 'n8n-nodes-base.slack', typeVersion: 2.5, position: P(15, 0.5),
    parameters: {
      authentication: 'accessToken',
      resource: 'message', operation: 'post',
      select: 'channel',
      channelId: { __rl: true, mode: 'id', value: '={{ ' + CFGX + '.slack_channel_id }}' },
      messageType: 'text',
      text: "={{ $json.text.replace('%%REVIEW_URL%%', $execution.resumeFormUrl) }}",
      otherOptions: { includeLinkToWorkflow: false },
    },
    retryOnFail: true, maxTries: 3, waitBetweenTries: 5000,
    ...E,
  });
  b.add({
    name: 'Wait For Decision', type: 'n8n-nodes-base.wait', typeVersion: 1.1, position: P(16, 0),
    webhookId: uuid('factory-review-form'),
    parameters: {
      resume: 'form',
      incomingAuthentication: 'basicAuth',
      formTitle: 'GymRamp course review',
      formDescription: 'Approving publishes this version to the LMS. Requesting changes sends it back with your notes.',
      formFields: {
        values: [
          { fieldLabel: 'Decision', fieldType: 'dropdown', requiredField: true,
            fieldOptions: { values: [{ option: 'Approve and publish' }, { option: 'Request changes' }] } },
          { fieldLabel: 'Comments', fieldType: 'textarea', placeholder: 'What should change? Optional when approving.' },
        ],
      },
      limitWaitTime: true,
      limitType: 'afterTimeInterval',
      resumeAmount: 7,
      resumeUnit: 'days',
      responseMode: 'onReceived',
      options: {
        appendAttribution: false,
        respondWithOptions: { values: { respondWith: 'text', formSubmittedText: 'Thank you. Your decision has been recorded.' } },
      },
    },
  });
  b.add(code('Normalize Decision', P(16, 0), 'normalize-decision.js'));
  b.add(pg('Record Review', P(17, 0), [
    'WITH r AS (INSERT INTO reviews (version_id, channel, decision, comments) VALUES ($1, $2, $3, $4) RETURNING id),',
    'v AS (UPDATE course_versions SET status = $5, updated_at = now() WHERE id = $1 RETURNING course_id),',
    'c AS (UPDATE courses SET status = $5, updated_at = now() WHERE id = (SELECT course_id FROM v) RETURNING id)',
    'SELECT (SELECT id FROM r) AS review_id;',
  ], [COURSE + '.version_id', '$json.channel', '$json.decision', '$json.comments', '$json.status'], E));
  b.add(ifTrue('Approved?', P(18, 0), "={{ $('Normalize Decision').first().json.approved }}"));
  b.add(pg('Publish To LMS (Mock)', P(19, 0), [
    // Stand-in for the real GymRamp LMS / Lovable + Supabase endpoint. Replace this node
    // with the HTTP call once the target exists; the payload shape is the contract.
    'WITH p AS (',
    "  INSERT INTO lms_publications (version_id, target, payload) VALUES ($1, 'mock-lms', $2::jsonb)",
    '  ON CONFLICT (version_id) DO UPDATE SET payload = EXCLUDED.payload, published_at = now()',
    '  RETURNING id, published_at',
    '),',
    "v AS (UPDATE course_versions SET status = 'published', updated_at = now() WHERE id = $1 RETURNING course_id),",
    "c AS (UPDATE courses SET status = 'published', updated_at = now() WHERE id = (SELECT course_id FROM v) RETURNING id)",
    'SELECT (SELECT id FROM p) AS publication_id, (SELECT published_at FROM p) AS published_at;',
  ], [
    COURSE + '.version_id',
    "JSON.stringify({ course_slug: " + COURSE + ".slug, version: " + COURSE + ".version, title: $('Build Course Content').first().json.package.title, " +
      "learning_objectives: $('Build Course Content').first().json.outline.learning_objectives, files: $('Produce Media').first().json.files, " +
      "references: $('Build Course Content').first().json.references, exam_pass_mark: $('Build Course Content').first().json.package.exam.pass_mark_percent, " +
      "approved_via: $('Normalize Decision').first().json.channel })",
  ], E));
  b.add(emailWriter('Write Published Email', P(20, 0), 'published'));
  b.add(gmailSend('Email · Published', P(21, 0), '={{ ' + CFGX + '.reviewer_email }}'));

  b.add(pg('Mark Failed', P(10, 3), [
    "WITH v AS (UPDATE course_versions SET status = 'failed', failure = $2, updated_at = now() WHERE id = $1 RETURNING course_id),",
    "c AS (UPDATE courses SET status = 'failed', updated_at = now() WHERE id = (SELECT course_id FROM v) RETURNING id)",
    'SELECT (SELECT count(*) FROM v) AS marked, $2::text AS failure;',
  ], [
    "$('Create Course').isExecuted ? " + COURSE + '.version_id : null',
    "String($json.error?.message ?? $json.error ?? $json.message ?? 'unknown error').slice(0, 2000)",
  ], { onError: 'continueRegularOutput' }));
  b.add(emailWriter('Write Failure Email', P(11, 3), 'failure'));
  b.add(gmailSend('Email · Failure Alert', P(12, 3), '={{ ' + CFGX + '.reviewer_email }}'));

  for (const t of ['Course Request Webhook', 'Course Request Form', 'Called By Radar']) b.link(t, 'Normalize Request');
  b.link('Normalize Request', 'Config');
  b.link('Config', 'Create Course');
  b.link('Create Course', 'Research Topic'); fail('Create Course');
  b.link('Research Topic', 'Analyse Evidence'); fail('Research Topic');
  b.link('Analyse Evidence', 'Save Analysis'); fail('Analyse Evidence');
  b.link('Save Analysis', 'Produce Course?'); fail('Save Analysis');
  b.link('Produce Course?', 'Build Course Content', 0);
  b.link('Produce Course?', 'Record Not Produced', 1);
  b.link('Record Not Produced', 'Write Not Produced Email'); fail('Record Not Produced');
  b.link('Write Not Produced Email', 'Email · Not Produced');
  b.link('Build Course Content', 'Save Content'); fail('Build Course Content');
  b.link('Save Content', 'Gate Passed?'); fail('Save Content');
  b.link('Gate Passed?', 'Produce Media', 0);
  b.link('Gate Passed?', 'Write Gate Blocked Email', 1);
  b.link('Write Gate Blocked Email', 'Email · Gate Blocked');
  b.link('Produce Media', 'Mark In Review'); fail('Produce Media');
  b.link('Mark In Review', 'Build Review Message'); fail('Mark In Review');
  b.link('Build Review Message', 'Review Channel');
  b.link('Review Channel', 'Gmail · Send Review Pack', 0);
  b.link('Review Channel', 'Slack · Send Review Link', 1);
  b.link('Review Channel', 'Unknown Review Channel', 2);
  b.link('Gmail · Send Review Pack', 'Wait For Decision'); fail('Gmail · Send Review Pack');
  b.link('Slack · Send Review Link', 'Wait For Decision'); fail('Slack · Send Review Link');
  b.link('Wait For Decision', 'Normalize Decision');
  b.link('Normalize Decision', 'Record Review');
  b.link('Record Review', 'Approved?'); fail('Record Review');
  b.link('Approved?', 'Publish To LMS (Mock)', 0);
  b.link('Publish To LMS (Mock)', 'Write Published Email'); fail('Publish To LMS (Mock)');
  b.link('Write Published Email', 'Email · Published');
  b.link('Mark Failed', 'Write Failure Email');
  b.link('Write Failure Email', 'Email · Failure Alert');

  b.wf.settings = { executionOrder: 'v1', errorWorkflow: '__WF_ERRORS__', executionTimeout: 3600 };
  return b.wf;
}

// =============================================================== 6. radar ===
function buildRadar() {
  const b = workflow('GymRamp HF · Research Radar',
    'Scheduled weekly. For every active watch topic: research (recent records only), keep ONLY sources never ' +
    'seen before, analyse them, record new_course / update_course / flag_review / no_action findings, and email ' +
    'a digest. With auto_produce on, new/update findings are sent to the Course Factory.');
  const CFGX = "$('Config').first().json";
  b.add({
    name: 'Weekly Radar', type: 'n8n-nodes-base.scheduleTrigger', typeVersion: 1.3, position: P(0, 0),
    parameters: { rule: { interval: [{ field: 'weeks', weeksInterval: 1, triggerAtDay: [CFG.schedule.radar_weekday], triggerAtHour: CFG.schedule.radar_hour }] } },
  });
  b.add(setRaw('Config', P(1, 0), RUNTIME));
  b.add(pg('Load Watch Topics', P(2, 0), [
    // A one-week overlap on since_date is harmless: dedupe is done by the sources table,
    // not by the date window, which only keeps each search small.
    'WITH t AS (SELECT id, topic, search_hint, last_run_at FROM watch_topics WHERE active ORDER BY id),',
    'u AS (UPDATE watch_topics w SET last_run_at = now() FROM t WHERE w.id = t.id RETURNING w.id)',
    "SELECT COALESCE(json_agg(json_build_object('topic', t.topic, 'search_hint', t.search_hint,",
    "         'since_date', to_char(COALESCE(t.last_run_at - interval '7 days', now() - interval '365 days'), 'YYYY-MM-DD'))), '[]'::json) AS topics,",
    '       now() AS run_started_at,',
    '       (SELECT count(*) FROM u) AS topics_marked',
    'FROM t;',
  ], null));
  b.add({
    name: 'Split Topics', type: 'n8n-nodes-base.splitOut', typeVersion: 1, position: P(3, 0),
    parameters: { fieldToSplitOut: 'topics', include: 'noOtherFields', options: {} },
  });
  b.add(execWf('Research Topic', P(4, 0), '__WF_RESEARCH__', {
    topic: '={{ $json.topic }}',
    search_hint: '={{ $json.search_hint }}',
    since_date: '={{ $json.since_date }}',
    audience: '={{ ' + CFGX + '.default_audience }}',
    trigger: 'radar',
    max_sources: 15,
    config: '={{ ' + CFGX + ' }}',
  }, { mode: 'each', node: { onError: 'continueRegularOutput' } }));
  b.add(code('Keep New Sources', P(5, 0), 'keep-new-sources.js'));
  b.add(ifTrue('Has New Sources?', P(6, 0), '={{ $json.skip !== true }}'));
  b.add(execWf('Analyse New Evidence', P(7, -0.5), '__WF_ANALYSIS__', {
    topic: '={{ $json.topic }}',
    audience: '={{ ' + CFGX + '.default_audience }}',
    mode: 'radar',
    existing_version: 0,
    run_id: '={{ $json.run_id }}',
    evidence: '={{ $json.evidence }}',
    config: '={{ ' + CFGX + ' }}',
  }, { mode: 'each', node: { onError: 'continueRegularOutput' } }));
  b.add(pg('Record Findings', P(8, -0.5), [
    'WITH f AS (',
    '  INSERT INTO research_findings (run_id, topic, decision, rationale, course_id, source_ids)',
    '  VALUES ($1, $2, $3, $4, (SELECT id FROM courses WHERE slug = $5::text), $6::jsonb)',
    '  RETURNING id',
    ')',
    'SELECT (SELECT id FROM f) AS finding_id, $2::text AS topic, $3::text AS decision;',
  ], [
    '$json.run_id',
    "$json.topic || 'unknown topic'",
    "$json.analysis?.decision ?? 'flag_review'",
    "$json.analysis?.rationale ?? ('Analysis failed: ' + String($json.error?.message ?? $json.error ?? 'unknown'))",
    '$json.analysis?.target_course_slug',
    'JSON.stringify(($json.relevant_evidence || []).map((e) => e.source_id))',
  ], { onError: 'continueRegularOutput' }));
  b.add(ifTrue('Auto Produce?', P(9, -1), '={{ ' + CFGX + ".auto_produce === true && ['new_course', 'update_course'].includes($json.decision) }}"));
  b.add(execWf('Start Course Production', P(10, -1), '__WF_FACTORY__', {
    topic: '={{ $json.topic }}',
    trigger: 'radar',
    force: false,
    finding_id: '={{ $json.finding_id }}',
  }, { mode: 'each', wait: false, node: { onError: 'continueRegularOutput' } }));
  b.add(pg('Load Radar Summary', P(9, 0.5), [
    'SELECT',
    "  (SELECT COALESCE(json_agg(json_build_object('topic', topic, 'found', found, 'new', new_sources) ORDER BY topic), '[]'::json)",
    "     FROM research_runs WHERE trigger = 'radar' AND started_at >= $1::timestamptz) AS runs,",
    "  (SELECT COALESCE(json_agg(json_build_object('topic', topic, 'decision', decision, 'rationale', rationale) ORDER BY decision), '[]'::json)",
    '     FROM research_findings WHERE run_id IS NOT NULL AND created_at >= $1::timestamptz) AS findings;',
  ], ["$('Load Watch Topics').first().json.run_started_at"], { executeOnce: true }));
  b.add(codeKit('Build Digest', P(10, 0.5), 'build-digest.js'));
  b.add(gmailSend('Email · Radar Digest', P(11, 0.5), '={{ ' + CFGX + '.reviewer_email }}', '={{ $json.html }}', {}));

  b.link('Weekly Radar', 'Config');
  b.link('Config', 'Load Watch Topics');
  b.link('Load Watch Topics', 'Split Topics');
  b.link('Split Topics', 'Research Topic');
  b.link('Research Topic', 'Keep New Sources');
  b.link('Keep New Sources', 'Has New Sources?');
  b.link('Has New Sources?', 'Analyse New Evidence', 0);
  b.link('Has New Sources?', 'Load Radar Summary', 1);
  b.link('Analyse New Evidence', 'Record Findings');
  b.link('Record Findings', 'Auto Produce?');
  b.link('Record Findings', 'Load Radar Summary');
  b.link('Auto Produce?', 'Start Course Production', 0);
  b.link('Load Radar Summary', 'Build Digest');
  b.link('Build Digest', 'Email · Radar Digest');

  b.wf.settings = { executionOrder: 'v1', errorWorkflow: '__WF_ERRORS__', executionTimeout: 3600 };
  return b.wf;
}

// ============================================================== 7. errors ===
function buildErrors() {
  const b = workflow('GymRamp HF · Error Handler',
    'Error workflow for the Course Factory and Research Radar. Marks the course version of the failed execution ' +
    'as failed and emails the reviewer the real error, node and execution link.');
  b.add({ name: 'Error Trigger', type: 'n8n-nodes-base.errorTrigger', typeVersion: 1, position: P(0, 0), parameters: {} });
  b.add(pg('Mark Version Failed', P(1, 0), [
    "WITH v AS (UPDATE course_versions SET status = 'failed', failure = $2, updated_at = now()",
    "           WHERE n8n_execution_id = $1 AND status NOT IN ('approved', 'published') RETURNING course_id),",
    "c AS (UPDATE courses SET status = 'failed', updated_at = now() WHERE id IN (SELECT course_id FROM v) RETURNING id)",
    'SELECT (SELECT count(*) FROM v) AS marked;',
  ], [
    "String($json.execution?.id ?? '')",
    "String($json.execution?.error?.message ?? 'unknown error').slice(0, 2000)",
  ], { onError: 'continueRegularOutput' }));
  // Email, deliberately: a different channel from the Slack review path, so an outage of
  // one cannot also swallow the alert about it.
  b.add(codeKit('Write Error Email', P(2, 0), 'write-error-email.js'));
  b.add(gmailSend('Email · Workflow Error', P(3, 0), RUNTIME.reviewer_email));
  b.link('Error Trigger', 'Mark Version Failed');
  b.link('Mark Version Failed', 'Write Error Email');
  b.link('Write Error Email', 'Email · Workflow Error');
  return b.wf;
}

// =============================================================== write ======
const WORKFLOWS = {
  errors: buildErrors(),
  research: buildResearch(),
  analysis: buildAnalysis(),
  content: buildContent(),
  media: buildMedia(),
  factory: buildFactory(),
  radar: buildRadar(),
};

for (const [key, wf] of Object.entries(WORKFLOWS)) {
  const names = new Set(wf.nodes.map((n) => n.name));
  for (const [from, byType] of Object.entries(wf.connections)) {
    if (!names.has(from)) throw new Error(wf.name + ': connection from unknown node ' + from);
    for (const ports of Object.values(byType)) for (const port of ports) for (const t of port) {
      if (!names.has(t.node)) throw new Error(wf.name + ': connection to unknown node ' + t.node);
    }
  }
  const text = JSON.stringify(wf);
  // `.item` is only safe where pairing is intact end to end: the per-file Supabase branch.
  const itemRefs = (text.match(/\$\('([^']+)'\)\.item\.json/g) || []).filter((m) => !m.includes('Split Files For Upload'));
  if (itemRefs.length) throw new Error(wf.name + ': cross-node .item reference(s): ' + [...new Set(itemRefs)].join(', '));
  if (/"credentials"/.test(text)) throw new Error(wf.name + ': credentials block in export');

  const out = { name: wf.name, nodes: wf.nodes, connections: wf.connections, settings: wf.settings, meta: { description: wf._description } };
  fs.writeFileSync(path.join(ROOT, key + '.workflow.json'), JSON.stringify(out, null, 2) + '\n');
  console.log(key.padEnd(9) + wf.nodes.length.toString().padStart(3) + ' nodes  ' + wf.name);
}
