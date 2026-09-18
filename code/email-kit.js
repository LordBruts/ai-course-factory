// ---- GymRamp email kit ------------------------------------------------------
// Prepended by build-workflows.js to every Code node that writes an email, so all
// messages share one look. Same rules as the earlier newsletter projects, because
// email clients are hostile: inline styles only (Gmail strips <style>), nested
// tables (no flexbox/grid), a centred 640px container on a soft background,
// web-safe fonts, no external images. Everything interpolated is HTML-escaped.

const KIT = {
  font: "system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif",
  navy: '#0B1F33', accent: '#FF6B2C', page: '#F2F4F7', card: '#FFFFFF',
  text: '#1B2733', muted: '#5B6673', rule: '#E4E8EE',
  ok: '#1E7F4F', warn: '#B26A00', bad: '#B3261E',
};

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

function p(text, opts) {
  const o = opts || {};
  return '<p style="margin:0 0 ' + (o.gap == null ? 14 : o.gap) + 'px;font-size:' + (o.size || 15) + 'px;line-height:1.6;color:' +
    (o.color || KIT.text) + ';">' + (o.html ? text : esc(text)) + '</p>';
}

function list(items, opts) {
  const o = opts || {};
  const rows = items.filter(Boolean).map((it) =>
    '<li style="margin:0 0 8px;font-size:' + (o.size || 15) + 'px;line-height:1.55;color:' + KIT.text + ';">' + (o.html ? it : esc(it)) + '</li>').join('');
  return rows ? '<ul style="margin:0 0 14px;padding-left:20px;">' + rows + '</ul>' : '';
}

function section(label, inner) {
  return '<tr><td style="padding:26px 32px 4px;">' +
    '<div style="font-size:12px;letter-spacing:1.4px;font-weight:700;color:' + KIT.navy + ';text-transform:uppercase;">' + esc(label) + '</div>' +
    '<div style="width:40px;height:3px;background:' + KIT.accent + ';margin:8px 0 14px;line-height:3px;font-size:0;">&nbsp;</div>' +
    inner + '</td></tr>';
}

function callout(title, inner, tone) {
  const color = { ok: KIT.ok, warn: KIT.warn, bad: KIT.bad }[tone] || KIT.accent;
  const tint = { ok: '#EEF7F1', warn: '#FFF6E8', bad: '#FCEDEC' }[tone] || '#FFF3EC';
  return '<tr><td style="padding:22px 32px 0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">' +
    '<tr><td style="background:' + tint + ';border-left:4px solid ' + color + ';padding:14px 18px;">' +
    '<div style="font-size:14px;font-weight:700;color:' + color + ';margin-bottom:6px;">' + esc(title) + '</div>' + inner +
    '</td></tr></table></td></tr>';
}

function button(label, href) {
  return '<table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:6px 0 4px;"><tr>' +
    '<td style="background:' + KIT.accent + ';border-radius:6px;">' +
    '<a href="' + esc(href) + '" style="display:inline-block;padding:13px 26px;font-family:' + KIT.font +
    ';font-size:15px;font-weight:700;color:#FFFFFF;text-decoration:none;">' + esc(label) + '</a></td></tr></table>';
}

// rows: [[label, valueHtml]]
function facts(rows) {
  return '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:0 0 10px;">' +
    rows.filter(Boolean).map(([k, v]) =>
      '<tr><td style="padding:7px 12px 7px 0;border-bottom:1px solid ' + KIT.rule + ';font-size:13px;color:' + KIT.muted +
      ';width:38%;vertical-align:top;">' + esc(k) + '</td><td style="padding:7px 0;border-bottom:1px solid ' + KIT.rule +
      ';font-size:14px;color:' + KIT.text + ';vertical-align:top;">' + v + '</td></tr>').join('') + '</table>';
}

function link(label, href) {
  return '<a href="' + esc(href) + '" style="color:' + KIT.accent + ';text-decoration:none;font-weight:600;">' + esc(label) + '</a>';
}

// blocks are <tr> strings from section()/callout(); intro is plain text paragraphs.
function emailLayout(o) {
  const intro = (o.intro || []).map((t) => p(t)).join('');
  return '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>' +
    '<body style="margin:0;padding:0;background:' + KIT.page + ';">' +
    '<div style="display:none;max-height:0;overflow:hidden;opacity:0;">' + esc(o.preheader || '') + '</div>' +
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:' + KIT.page + ';border-collapse:collapse;"><tr><td align="center" style="padding:28px 12px;">' +
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:' + KIT.card +
    ';border-collapse:collapse;font-family:' + KIT.font + ';border-radius:8px;overflow:hidden;">' +
    '<tr><td style="background:' + KIT.navy + ';padding:22px 32px;">' +
    '<div style="font-size:12px;letter-spacing:2px;font-weight:700;color:' + KIT.accent + ';">GYMRAMP' + (o.eyebrow ? ' &middot; ' + esc(o.eyebrow).toUpperCase() : '') + '</div>' +
    '<div style="font-size:22px;line-height:1.3;font-weight:700;color:#FFFFFF;margin-top:8px;">' + esc(o.title) + '</div>' +
    (o.subtitle ? '<div style="font-size:14px;color:#C9D3DD;margin-top:6px;">' + esc(o.subtitle) + '</div>' : '') +
    '</td></tr>' +
    '<tr><td style="padding:26px 32px 0;">' + intro + '</td></tr>' +
    (o.blocks || []).join('') +
    '<tr><td style="padding:26px 32px 28px;">' + (o.closing || []).map((t) => p(t)).join('') +
    p('GymRamp Course Factory', { color: KIT.muted, size: 14, gap: 0 }) + '</td></tr>' +
    '<tr><td style="background:' + KIT.page + ';padding:14px 32px;font-size:12px;line-height:1.5;color:' + KIT.muted + ';">' +
    esc(o.footer || 'Automated message from the GymRamp Course Factory. Course content is educational and is never published without human approval.') +
    '</td></tr></table></td></tr></table></body></html>';
}
// ---- end email kit ------------------------------------------------------------
