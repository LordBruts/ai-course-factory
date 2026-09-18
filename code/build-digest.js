// n8n Code node: "Build Digest"   (GymRamp · Research Radar)
// MODE: Run Once for All Items
//
// The weekly research email: what was scanned, how much was genuinely new, and what
// the radar proposes. Built from the rows written THIS run, so it reports what the
// database recorded, not what the workflow believes it did. Email kit prepended.

const summary = $input.first().json || {};
const parse = (v) => (typeof v === 'string' ? JSON.parse(v) : v || []);
const runs = parse(summary.runs);
const findings = parse(summary.findings);
const cfg = $('Config').first().json;
const clean = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();

let failed = [];
try { failed = $('Keep New Sources').first().json.failed || []; } catch (e) { failed = []; }

const totalNew = runs.reduce((n, r) => n + Number(r.new || 0), 0);
const LABEL = { new_course: 'Worth a new course', update_course: 'Worth updating a course', flag_review: 'Needs a closer look', no_action: 'Nothing to act on' };
const TONE = { new_course: 'ok', update_course: 'ok', flag_review: 'warn', no_action: '' };
const actionable = findings.filter((f) => f.decision !== 'no_action');

const table = '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:0 0 8px;">' +
  '<tr><td style="padding:8px 0;font-size:12px;color:' + KIT.muted + ';border-bottom:2px solid ' + KIT.rule + ';">Topic</td>' +
  '<td align="right" style="padding:8px 0;font-size:12px;color:' + KIT.muted + ';border-bottom:2px solid ' + KIT.rule + ';">Found</td>' +
  '<td align="right" style="padding:8px 0 8px 16px;font-size:12px;color:' + KIT.muted + ';border-bottom:2px solid ' + KIT.rule + ';">New</td></tr>' +
  runs.map((r) => '<tr><td style="padding:8px 0;font-size:14px;color:' + KIT.text + ';border-bottom:1px solid ' + KIT.rule + ';">' + esc(r.topic) + '</td>' +
    '<td align="right" style="padding:8px 0;font-size:14px;color:' + KIT.muted + ';border-bottom:1px solid ' + KIT.rule + ';">' + r.found + '</td>' +
    '<td align="right" style="padding:8px 0 8px 16px;font-size:14px;font-weight:700;color:' + (r.new ? KIT.accent : KIT.muted) + ';border-bottom:1px solid ' + KIT.rule + ';">' + r.new + '</td></tr>').join('') +
  '</table>';

const proposals = findings.map((f) => callout(LABEL[f.decision] + ': ' + clean(f.topic), p(clean(f.rationale), { gap: 0, size: 14 }), TONE[f.decision]));

const html = emailLayout({
  preheader: totalNew + ' new sources this week, ' + actionable.length + ' worth your attention.',
  eyebrow: 'Research radar',
  title: 'This week in recovery and wellness research',
  subtitle: runs.length + ' topics scanned · ' + totalNew + ' new sources · ' + actionable.length + ' to consider',
  intro: [
    'Hi,',
    totalNew
      ? 'Here is what the weekly scan turned up. Only studies we had never seen before were reviewed, so everything below is new since the last run.'
      : 'The weekly scan found nothing new this week. Every study it came across had already been reviewed in an earlier run, so there is nothing to decide.',
  ],
  blocks: [
    section('What was scanned', table),
    ...(findings.length ? [section('What we suggest', p('Each topic with new research was assessed. Suggestions only; nothing is produced without you.', { size: 14, color: KIT.muted }))].concat(proposals) : []),
    failed.length ? callout('Topics we could not scan', list(failed.map((f) => clean(f.topic) + ': ' + clean(f.error)), { size: 14 }), 'bad') : '',
  ],
  closing: [cfg.auto_produce
    ? 'Automatic production is on, so topics marked for a new or updated course have already been sent to the Course Factory. You will get a review email for each.'
    : 'To turn a suggestion into a course, submit its topic on the Course Request form. You will get the draft for review as usual.'],
});

return [{
  json: { subject: 'Research radar: ' + totalNew + ' new sources, ' + actionable.length + ' to consider', html },
  pairedItem: { item: 0 },
}];
