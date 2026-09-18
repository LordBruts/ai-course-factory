// n8n Code node: "Normalize Request"   (GymRamp · Course Factory)
// MODE: Run Once for All Items
//
// Three entry points, one request shape:
//   Webhook            -> $json.body.{topic, audience, search_hint, force}
//   Course Request Form -> $json['Topic'], $json['Audience'], ...  (keys are field labels)
//   Called by Radar     -> $json.{topic, audience, search_hint, force, trigger, finding_id}

const src = $input.first().json || {};
let r;
let trigger;
if (src.body && typeof src.body === 'object' && !Array.isArray(src.body)) {
  r = src.body;
  trigger = 'webhook';
} else if ('Topic' in src) {
  r = {
    topic: src['Topic'],
    audience: src['Audience'],
    search_hint: src['Search terms (optional)'],
    force: src['Produce even if evidence is thin'] === 'Yes',
  };
  trigger = 'form';
} else {
  r = src;
  trigger = r.trigger || 'radar';
}

const topic = String(r.topic || '').replace(/\s+/g, ' ').trim();
if (topic.length < 5 || topic.length > 200) {
  throw new Error('A course request needs a topic of 5-200 characters. Received: "' + topic.slice(0, 80) + '"');
}

const slug = String(r.slug || topic)
  .toLowerCase()
  .normalize('NFKD')
  .replace(/\p{M}+/gu, '')
  .replace(/[^a-z0-9]+/g, '-')
  .replace(/^-+|-+$/g, '')
  .slice(0, 60);

return [{
  json: {
    topic,
    slug,
    audience: String(r.audience || '').trim() || null,
    search_hint: String(r.search_hint || '').trim() || null,
    force: r.force === true || r.force === 'true',
    trigger,
    finding_id: r.finding_id != null ? Number(r.finding_id) : null,
  },
  pairedItem: { item: 0 },
}];
