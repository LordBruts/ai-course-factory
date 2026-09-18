// n8n Code node: "Prepare Evidence Brief"   (GymRamp · Build Course Content)
// MODE: Run Once for All Items
//
// The writers' ONLY knowledge source. They get no search tools and no memory,
// so anything they state has to come from this brief or from general
// professional practice -- and the Citation & Claim Gate checks which.
//
// Braces are stripped: LangChain prompt templates read "{" as a variable.

const start = $('Start').first().json;
const safe = (s) => String(s == null ? '' : s).replace(/[{}]/g, '');
const evidence = start.evidence || [];

if (!evidence.length) {
  throw new Error('Build Course Content called with no evidence. Refusing to write a course with nothing to cite.');
}

const brief = evidence
  .map((e) => {
    const findings = (e.key_findings || [])
      .map((f) => '    - ' + safe(f.claim) + (f.strength ? ' (' + f.strength + ')' : ''))
      .join('\n');
    const lines = [
      '[' + e.marker + '] ' + safe(e.title),
      '  ' + [e.authors_short, e.year, e.evidence_level, e.journal].filter(Boolean).map(safe).join(' | '),
      findings ? '  Key findings:\n' + findings : '  Key findings: none extracted',
      '  Abstract excerpt: ' + safe(e.abstract).slice(0, 900),
    ];
    return lines.join('\n');
  })
  .join('\n\n');

const a = start.analysis || {};
return [{
  json: {
    brief,
    markers: evidence.map((e) => e.marker),
    safety_flags: (a.safety_flags || []).map(safe),
    objectives: (a.learning_objectives || []).map(safe),
  },
  pairedItem: { item: 0 },
}];
