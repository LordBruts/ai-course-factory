// n8n Code node: "Build Review Message"   (GymRamp · Course Factory)
// MODE: Run Once for All Items
//
// Everything an administrator needs to approve AI-written health education, in one
// email: what the course is, any concerns up front, the files, the statements worth
// a second look, and every claim beside the source it rests on.
//
// The decision button points at the Wait node's form. Its URL only exists at run
// time, so the HTML carries %%REVIEW_URL%% and the send node substitutes
// $execution.resumeFormUrl. The email kit is prepended by the build script.
//
// Output: { subject, html, text (for Slack), channel }

const cfg = $('Config').first().json;
const course = $('Create Course').first().json;
const a = $('Analyse Evidence').first().json.analysis || {};
const content = $('Build Course Content').first().json;
const media = $('Produce Media').first().json;

const gate = content.gate || {};
const stats = gate.stats || {};
const pkg = content.package || {};
const clean = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
const title = clean(pkg.title);

const LABEL = { pptx: 'Slides (PowerPoint)', mp4: 'Training video', worksheet: 'Worksheet', quiz: 'Knowledge-check quiz', exam: 'Certification exam', answer_key: 'Answer key', sources: 'Reference list' };
const minutes = media.video_seconds ? Math.floor(media.video_seconds / 60) + ' min ' + Math.round(media.video_seconds % 60) + ' s' : '';
const voice = media.tts_provider === 'elevenlabs' ? 'ElevenLabs' : media.tts_provider === 'edge' ? 'Microsoft neural voice' : 'unknown';

const CHECK = {
  UNCITED_CLAIM: 'Sounds like a research finding but has no source attached.',
  DOSE_STATED: 'Mentions a dose. It is cited, but worth confirming against the source.',
  DISEASE_TREATMENT_CLAIM: 'Talks about treating a condition. It is cited, but check the wording stays within scope.',
  ASSESSMENT_SHORT: 'Has fewer questions than planned.',
};
const place = (w) => String(w || '').replace(/^slide (\d+) bullet$/, 'Slide $1, on screen').replace(/^slide (\d+)$/, 'Slide $1')
  .replace(/^intro$/, 'Introduction').replace(/^takeaways$/, 'Key takeaways').replace(/^(quiz|exam)$/, (m) => m[0].toUpperCase() + m.slice(1));

const advisories = (gate.advisory || []).slice(0, 15).map((f) =>
  '<b>' + esc(place(f.where)) + '.</b> ' + esc(CHECK[f.code] || f.code) +
  (/^\d+ of \d+/.test(f.detail) ? ' <span style="color:' + KIT.muted + ';">(' + esc(f.detail) + ')</span>' : '<br><span style="color:' + KIT.muted + ';">&ldquo;' + esc(clean(f.detail)) + '&rdquo;</span>'));

// Claims grouped by where they appear, each with its numbered sources.
const bySlide = new Map();
for (const c of content.claims || []) {
  const key = c.slide_no === 0 ? 'Introduction' : c.slide_no > (pkg.slides || []).length ? 'Key takeaways' : 'Slide ' + c.slide_no + ': ' + clean((pkg.slides[c.slide_no - 1] || {}).title);
  if (!bySlide.has(key)) bySlide.set(key, []);
  const tag = c.status === 'cited' ? '' : ' <span style="color:' + KIT.warn + ';font-weight:600;">(no source)</span>';
  bySlide.get(key).push(esc(clean(c.text)) + tag);
}
const claimsHtml = [...bySlide.entries()].map(([k, items]) =>
  '<div style="font-size:13px;font-weight:700;color:' + KIT.navy + ';margin:10px 0 6px;">' + esc(k) + '</div>' + list(items, { html: true, size: 14 })).join('');

const refsHtml = (content.references || []).map((r) =>
  '<p style="margin:0 0 10px;font-size:13px;line-height:1.5;color:' + KIT.text + ';"><b>[' + r.n + ']</b> ' + esc(r.citation) +
  (r.url ? ' ' + link('Open', r.url) : '') + '</p>').join('');

const flagged = a.decision === 'flag_review';
const html = emailLayout({
  preheader: 'Ready for your review: ' + title + '. Nothing is published until you approve it.',
  eyebrow: 'Ready for review',
  title: title,
  subtitle: clean(pkg.subtitle) + ' · Version ' + course.version,
  intro: [
    'Hi,',
    'A new draft of "' + title + '" is ready for you. It has been researched, written, narrated and packaged, and it is waiting on your decision. Nothing reaches the LMS until you approve it.',
  ],
  blocks: [
    flagged
      ? callout('Please read this first: the evidence review flagged this topic',
          p(clean(a.rationale), { size: 14 }) + ((a.safety_flags || []).length ? list(a.safety_flags.map(clean), { size: 14 }) : ''), 'warn')
      : ((a.safety_flags || []).length ? callout('Points to keep in mind', list(a.safety_flags.map(clean), { size: 14 }), 'warn') : ''),
    '<tr><td style="padding:24px 32px 0;">' + button('Approve or request changes', '%%REVIEW_URL%%') +
      p('Opens a short form (sign in with the GymRamp form login). If you request changes, tell us what should be different.', { size: 13, color: KIT.muted, gap: 0 }) + '</td></tr>',
    section('What is in this version', facts([
      ['Slides', (stats.slides || 0) + ' content slides, plus title, takeaways and references'],
      ['Training video', esc(minutes) + ', narrated with ' + esc(voice) + (media.tts_fallback_reason ? ' <span style="color:' + KIT.warn + ';">(ElevenLabs was unavailable)</span>' : '')],
      ['Assessments', 'Worksheet, ' + (stats.quiz_questions || 0) + '-question quiz, ' + (stats.exam_questions || 0) + '-question certification exam (pass mark ' + (pkg.exam && pkg.exam.pass_mark_percent || 80) + '%)'],
      ['Sources', (stats.references || 0) + ' studies cited; ' + (stats.claims_cited || 0) + ' statements carry a source'],
    ].map(([k, v]) => [k, v]))),
    section('Files', facts((media.files || []).map((f) => [LABEL[f.kind] || f.kind, link('Open', f.url)])) +
      p('These links open on the GymRamp computer running the factory.', { size: 13, color: KIT.muted })),
    advisories.length ? section('Worth a second look', list(advisories, { html: true, size: 14 })) : '',
    section('Every statement and its source', claimsHtml || p('No statements were recorded.')),
    section('References', refsHtml),
  ],
  closing: ['Thanks for reviewing.'],
});

// Slack gets a short text version; the full review lives in the same form link.
const text = 'Ready for review: ' + title + ' (version ' + course.version + ')\n' +
  (flagged ? 'Flagged by the evidence review: ' + clean(a.rationale) + '\n' : '') +
  (stats.slides || 0) + ' slides, ' + minutes + ' video, ' + (stats.references || 0) + ' sources, ' + (advisories.length) + ' item(s) worth a second look.\n' +
  (media.files || []).map((f) => (LABEL[f.kind] || f.kind) + ': ' + f.url).join('\n') +
  '\nApprove or request changes: %%REVIEW_URL%%';

return [{
  json: {
    subject: (flagged ? 'Review needed (flagged): ' : 'Ready for your review: ') + title,
    html,
    text,
    channel: String(cfg.review_channel || 'gmail').toLowerCase(),
  },
  pairedItem: { item: 0 },
}];
