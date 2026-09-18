// n8n Code node: "Write ... Email"   (GymRamp · Course Factory)
// MODE: Run Once for All Items
//
// One composer for every notification the factory sends, so the voice stays
// consistent: a short, specific note -- what happened, why, and exactly what to do
// next. Internal codes (flag_review, needs_revision, CURE_PROMISE) never reach the
// reader; they are translated here. The build script prepends the email kit and
// sets KIND for each node.
//
// Output: { subject, html }

const KIND = '__KIND__';

const had = (name) => { try { return $(name).isExecuted; } catch (e) { return false; } };
const first = (name) => (had(name) ? $(name).first().json : {});
const req = first('Normalize Request');
const clean = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();

const REASON = {
  UNKNOWN_MARKER: 'Cites a source that is not part of the research for this course.',
  FREETEXT_CITATION: 'Uses a citation that did not come from the research.',
  CURE_PROMISE: 'Reads as a promise or guarantee of results.',
  DISEASE_TREATMENT_CLAIM: 'Claims to treat or prevent a medical condition.',
  MEDICATION_INSTRUCTION: 'Gives advice about medication.',
  DOSE_STATED: 'States a dose without a supporting source.',
  UNCITED_STATISTIC: 'Quotes a figure without a source.',
  INVENTED_EXPERIENCE: 'Describes client or personal experience that cannot be verified.',
  NARRATION_TOO_LONG: 'The narration is longer than the voice budget allows.',
  QUESTION_INVALID: 'A quiz or exam question cannot be answered as written.',
  ASSESSMENT_EMPTY: 'The quiz or exam has no questions.',
  WORKSHEET_EMPTY: 'The worksheet is missing.',
  SLIDE_COUNT: 'The course has the wrong number of slides.',
  SLIDE_INVALID: 'A slide is missing its title, bullets or narration.',
  NO_CITATIONS: 'The course does not cite any of the research.',
};
const place = (w) => String(w || '')
  .replace(/^slide (\d+) bullet$/, 'Slide $1, on screen').replace(/^slide (\d+)$/, 'Slide $1, narration')
  .replace(/^intro$/, 'Introduction').replace(/^takeaways$/, 'Key takeaways')
  .replace(/^(quiz|exam) Q(\d+)$/, (m, a, n) => (a === 'quiz' ? 'Quiz' : 'Exam') + ' question ' + n)
  .replace(/^course$/, 'Whole course').replace(/^script$/, 'Script').replace(/^worksheet$/, 'Worksheet');

let subject;
let html;

if (KIND === 'not_produced') {
  const a = first('Analyse Evidence').analysis || {};
  const counts = a.counts || {};
  const flagged = a.decision === 'flag_review';
  subject = 'No course produced yet: ' + clean(req.topic);
  html = emailLayout({
    preheader: 'The research did not support producing this course yet.',
    eyebrow: 'Course request',
    title: 'We held off on this course',
    subtitle: clean(req.topic),
    intro: [
      'Hi,',
      'We looked into your request for a course on "' + clean(req.topic) + '" and decided not to produce it yet. ' +
        (flagged
          ? 'The evidence review raised concerns, and there were not enough relevant studies to go ahead with confidence.'
          : 'The research we found does not support a course at this stage.'),
    ],
    blocks: [
      section('What the review found', p(clean(a.rationale)) + facts([
        ['Sources reviewed', String(counts.total || 0)],
        ['Relevant to fitness and recovery', String(counts.relevant || 0)],
      ])),
      (a.safety_flags || []).length ? section('Worth knowing before revisiting it', list(a.safety_flags.map(clean))) : '',
      (a.overrides || []).length ? callout('Policy check', p(a.overrides.map(clean).join('. ') + '.', { gap: 0, size: 14 }), 'warn') : '',
    ],
    closing: ['If you would still like it produced, submit the request again with "Produce even if evidence is thin" set to Yes, and the course will be written and sent to you for review as usual.'],
  });
} else if (KIND === 'gate_blocked') {
  const c = first('Build Course Content');
  const title = clean((c.package || {}).title || req.topic);
  const issues = ((c.gate || {}).blocking || []).map((f) =>
    '<b>' + esc(place(f.where)) + '.</b> ' + esc(REASON[f.code] || f.code) +
    (f.detail && !/^\d+ /.test(f.detail) ? '<br><span style="color:' + KIT.muted + ';">&ldquo;' + esc(clean(f.detail)) + '&rdquo;</span>' : ' <span style="color:' + KIT.muted + ';">(' + esc(clean(f.detail)) + ')</span>'));
  subject = 'Needs changes before production: ' + title;
  html = emailLayout({
    preheader: issues.length + ' issue(s) stopped this draft before any narration or video was made.',
    eyebrow: 'Content check',
    title: 'This draft needs changes',
    subtitle: title,
    intro: [
      'Hi,',
      'The draft of "' + title + '" was written, but it did not pass our content checks, so production stopped before any narration or video was made. No voice credits were used.',
    ],
    blocks: [
      callout('What needs changing', list(issues, { html: true, size: 14 }), 'bad'),
    ],
    closing: ['This version is saved as needing revision. Submitting the topic again will write a fresh draft with the same checks applied.'],
  });
} else if (KIND === 'published') {
  const c = first('Build Course Content');
  const course = first('Create Course');
  const media = first('Produce Media');
  const decision = first('Normalize Decision');
  const title = clean((c.package || {}).title);
  const LABEL = { pptx: 'Slides (PowerPoint)', mp4: 'Training video', worksheet: 'Worksheet', quiz: 'Knowledge-check quiz', exam: 'Certification exam', answer_key: 'Answer key', sources: 'Reference list' };
  subject = 'Published: ' + title + ' (version ' + course.version + ')';
  html = emailLayout({
    preheader: 'Version ' + course.version + ' is live in the LMS.',
    eyebrow: 'Published',
    title: title,
    subtitle: 'Version ' + course.version + ' is now published',
    intro: [
      'Hi,',
      'Thanks for approving "' + title + '". Version ' + course.version + ' has been published to the LMS. For now that is the test target, until the GymRamp LMS connection is set up.',
    ],
    blocks: [
      decision.comments ? callout('Your review notes', p(clean(decision.comments), { gap: 0, size: 14 }), 'ok') : '',
      section('Course files', facts((media.files || []).map((f) => [LABEL[f.kind] || f.kind, link('Download', f.url)]))),
    ],
    closing: [],
  });
} else if (KIND === 'failure') {
  const failed = first('Mark Failed');
  const url = 'http://localhost:5678/workflow/' + $workflow.id + '/executions/' + $execution.id;
  subject = 'Course production stopped: ' + clean(req.topic);
  html = emailLayout({
    preheader: 'An error stopped production partway through.',
    eyebrow: 'Production error',
    title: 'Production stopped partway through',
    subtitle: clean(req.topic),
    intro: [
      'Hi,',
      'Production of "' + clean(req.topic) + '" hit an error and stopped, so this version has been marked as failed. Nothing was sent for review or published.',
    ],
    blocks: [
      callout('The error', p(clean(failed.failure || 'No error message was recorded.'), { gap: 0, size: 14 }), 'bad'),
      section('Next steps', p('The full run, node by node, is in the ' + link('n8n execution log', url) + '. Once the cause is fixed, submit the topic again to start a new version.', { html: true })),
    ],
    closing: [],
  });
} else {
  throw new Error('compose-email: unknown KIND ' + KIND);
}

return [{ json: { subject, html }, pairedItem: { item: 0 } }];
