// n8n Code node: "Return Evidence Pack"   (GymRamp · Research Topic)
// MODE: Run Once for All Items
//
// Joins the ranked candidates with the database ids returned by the upsert,
// and builds each citation string from the STRUCTURED record. A citation is
// computed here, once, and never written by a model.
//
// Output (the sub-workflow's return contract):
//   { topic, run_id, found_total, new_count, evidence: [{ marker, source_id,
//     is_new, source_type, title, authors_short, year, journal, doi, pmid,
//     nct_id, url, pub_types, abstract, citation }] }

const ranked = $('Normalize & Rank').first().json;
const db = $input.first().json || {};
const rows = typeof db.rows === 'string' ? JSON.parse(db.rows) : db.rows || [];
const byKey = new Map(rows.map((r) => [r.source_key, r]));

function initials(raw) {
  const s = String(raw || '').replace(/[.\s-]/g, '');
  return s ? s.toUpperCase().split('').map((c) => c + '.').join(' ') : '';
}

function apaAuthors(authors) {
  const names = (authors || [])
    .filter((a) => a && a.last)
    .map((a) => (a.initials ? a.last + ', ' + initials(a.initials) : a.last));
  if (!names.length) return '';
  if (names.length === 1) return names[0];
  if (names.length <= 20) return names.slice(0, -1).join(', ') + ', & ' + names[names.length - 1];
  return names.slice(0, 19).join(', ') + ', ... ' + names[names.length - 1];
}

function citation(r) {
  const year = r.year ? '(' + r.year + ')' : '(n.d.)';
  if (r.source_type === 'clinical_trial') {
    return apaAuthors(r.authors) + '. ' + year + '. ' + r.title +
      ' (ClinicalTrials.gov Identifier ' + r.nct_id + '). ' + r.url;
  }
  const journal = r.journal ? ' ' + r.journal + '.' : '';
  const link = r.doi ? ' https://doi.org/' + r.doi : r.url ? ' ' + r.url : '';
  return (apaAuthors(r.authors) || 'Anonymous') + ' ' + year + '. ' + r.title + '.' + journal + link;
}

const shortAuthors = (a) =>
  !a || !a.length ? '' : a.length === 1 ? a[0].last : a.length === 2 ? a[0].last + ' & ' + a[1].last : a[0].last + ' et al.';

let unresolved = 0;
const evidence = [];
for (const c of ranked.candidates || []) {
  const row = byKey.get(c.source_key);
  if (!row || !row.id) {
    // The upsert returns every input key. A key with no id means two candidates in one
    // batch collided on a secondary key (same PMID, different DOI). Never cite a source
    // that has no row -- drop it and count it.
    unresolved++;
    continue;
  }
  evidence.push({
    marker: c.marker,
    source_id: Number(row.id),
    is_new: row.is_new === true,
    source_type: c.source_type,
    title: c.title,
    authors_short: shortAuthors(c.authors),
    year: c.year,
    journal: c.journal,
    doi: c.doi,
    pmid: c.pmid,
    nct_id: c.nct_id,
    url: c.url,
    pub_types: c.pub_types,
    abstract: c.abstract,
    citation: citation(c),
  });
}

return [{
  json: {
    topic: ranked.topic,
    run_id: db.run_id ? Number(db.run_id) : null,
    found_total: ranked.found_total,
    new_count: evidence.filter((e) => e.is_new).length,
    unresolved,
    evidence,
  },
  pairedItem: { item: 0 },
}];
