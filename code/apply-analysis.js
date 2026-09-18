// n8n Code node: "Return Analysis"   (GymRamp · Evidence Analysis)
// MODE: Run Once for All Items
//
// The model PROPOSES a decision; this node applies policy deterministically on
// top of it, and records every override so a reviewer can see why.
//
//   * Findings are kept only for markers that exist in the evidence pack.
//   * new_course / update_course need at least min_relevant_sources relevant
//     sources, otherwise they are downgraded (flag_review, or no_action if none).
//   * In course mode, new vs update is a FACT (does a prior version exist?),
//     not a model judgement.
//
// Output (return contract):
//   { topic, slug, run_id, analysis: {...}, evidence: [all, enriched], relevant_evidence: [...] }

const start = $('Start').first().json;
const cfg = start.config || {};
const llmOut = $('Analyse Evidence').isExecuted ? $('Analyse Evidence').first().json : {};
const a = llmOut.output && typeof llmOut.output === 'object' ? llmOut.output : llmOut;

const DECISIONS = ['new_course', 'update_course', 'flag_review', 'no_action'];
const LEVELS = ['systematic_review', 'rct', 'controlled_trial', 'observational', 'review', 'case_or_other', 'trial_registration'];
const evidence = start.evidence || [];
const known = new Set(evidence.map((e) => e.marker));
const overrides = [];

const assessed = new Map();
for (const s of Array.isArray(a.sources) ? a.sources : []) {
  if (!s || !known.has(s.marker)) {
    if (s && s.marker) overrides.push('ignored assessment for unknown marker ' + s.marker);
    continue;
  }
  assessed.set(s.marker, s);
}

const enriched = evidence.map((e) => {
  const s = assessed.get(e.marker);
  return {
    ...e,
    evidence_level: s && LEVELS.includes(s.evidence_level) ? s.evidence_level : 'unassessed',
    relevance: s && ['high', 'medium', 'low'].includes(s.relevance) ? s.relevance : 'low',
    key_findings: s && Array.isArray(s.key_findings) ? s.key_findings.slice(0, 3) : [],
  };
});
const relevant = enriched.filter((e) => e.relevance !== 'low');

let decision = DECISIONS.includes(a.decision) ? a.decision : null;
if (!decision) {
  overrides.push(evidence.length ? 'model returned no valid decision' : 'no evidence to analyse');
  decision = evidence.length ? 'flag_review' : 'no_action';
}

const min = Number(cfg.min_relevant_sources || 3);
if ((decision === 'new_course' || decision === 'update_course') && relevant.length < min) {
  overrides.push('only ' + relevant.length + ' relevant source(s), policy minimum is ' + min);
  decision = relevant.length ? 'flag_review' : 'no_action';
}

// An update needs a course to update. First radar run: "update_course" for Longevity,
// with no longevity course in the catalogue at all.
let courses = [];
try {
  const raw = $('Load Existing Courses').first().json.courses;
  courses = typeof raw === 'string' ? JSON.parse(raw) : raw || [];
} catch (e) { courses = []; }
const target = a.target_course_slug && courses.some((c) => c.slug === a.target_course_slug) ? a.target_course_slug : null;
if (start.mode === 'radar' && decision === 'update_course' && !target) {
  overrides.push('update proposed for "' + (a.target_course_slug || 'no course') + '", which is not an existing course; treated as new_course');
  decision = 'new_course';
}

if (start.mode !== 'radar' && (decision === 'new_course' || decision === 'update_course')) {
  const fact = Number(start.existing_version || 0) > 1 ? 'update_course' : 'new_course';
  if (fact !== decision) {
    overrides.push('decision ' + decision + ' corrected to ' + fact + ' from the course history');
    decision = fact;
  }
}

return [{
  json: {
    topic: start.topic,
    slug: start.slug || null,
    run_id: start.run_id || null,
    analysis: {
      decision,
      model_decision: a.decision || null,
      overrides,
      rationale: String(a.rationale || ''),
      target_course_slug: target,
      safety_flags: Array.isArray(a.safety_flags) ? a.safety_flags : [],
      proposed_title: String(a.proposed_title || start.topic),
      learning_objectives: Array.isArray(a.learning_objectives) ? a.learning_objectives.slice(0, 6) : [],
      counts: { total: evidence.length, assessed: assessed.size, relevant: relevant.length },
    },
    evidence: enriched,
    relevant_evidence: relevant,
  },
  pairedItem: { item: 0 },
}];
