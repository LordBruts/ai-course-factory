// n8n Code node: "Build Analysis Prompt"   (GymRamp · Evidence Analysis)
// MODE: Run Once for All Items
//
// Renders the evidence list and the existing course catalogue as plain text
// for the analyst model.
//
// Curly braces are stripped from everything interpolated: the LLM chain builds
// LangChain prompt templates, where a stray "{" in an abstract is read as a
// template variable and the call fails with "Missing value for input variable".

const start = $('Start').first().json;
const db = $input.first().json || {};
const courses = typeof db.courses === 'string' ? JSON.parse(db.courses) : db.courses || [];
const safe = (s) => String(s == null ? '' : s).replace(/[{}]/g, '');

const evidence = start.evidence || [];
if (!evidence.length) {
  return [{ json: { prompt: '', empty: true }, pairedItem: { item: 0 } }];
}

const sourceText = evidence
  .map((e) =>
    [
      '[' + e.marker + '] ' + safe(e.title),
      '  Type: ' + safe((e.pub_types || []).join(', ') || e.source_type) + ' | Year: ' + (e.year || 'n/a') +
        ' | ' + safe(e.journal || ''),
      '  Abstract: ' + safe(e.abstract).slice(0, 1800),
    ].join('\n')
  )
  .join('\n\n');

const catalogue = courses.length
  ? courses.map((c) => '- ' + safe(c.slug) + ': ' + safe(c.title) + ' (status ' + safe(c.status) + ', v' + c.version + ')').join('\n')
  : '- none yet';

const prompt = [
  'TOPIC: ' + safe(start.topic),
  'AUDIENCE: ' + safe(start.audience),
  'MODE: ' + (start.mode === 'radar'
    ? 'radar -- these sources are NEW since the last scan; decide whether they justify action.'
    : 'course -- an administrator requested a course on this topic; assess whether the evidence supports it.'),
  '',
  'EXISTING GYMRAMP COURSES:',
  catalogue,
  '',
  'SOURCES (' + evidence.length + '):',
  sourceText,
  '',
  'Assess every source by its marker and return the json object.',
].join('\n');

return [{ json: { prompt, empty: false }, pairedItem: { item: 0 } }];
