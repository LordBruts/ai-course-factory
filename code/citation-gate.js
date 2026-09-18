// n8n Code node: "Citation & Claim Gate"   (GymRamp · Build Course Content)
// MODE: Run Once for All Items
//
// The deterministic control between AI-written health content and anything a
// human is asked to approve. Zero LLM calls.
//
// 1. Citations. Writers may only cite with evidence markers ([E03]). This node
//    rejects unknown markers, renumbers the real ones by first appearance
//    ([1], [2]...), and COMPUTES the reference list from the structured source
//    records -- an invented reference is unrepresentable, not just discouraged.
// 2. Claims. Every narration sentence is classified cited / uncited / blocked
//    and stored, so each claim in the course traces back to a source row.
// 3. Forbidden claim classes are blocked outright rather than fact-checked:
//    cure promises, uncited statistics, uncited doses, medication instructions,
//    invented first-person experience, author-year citations the writer made up.
// 4. Structure: slide/question validity and the narration spend budget, checked
//    BEFORE any TTS character is paid for.
//
// Blocking findings stop production; advisory findings travel to the reviewer.

const start = $('Start').first().json;
const cfg = start.config || {};
const unwrap = (j) => (j && j.output && typeof j.output === 'object' ? j.output : j || {});
const script = unwrap($('Write Course Script').first().json);
const assess = unwrap($('Write Assessments').first().json);

const evidence = start.evidence || [];
const byMarker = new Map(evidence.map((e) => [e.marker, e]));
const MAX_SLIDES = Number(cfg.max_slides || 16);
const MAX_TTS = Number(cfg.max_tts_chars || 3000);
// Fixed narration the worker adds: one intro sentence on the first references slide,
// plus "References, continued." on each further page (4 references per slide).
const referencesNarration = (count) => 160 + Math.max(0, Math.ceil(count / 4) - 1) * 25;

const blocking = [];
const advisory = [];
const flag = (list, code, where, detail) => list.push({ code, where, detail: String(detail).slice(0, 300) });

// ------------------------------------------------------------- markers ----
const order = [];
const GROUP = /\[\s*(E\d{1,3}(?:\s*[,;&]\s*E\d{1,3})*)\s*\]/gi;
const pad = (m) => 'E' + String(parseInt(m.slice(1), 10)).padStart(2, '0');

// Returns { text (markers renumbered), markers: ['E03', ...] }.
function resolve(text, where) {
  const found = [];
  const out = String(text || '').replace(GROUP, (_, inner) => {
    const nums = [];
    for (const raw of inner.split(/[,;&]/)) {
      const m = pad(raw.trim().toUpperCase());
      if (!byMarker.has(m)) {
        flag(blocking, 'UNKNOWN_MARKER', where, m + ' is not in the evidence pack');
        continue;
      }
      if (!order.includes(m)) order.push(m);
      if (!found.includes(m)) found.push(m);
      nums.push(order.indexOf(m) + 1);
    }
    return nums.length ? '[' + [...new Set(nums)].sort((a, b) => a - b).join(', ') + ']' : '';
  });
  return { text: out.replace(/\s+([.,;:])/g, '$1').replace(/\s{2,}/g, ' ').trim(), markers: found };
}

const spoken = (t) => String(t || '').replace(/\s*\[[\d,\s]+\]/g, '').trim();
// Writers often put the marker AFTER the full stop ("...tissue. [E02]"). Split as-is and
// the citation lands on the NEXT sentence, leaving the one it supports looking uncited
// (first live run: 4 of 6 slides). Move a trailing marker back inside its sentence first.
const TRAILING = /([.!?])\s*(\[\s*E\d{1,3}(?:\s*[,;&]\s*E\d{1,3})*\s*\])/gi;
const tidy = (t) => String(t || '').replace(TRAILING, ' $2$1');
const sentences = (t) => tidy(t).split(/(?<=[.!?])\s+/).map((s) => s.trim()).filter(Boolean);
const hasMarker = (s) => /\[\s*E\d{1,3}/i.test(s);

// --------------------------------------------------------- claim rules ----
const RULES = [
  { code: 'FREETEXT_CITATION', re: /\(([A-Z][A-Za-z'’-]+(?:\s+et al\.?|\s*(?:&|and)\s*[A-Z][A-Za-z'’-]+)?),?\s+(?:19|20)\d{2}[a-z]?\)/, level: () => 'blocking' },
  // Negated forms are exactly what a responsible course SHOULD say ("a recovery service,
  // not a cure", "benefits are not guaranteed"), and blocking them flagged the most careful
  // sentences in the first two live runs.
  { code: 'CURE_PROMISE', re: /\b(cures?|curing|guarantee[sd]?|miracle|clinically proven|scientifically proven|proven to)\b/i,
    level: (cited, s) => (/\b(not|never|no|nor|isn't|aren't|without|rather than|instead of)\s+(?:\w+\s+){0,3}(cures?|curing|guarantee[sd]?|miracle|clinically|scientifically|proven)\b/i.test(s) ? null : 'blocking') },
  { code: 'DISEASE_TREATMENT_CLAIM', re: /\b(treats?|treating|prevents?|reverses?|heals?)\s+(?:[a-z'-]+\s+){0,3}(disease|diabetes|cancer|arthritis|depression|obesity|dementia|alzheimer'?s|infection|hypertension|injur(?:y|ies))\b/i, level: (cited) => (cited ? 'advisory' : 'blocking') },
  { code: 'MEDICATION_INSTRUCTION', re: /\b(stop|start|change|reduce|increase|replace|skip)\s+(?:taking\s+)?(?:your\s+|their\s+)?(medication|medicine|prescription|insulin|drugs?)\b/i, level: () => 'blocking' },
  { code: 'DOSE_STATED', re: /\b\d+(?:\.\d+)?\s?(mg|mcg|µg|ug|iu|ml|units?)\b/i, level: (cited) => (cited ? 'advisory' : 'blocking') },
  { code: 'UNCITED_STATISTIC', re: /\d+(?:\.\d+)?\s?%|\b\d+(?:\.\d+)?[- ]fold\b|\bp\s?[<=]\s?0?\.\d+/i, level: (cited) => (cited ? null : 'blocking') },
  { code: 'INVENTED_EXPERIENCE', re: /\b(our|my)\s+(clients?|members?|patients?|gym|studio|clinic|facility|centre|center)\b|\bat our\b|\bI(?:'ve| have)?\s+(?:seen|used|treated|worked)\b/i, level: () => 'blocking' },
];
const CLAIMISH = /\b(improv|reduc|increas|decreas|enhanc|boost|lower|accelerat|effective|benefit|evidence|stud(?:y|ies)|research|trial|found|shown|showed|demonstrat|associated|linked)\w*/i;

const claims = [];
function checkNarration(text, where, slideNo) {
  const resolvedSentences = [];
  for (const s of sentences(text)) {
    const cited = hasMarker(s);
    let status = cited ? 'cited' : null;
    for (const rule of RULES) {
      if (!rule.re.test(s)) continue;
      const level = rule.level(cited, s);
      if (!level) continue;
      flag(level === 'blocking' ? blocking : advisory, rule.code, where, s);
      if (level === 'blocking') status = 'blocked';
    }
    const r = resolve(s, where);
    if (!status && CLAIMISH.test(s)) {
      status = 'uncited';
      flag(advisory, 'UNCITED_CLAIM', where, s);
    }
    if (status) claims.push({ slide_no: slideNo, text: r.text, markers: r.markers, status });
    resolvedSentences.push(r.text);
  }
  return resolvedSentences.join(' ');
}

// ------------------------------------------------------------- script -----
const rawSlides = Array.isArray(script.slides) ? script.slides : [];
if (rawSlides.length < 3 || rawSlides.length > MAX_SLIDES) {
  flag(blocking, 'SLIDE_COUNT', 'script', rawSlides.length + ' content slides (allowed 3-' + MAX_SLIDES + ')');
}

const introNotes = checkNarration(script.intro_notes, 'intro', 0);
const slides = rawSlides.map((s, i) => {
  const where = 'slide ' + (i + 1);
  if (!s || !s.title) flag(blocking, 'SLIDE_INVALID', where, 'missing title');
  const bullets = (Array.isArray(s && s.bullets) ? s.bullets : []).map(tidy).map((b) => {
    for (const rule of RULES) {
      if (rule.re.test(b)) {
        const level = rule.level(hasMarker(b), b);
        if (level) flag(level === 'blocking' ? blocking : advisory, rule.code, where + ' bullet', b);
      }
    }
    return resolve(b, where + ' bullet');
  });
  if (!bullets.length) flag(blocking, 'SLIDE_INVALID', where, 'no bullets');
  if (!String((s && s.notes) || '').trim()) flag(blocking, 'SLIDE_INVALID', where, 'no narration notes');
  const notes = checkNarration(s && s.notes, where, i + 1);
  const markerSet = new Set(bullets.flatMap((b) => b.markers));
  for (const c of claims.filter((c) => c.slide_no === i + 1)) c.markers.forEach((m) => markerSet.add(m));
  return {
    title: String((s && s.title) || '').trim(),
    bullets: bullets.map((b) => b.text),
    notes,
    refs: [...markerSet].map((m) => order.indexOf(m) + 1).sort((a, b) => a - b),
  };
});
const takeaways = (Array.isArray(script.takeaways) ? script.takeaways : []).map((t) => resolve(t, 'takeaways').text);
const takeawaysNotes = checkNarration(script.takeaways_notes, 'takeaways', slides.length + 1);

// --------------------------------------------------------- assessments ----
function questions(list, label, expected) {
  const qs = Array.isArray(list) ? list : [];
  if (!qs.length) flag(blocking, 'ASSESSMENT_EMPTY', label, 'no questions');
  else if (expected && qs.length < expected) flag(advisory, 'ASSESSMENT_SHORT', label, qs.length + ' of ' + expected + ' questions');
  return qs.map((q, i) => {
    const where = label + ' Q' + (i + 1);
    const options = (Array.isArray(q && q.options) ? q.options : []).map((o) => String(o).trim());
    const idx = Number(q && q.answer_index);
    if (!q || !String(q.question || '').trim()) flag(blocking, 'QUESTION_INVALID', where, 'missing question text');
    if (options.length < 3) flag(blocking, 'QUESTION_INVALID', where, 'fewer than 3 options');
    if (new Set(options.map((o) => o.toLowerCase())).size !== options.length) flag(blocking, 'QUESTION_INVALID', where, 'duplicate options');
    if (!Number.isInteger(idx) || idx < 0 || idx >= options.length) flag(blocking, 'QUESTION_INVALID', where, 'answer_index ' + (q && q.answer_index) + ' out of range');
    const refs = [];
    for (const raw of Array.isArray(q && q.markers) ? q.markers : []) {
      const m = pad(String(raw).replace(/[\[\]\s]/g, '').toUpperCase());
      if (!byMarker.has(m)) { flag(blocking, 'UNKNOWN_MARKER', where, m + ' is not in the evidence pack'); continue; }
      if (!order.includes(m)) order.push(m);
      refs.push(order.indexOf(m) + 1);
    }
    return {
      question: resolve(q && q.question, where).text,
      options,
      answer_index: idx,
      rationale: resolve(q && q.rationale, where).text,
      refs: [...new Set(refs)].sort((a, b) => a - b),
    };
  });
}

const quiz = assess.quiz || {};
const exam = assess.exam || {};
const worksheet = assess.worksheet || {};
const quizQs = questions(quiz.questions, 'quiz', Number(cfg.quiz_questions || 0));
const examQs = questions(exam.questions, 'exam', Number(cfg.exam_questions || 0));
if (!Array.isArray(worksheet.sections) || !worksheet.sections.length) flag(blocking, 'WORKSHEET_EMPTY', 'worksheet', 'no sections');

// ---------------------------------------------------------- references ----
const references = order.map((m, i) => {
  const e = byMarker.get(m);
  return { n: i + 1, marker: m, source_id: e.source_id, citation: e.citation, url: e.url || null };
});
if (!references.length) flag(blocking, 'NO_CITATIONS', 'course', 'the course cites no evidence at all');

// ------------------------------------------------------- spend budget -----
const narrationChars =
  spoken(introNotes).length + slides.reduce((n, s) => n + spoken(s.notes).length, 0) +
  spoken(takeawaysNotes).length + referencesNarration(references.length);
if (narrationChars > MAX_TTS) {
  flag(blocking, 'NARRATION_TOO_LONG', 'course', narrationChars + ' narration characters, budget ' + MAX_TTS);
}

const pkg = {
  course_slug: start.slug,
  version: Number(start.version || 1),
  title: String(script.title || start.title || start.topic).trim(),
  subtitle: String(script.subtitle || '').trim(),
  audience: String(start.audience || ''),
  intro_notes: introNotes,
  slides,
  takeaways,
  takeaways_notes: takeawaysNotes,
  references: references.map(({ n, citation, url }) => ({ n, citation, url })),
  worksheet: {
    title: String(worksheet.title || ''),
    instructions: String(worksheet.instructions || ''),
    sections: (worksheet.sections || []).map((s) => ({ heading: String(s.heading || ''), prompts: (s.prompts || []).map(String) })),
  },
  quiz: { title: String(quiz.title || ''), instructions: String(quiz.instructions || ''), questions: quizQs },
  exam: {
    title: String(exam.title || ''),
    instructions: String(exam.instructions || ''),
    pass_mark_percent: Number(exam.pass_mark_percent || cfg.exam_pass_mark || 80),
    questions: examQs,
  },
  tts_provider: cfg.tts_provider || null,
};

return [{
  json: {
    package: pkg,
    gate: {
      passed: blocking.length === 0,
      blocking,
      advisory,
      stats: {
        slides: slides.length,
        narration_chars: narrationChars,
        references: references.length,
        claims_cited: claims.filter((c) => c.status === 'cited').length,
        claims_uncited: claims.filter((c) => c.status === 'uncited').length,
        claims_blocked: claims.filter((c) => c.status === 'blocked').length,
        quiz_questions: quizQs.length,
        exam_questions: examQs.length,
      },
    },
    claims,
    references,
    outline: {
      title: pkg.title,
      subtitle: pkg.subtitle,
      learning_objectives: Array.isArray(script.learning_objectives) ? script.learning_objectives : [],
      slide_titles: slides.map((s) => s.title),
    },
  },
  pairedItem: { item: 0 },
}];
