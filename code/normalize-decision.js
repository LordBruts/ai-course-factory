// n8n Code node: "Normalize Decision"   (GymRamp · Course Factory)
// MODE: Run Once for All Items
//
// The Wait node resumes with the submitted form fields at the top level of the item
// (keys are the field LABELS). A send-and-wait node would nest them under `data`, so
// both are read. A wait that times out after 7 days resumes with the item it was
// given -- no Decision field at all -- which is recorded as 'expired', never mistaken
// for an approval. The same holds when the Slack node is disabled (no credential):
// nobody receives a link, so the review expires rather than passing.

const item = $input.first().json || {};
const data = item.data && typeof item.data === 'object' ? item.data : item;
const pick = (name) => {
  const key = Object.keys(data).find((k) => k.toLowerCase().trim() === name);
  return key ? data[key] : undefined;
};

const raw = String(pick('decision') || '').toLowerCase();
const decision = raw.startsWith('approve') ? 'approved' : raw.startsWith('request') || raw.startsWith('reject') ? 'rejected' : 'expired';

return [{
  json: {
    decision,
    approved: decision === 'approved',
    comments: String(pick('comments') || '').trim() || null,
    channel: $('Build Review Message').first().json.channel,
    responded_at: data.submittedAt || data.respondedAt || null,
    status: { approved: 'approved', rejected: 'needs_revision', expired: 'review_expired' }[decision],
  },
  pairedItem: { item: 0 },
}];
