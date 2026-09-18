// n8n Code node: "Normalize & Rank"   (GymRamp · Research Topic)
// MODE: Run Once for All Items
//
// Turns raw Europe PMC and ClinicalTrials.gov responses into ONE canonical
// source record shape, drops anything without an abstract, dedupes, ranks by
// evidence strength, caps the set and assigns the stable marker (E01, E02...)
// that every writer must cite by.
//
// Writers never see an author-year string, so they cannot invent one. They
// emit [E07]; only the Citation Gate turns that into a reference.
//
// Input : every HTTP response (a failed request arrives as {error}, ignored)
// Output: ONE item { topic, candidates[], found_total, dropped }

const start = $('Start').first().json;
const cfg = start.config || {};
const MAX = Number(start.max_sources || cfg.max_sources || 20);
const MAX_TRIALS = 3;

const clean = (s) => String(s || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
const lower = (a) => (a || []).map((t) => String(t).toLowerCase());

function fromEpmc(r) {
  const ji = r.journalInfo || {};
  const doi = r.doi ? String(r.doi).toLowerCase().trim() : null;
  return {
    source_type: 'literature',
    doi,
    pmid: r.pmid || null,
    pmcid: r.pmcid || null,
    nct_id: null,
    title: clean(r.title).replace(/\.$/, ''),
    authors: ((r.authorList || {}).author || []).map((a) => ({
      last: a.lastName || a.collectiveName || a.fullName || null,
      initials: a.initials || null,
    })),
    journal: (ji.journal || {}).title || r.journalTitle || null,
    year: parseInt(r.pubYear || ji.yearOfPublication, 10) || null,
    pub_types: lower((r.pubTypeList || {}).pubType),
    abstract: clean(r.abstractText).slice(0, 4000),
    url: doi ? 'https://doi.org/' + doi : r.pmid ? 'https://pubmed.ncbi.nlm.nih.gov/' + r.pmid + '/' : null,
    is_open_access: r.isOpenAccess === 'Y',
    cited_by: parseInt(r.citedByCount, 10) || 0,
  };
}

function fromTrial(s) {
  const p = s.protocolSection || {};
  const id = p.identificationModule || {};
  const st = p.statusModule || {};
  const design = p.designModule || {};
  const sponsor = ((p.sponsorCollaboratorsModule || {}).leadSponsor || {}).name || 'ClinicalTrials.gov';
  const date = (st.lastUpdatePostDateStruct || {}).date || (st.studyFirstPostDateStruct || {}).date || '';
  return {
    source_type: 'clinical_trial',
    doi: null,
    pmid: null,
    pmcid: null,
    nct_id: id.nctId || null,
    title: clean(id.briefTitle || id.officialTitle),
    authors: [{ last: sponsor, initials: null }],
    journal: 'ClinicalTrials.gov',
    year: parseInt(String(date).slice(0, 4), 10) || null,
    pub_types: lower(['trial registration', design.studyType, st.overallStatus].concat(design.phases || []).filter(Boolean)),
    abstract: clean((p.descriptionModule || {}).briefSummary).slice(0, 4000),
    url: id.nctId ? 'https://clinicaltrials.gov/study/' + id.nctId : null,
    is_open_access: true,
    cited_by: 0,
  };
}

// The planner names the modality itself (core_terms). A record mentioning none of them
// is about something else that merely shares the outcome words -- tart cherry juice for
// exercise recovery came back for a red light therapy topic on the first live run.
const planOut = $('Plan Searches').first().json || {};
const plan = planOut.output && typeof planOut.output === 'object' ? planOut.output : planOut;
const core = (Array.isArray(plan.core_terms) ? plan.core_terms : [])
  .map((t) => String(t).toLowerCase().trim()).filter((t) => t.length >= 3);

let found = 0;
const dropped = { no_abstract: 0, retracted: 0, duplicate: 0, off_topic: 0 };
const records = [];
for (const item of $input.all()) {
  const body = item.json || {};
  for (const r of ((body.resultList || {}).result) || []) { found++; records.push(fromEpmc(r)); }
  for (const s of body.studies || []) { found++; records.push(fromTrial(s)); }
}

const keyOf = (r) => (r.doi ? 'doi:' + r.doi : r.pmid ? 'pmid:' + r.pmid : r.nct_id ? 'nct:' + r.nct_id : null);
const byKey = new Map();
for (const r of records) {
  r.source_key = keyOf(r);
  if (!r.source_key || !r.title) continue;
  if (!r.abstract || r.abstract.length < 150) { dropped.no_abstract++; continue; }
  if (r.pub_types.some((t) => t.includes('retract')) || /^retract/i.test(r.title)) { dropped.retracted++; continue; }
  if (core.length) {
    const text = (r.title + ' ' + r.abstract).toLowerCase();
    if (!core.some((t) => text.includes(t))) { dropped.off_topic++; continue; }
  }
  const prev = byKey.get(r.source_key);
  if (prev) { dropped.duplicate++; if (r.abstract.length <= prev.abstract.length) continue; }
  byKey.set(r.source_key, r);
}

// Evidence-strength first, then recency, then (damped) influence.
function strength(r) {
  const t = r.pub_types.join(' ') + ' ' + r.title.toLowerCase();
  if (/meta-analysis|systematic review/.test(t)) return 6;
  if (/randomi[sz]ed controlled trial/.test(t)) return 5;
  if (r.source_type === 'clinical_trial') return 1.5;
  if (/clinical trial|controlled trial/.test(t)) return 4;
  if (/review/.test(t)) return 3;
  return 2;
}
// Topical fit. Without it, recency and review status dominate and a 2026 meta-analysis
// on thyroiditis outranks a 2024 trial on post-exercise soreness (first live run).
// Words from the topic, the search hint and the planner's context_terms, matched in the title (strong) and abstract (weak).
const STOP = new Set(['about', 'after', 'among', 'based', 'effect', 'effects', 'their', 'therapy', 'these', 'those', 'using', 'versus', 'which', 'while', 'with', 'within']);
const terms = [...new Set(
  (String(start.topic || '') + ' ' + String(start.search_hint || '') + ' ' + (Array.isArray(plan.context_terms) ? plan.context_terms.join(' ') : ''))
    .toLowerCase().replace(/[^a-z0-9 -]/g, ' ').split(/\s+/)
    .filter((w) => w.length > 4 && !STOP.has(w))
    .map((w) => w.replace(/(ies|es|s)$/, ''))
)];
function topical(r) {
  if (!terms.length) return 0;
  const title = r.title.toLowerCase();
  const abs = r.abstract.toLowerCase();
  const inTitle = terms.filter((t) => title.includes(t)).length;
  const inAbstract = terms.filter((t) => abs.includes(t)).length;
  return Math.min(8, inTitle * 2.5) + Math.min(3, inAbstract * 0.75);
}

const thisYear = new Date().getFullYear();
const score = (r) =>
  strength(r) * 1.5 +
  topical(r) +
  Math.max(0, 8 - (thisYear - (r.year || thisYear - 20))) * 0.25 +
  Math.min(3, Math.log10(r.cited_by + 1) * 1.5) +
  (r.is_open_access ? 0.5 : 0);

let trials = 0;
const candidates = Array.from(byKey.values())
  .map((r) => ({ r, s: score(r) }))
  .sort((a, b) => b.s - a.s || (b.r.year || 0) - (a.r.year || 0))
  .filter(({ r }) => (r.source_type !== 'clinical_trial' ? true : ++trials <= MAX_TRIALS))
  .slice(0, MAX)
  .map(({ r, s }, i) => ({ ...r, marker: 'E' + String(i + 1).padStart(2, '0'), rank_score: Math.round(s * 100) / 100 }));

return [{ json: { topic: start.topic, candidates, found_total: found, dropped }, pairedItem: { item: 0 } }];
