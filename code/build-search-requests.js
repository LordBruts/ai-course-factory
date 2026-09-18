// n8n Code node: "Build Search Requests"   (GymRamp · Research Topic)
// MODE: Run Once for All Items
//
// Fans the query planner's output into one item per HTTP request: Europe PMC
// for the literature (resultType=core carries abstract, DOI, PMID, OA flag and
// publication types in ONE call) and ClinicalTrials.gov for registered trials.
//
// Search is a plain, always-executed HTTP step -- not an agent tool -- so the
// model never decides what evidence exists or whether to look for it.
//
// A Basic LLM Chain with an output parser returns its object UNWRAPPED
// ($json.queries), while an Agent nests it under $json.output. Both are read.

const start = $('Start').first().json;
const planned = $input.first().json || {};
const plan = planned.output && typeof planned.output === 'object' ? planned.output : planned;

const thisYear = new Date().getFullYear();
let yearFloor = Number(plan.year_floor);
if (!(yearFloor > 1990 && yearFloor <= thisYear)) yearFloor = thisYear - 10;

// The radar passes since_date so a weekly run only asks for recent records.
// Dedupe does NOT depend on it -- the sources table does that -- it just keeps
// each call small.
const since = /^\d{4}-\d{2}-\d{2}$/.test(String(start.since_date || '')) ? start.since_date : null;

const seen = new Set();
const queries = [];
for (const q of Array.isArray(plan.queries) ? plan.queries : []) {
  const text = String((q && q.query) || q || '').replace(/\s+/g, ' ').trim();
  if (text.length < 3 || seen.has(text.toLowerCase())) continue;
  seen.add(text.toLowerCase());
  queries.push(text);
}
// A planner that returns nothing must not silently produce an empty pack:
// fall back to the watch-topic hint, then the topic itself.
if (!queries.length) queries.push(String(start.search_hint || start.topic));

const enc = encodeURIComponent;
const EPMC = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search';
const out = queries.slice(0, 6).map((q) => {
  let query = '(' + q + ') AND HAS_ABSTRACT:Y AND PUB_YEAR:[' + yearFloor + ' TO 3000]';
  if (since) query += ' AND FIRST_PDATE:[' + since + ' TO 3000-12-31]';
  return {
    json: {
      kind: 'epmc',
      query: q,
      url: EPMC + '?query=' + enc(query) + '&resultType=core&pageSize=25&format=json',
    },
  };
});

const trialTerm = String(plan.trials_query || start.search_hint || start.topic).replace(/"/g, '');
let ct = 'https://clinicaltrials.gov/api/v2/studies?format=json&pageSize=10&sort=' + enc('LastUpdatePostDate:desc') +
  '&query.term=' + enc(trialTerm);
if (since) ct += '&filter.advanced=' + enc('AREA[LastUpdatePostDate]RANGE[' + since + ',MAX]');
out.push({ json: { kind: 'ctgov', query: trialTerm, url: ct } });

return out;
