// n8n Code node: "Keep New Sources"   (GymRamp · Research Radar)
// MODE: Run Once for All Items
//
// This is where "don't reprocess research" pays off. Research Topic upserts
// every candidate into `sources`; only rows that did not exist before come back
// with is_new = true. A topic with nothing new costs no analysis call at all.
//
// A topic whose research failed arrives as { error } (the call runs with
// continueRegularOutput so one bad topic cannot sink the weekly scan). It is
// logged, not analysed.
//
// Always returns at least one item so the digest still runs on a quiet week.

const topics = $('Load Watch Topics').first().json.topics || [];
const out = [];
const failed = [];

$input.all().forEach((item, i) => {
  const r = item.json || {};
  const topic = r.topic || (topics[i] && topics[i].topic) || 'unknown topic';
  if (r.error || !Array.isArray(r.evidence)) {
    failed.push({ topic, error: String((r.error && r.error.message) || r.error || 'no evidence returned').slice(0, 200) });
    return;
  }
  const fresh = r.evidence.filter((e) => e.is_new === true);
  if (!fresh.length) return;
  out.push({ json: { topic, run_id: r.run_id, evidence: fresh, skip: false }, pairedItem: { item: i } });
});

if (!out.length) return [{ json: { skip: true, failed }, pairedItem: { item: 0 } }];
out[0].json.failed = failed;
return out;
