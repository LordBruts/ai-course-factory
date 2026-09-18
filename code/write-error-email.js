// n8n Code node: "Write Error Email"   (GymRamp · Error Handler)
// MODE: Run Once for All Items
//
// For failures nothing else caught (a crash between nodes, a timeout, an unwired
// failure). Names the workflow, the node and the real error. Email kit prepended.

const t = $('Error Trigger').first().json || {};
const ex = t.execution || {};
const wf = t.workflow || {};
const marked = Number(($input.first().json || {}).marked || 0);
const clean = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();

const html = emailLayout({
  preheader: clean(wf.name) + ' stopped with an error.',
  eyebrow: 'Workflow error',
  title: 'Something went wrong in ' + clean(wf.name),
  intro: [
    'Hi,',
    'The workflow "' + clean(wf.name) + '" stopped with an error that was not handled inside the workflow itself.' +
      (marked ? ' The course version it was producing has been marked as failed.' : ''),
  ],
  blocks: [
    callout('The error', p(clean((ex.error || {}).message || 'No error message was recorded.'), { gap: 0, size: 14 }), 'bad'),
    section('Details', facts([
      ['Stopped at', esc(clean(ex.lastNodeExecuted || 'unknown'))],
      ['Execution', ex.url ? link('Open in n8n', ex.url) : esc(String(ex.id || 'unknown'))],
    ])),
  ],
  closing: ['Once the cause is fixed, the run can be retried from n8n or the topic submitted again.'],
});

return [{ json: { subject: 'Workflow error: ' + clean(wf.name), html }, pairedItem: { item: 0 } }];
