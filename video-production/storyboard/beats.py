"""Narration -> teaching beats.

A beat is one spoken idea with real start/end times taken from the word-level
transcript. Beats are the unit the storyboard decides on, and they are NOT slides:
one slide usually contains several beats, and a run of short beats may share a
single visual. Slide boundaries are carried along as a hint (they tell us where
the author changed subject) but they never define a cut.

Timing comes from the transcript, never from estimates: a visual that appears
0.4 s after the sentence it illustrates reads as a mistake, and guessing from
character counts drifts by seconds over a ten-minute course.

No text is rewritten here. Every beat carries the approved narration verbatim,
because the claim gate approved those words and nothing downstream may change them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Optional, Sequence

# A sentence ends at . ! ? — but not inside an abbreviation or a decimal, and a
# citation marker may sit before or after the stop: "... recovery [3]. Next ..."
_SENTENCE_END = re.compile(r"(?<=[.!?])(?:\s*\[\d+(?:\s*,\s*\d+)*\])?\s+(?=[A-Z(\"'])")
_ABBREV = re.compile(r"\b(?:e\.g|i\.e|vs|etc|Dr|Prof|approx|Fig|No)\.$", re.I)
_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")   # [3] and [1, 2] and [5, 6, 7, 8]
_WORD = re.compile(r"[a-z0-9']+", re.I)

# Language that signals what a beat is doing. These are cues, not commands: the
# rules engine weighs them, and a cue on its own never forces a visual.
PROCESS_CUES = ("first", "then", "next", "finally", "step", "begins", "followed by", "after that", "start by")
COMPARISON_CUES = ("versus", "compared with", "compared to", "unlike", "whereas", "in contrast", "rather than",
                   "outperform", "differ", "difference between", "not superior to", "did not beat", "more than")
EVIDENCE_CUES = ("study", "studies", "trial", "trials", "review", "meta-analysis", "randomised", "randomized",
                 "participants", "researchers", "evidence", "found that", "reported", "showed")
RECAP_CUES = ("in summary", "to summarise", "to summarize", "key takeaway", "remember", "to recap", "in short")
TRANSITION_CUES = ("now", "next", "let's", "lets", "moving on", "with that", "so far", "before we")
DEFINITION_CUES = ("is defined as", "means", "refers to", "is the", "describes", "uses", "stands for", ", or ")

# Guidance the learner is meant to act on. In a compliance-sensitive course this is
# the most consequential content on screen, and it reads as an instruction, not a claim.
PRACTICE_CUES = ("stay within", "your role", "do not", "don't", "never ", "always ", "make sure",
                 "be clear", "present ", "avoid ", "should stay", "must ", "remember to")

# A finding that failed to show an effect. Teaching what did NOT work is half of
# evidence-based practice, and these sentences are easy to skim past when only spoken.
NULL_RESULT_CUES = ("did not", "was not superior", "no difference", "not significant", "failed to",
                    "no benefit", "did not beat", "no adverse events")

# A number with a unit or a percentage is a claim a viewer should be able to read,
# not just hear. Bare years and reference numbers are excluded on purpose.
STATISTIC = re.compile(
    r"(?<![\w.])(?:\d{1,3}(?:[.,]\d+)?\s?%"
    r"|\d{1,3}(?:[.,]\d+)?\s?(?:mg|g|kg|ml|l|nm|mm|cm|m|s|sec|seconds|min|minutes|hours?|days?|weeks?|months?|years?|hz|w|j|cal|kcal|°c|c|f|x|fold|times|nanometres?|nanometers?|joules?|watts?|milliwatts?|hertz|micrometres?|micrometers?)"
    r"|(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:times|fold))(?![\w])",
    re.I,
)


@dataclass
class Beat:
    """One spoken idea, with the timing it is actually said at."""

    beat_id: str
    slide_index: int
    text: str                       # verbatim approved narration, markers included
    spoken_text: str                # the same words minus [n] markers, i.e. what is heard
    start: float
    end: float
    citation_ids: List[int] = field(default_factory=list)
    beat_type: str = "teaching"
    cues: List[str] = field(default_factory=list)
    statistics: List[str] = field(default_factory=list)
    word_count: int = 0
    slide_title: str = ""
    slide_bullets: List[str] = field(default_factory=list)
    is_slide_opening: bool = False
    timing: str = "estimate"         # "transcript" when word timings placed this beat

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["duration"] = self.duration
        return d


def strip_markers(text: str) -> str:
    """The spoken form: citation markers are written, never read aloud."""
    return re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", text).strip()


def split_sentences(text: str) -> List[str]:
    """Split narration into sentences without breaking abbreviations or decimals."""
    text = " ".join((text or "").split())
    if not text:
        return []
    parts, buf = [], ""
    for chunk in _SENTENCE_END.split(text):
        candidate = (buf + " " + chunk).strip() if buf else chunk
        # "e.g." and friends look like a sentence end; keep collecting.
        if _ABBREV.search(candidate):
            buf = candidate
            continue
        parts.append(candidate)
        buf = ""
    if buf:
        parts.append(buf)
    return [p for p in (s.strip() for s in parts) if p]


def _norm_words(text: str) -> List[str]:
    return [w.lower() for w in _WORD.findall(text)]


_SPELLING = {"metre": "meter", "metres": "meters", "litre": "liter", "litres": "liters",
             "centre": "center", "fibre": "fiber", "fibres": "fibers", "colour": "color",
             "behaviour": "behavior", "programme": "program"}


def _canon(token: str) -> str:
    """Spelling-insensitive form: the script may be British, the ASR American."""
    t = token.lower().strip("'")
    if t in _SPELLING:
        return _SPELLING[t]
    for gb, us in (("metre", "meter"), ("metres", "meters"), ("litre", "liter")):
        if t.endswith(gb):
            return t[: -len(gb)] + us
    if t.endswith("ise") and len(t) > 5:
        return t[:-3] + "ize"
    # British doubles the consonant before -ing/-ed: signalling, modelled, travelling.
    for gb, us in (("lling", "ling"), ("lled", "led")):
        if t.endswith(gb) and len(t) > 6:
            return t[: -len(gb)] + us
    return t


_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "         "fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def number_words(n: int) -> List[str]:
    """How a narrator says an integer (British "and"): 650 -> six hundred and fifty."""
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        return [_TENS[n // 10]] + ([_ONES[n % 10]] if n % 10 else [])
    if n < 1000:
        rest = n % 100
        return [_ONES[n // 100], "hundred"] + (["and"] + number_words(rest) if rest else [])
    if n < 1_000_000:
        rest = n % 1000
        tail = ([] if not rest else (["and"] if rest < 100 else []) + number_words(rest))
        return number_words(n // 1000) + ["thousand"] + tail
    return [str(n)]


def spoken_tokens(text: str) -> List[str]:
    """Canonical tokens as they would be SAID: digits become words, spelling is unified.

    The approved script writes "650" and "signalling"; speech recognition returns "six
    hundred and fifty" and "signaling". Comparing raw tokens reports those as edits, which
    hides real deviations inside formatting noise.
    """
    out: List[str] = []
    for tok in re.findall(r"\d+(?:\.\d+)?|[a-z0-9']+", text.lower()):
        if tok[0].isdigit():
            whole, _, frac = tok.partition(".")
            out += number_words(int(whole))
            if frac:
                out += ["point"] + [_ONES[int(d)] for d in frac]
        else:
            out.append(_canon(tok))
    return out


_UNIT = {w: i for i, w in enumerate(_ONES)}
_UNIT["oh"] = 0
_TEN = {w: 10 * i for i, w in enumerate(_TENS) if w != "_"}
_NUMBER_WORDS = set(_UNIT) | set(_TEN) | {"hundred", "thousand"}


def _cardinal(run: List[str]) -> Optional[int]:
    total, current = 0, 0
    for w in run:
        if w == "and":
            continue
        if w in _UNIT:
            current += _UNIT[w]
        elif w in _TEN:
            current += _TEN[w]
        elif w == "hundred":
            current = max(current, 1) * 100
        elif w == "thousand":
            total += max(current, 1) * 1000
            current = 0
        else:
            return None
    return total + current


def _grouped(run: List[str]) -> Optional[int]:
    """Digits read in groups: "eight oh eight" = 808, "six thirty" = 630."""
    if any(w in ("hundred", "thousand", "and") for w in run) or len(run) < 2:
        return None
    groups: List[str] = []
    i = 0
    while i < len(run):
        w = run[i]
        if w in _TEN and i + 1 < len(run) and run[i + 1] in _UNIT and _UNIT[run[i + 1]] > 0 and run[i + 1] != "oh":
            groups.append(str(_TEN[w] + _UNIT[run[i + 1]]))
            i += 2
            continue
        groups.append(str(_TEN[w]) if w in _TEN else str(_UNIT[w]))
        i += 1
    return int("".join(groups))


def collapse_numbers(tokens: Sequence[str], allowed: Optional[set] = None,
                     owners: Optional[Sequence[int]] = None):
    """Replace each spoken number with one '#<value>' token.

    "six hundred and fifty", "650" (already expanded by spoken_tokens) and a reader's
    "six fifty" are the same claim. Where a run reads two ways (cardinal or digit
    groups), the reading the approved script contains wins; otherwise the cardinal.
    Returns tokens, or (tokens, owners) when owners are given.
    """
    out: List[str] = []
    own: List[int] = []
    i = 0
    n = len(tokens)
    while i < n:
        if tokens[i] not in _NUMBER_WORDS or tokens[i] == "oh" and not (i + 1 < n and tokens[i + 1] in _NUMBER_WORDS):
            out.append(tokens[i])
            if owners is not None:
                own.append(owners[i])
            i += 1
            continue
        j = i
        while j < n and (tokens[j] in _NUMBER_WORDS or
                         (tokens[j] == "and" and j > i and tokens[j - 1] in ("hundred", "thousand")
                          and j + 1 < n and tokens[j + 1] in _NUMBER_WORDS and tokens[j + 1] not in ("hundred", "thousand"))):
            # A second cardinal starts where a small number is followed by a larger place:
            # "twenty four forty eight" is two numbers, but no reader says that; keep one run.
            j += 1
        run = list(tokens[i:j])
        card, grp = _cardinal(run), _grouped(run)
        value = card
        if allowed is not None and grp is not None and grp in allowed and card not in allowed:
            value = grp
        out.append("#%s" % value)
        if owners is not None:
            own.append(owners[i])
        i = j
    return (out, own) if owners is not None else out


def numbers_in(text: str) -> set:
    """Every number an approved text states, as values."""
    return {int(t[1:]) for t in collapse_numbers(spoken_tokens(text)) if t.startswith("#") and t[1:].isdigit()}


class WordTimeline:
    """Aligns a slide's approved sentences to its transcript's word timings.

    The transcript is authoritative for *when* a word is said; the approved script
    is authoritative for *what* the words are. They disagree in small ways (spelling,
    a hyphenated compound heard as three words, a misheard term), so the whole slide
    is aligned at once with a sequence diff rather than walked greedily: a greedy
    walk that misses one word drifts into the next sentence and loses every sentence
    after it.
    """

    def __init__(self, words: Sequence[Dict[str, Any]]):
        # Scribe emits {"text", "type": "word"|"spacing"|"audio_event", "start", "end"}.
        # Reading a "word" key instead finds nothing and silently degrades every beat
        # to the estimate, so accept both spellings and keep only real words.
        self.heard: List[Dict[str, Any]] = []
        for w in words:
            token = w.get("text", w.get("word"))
            if w.get("type", "word") != "word" or not token or w.get("start") is None:
                continue
            end = w.get("end") if w.get("end") is not None else w["start"]
            for part in _norm_words(token):
                self.heard.append({"t": _canon(part), "start": float(w["start"]), "end": float(end)})

    def align(self, sentences: Sequence[str]) -> List[Optional[Dict[str, float]]]:
        """One span per sentence (None where too few of its words were heard)."""
        import difflib

        script: List[str] = []
        owner: List[int] = []
        for k, sentence in enumerate(sentences):
            for t in _norm_words(sentence):
                script.append(_canon(t))
                owner.append(k)
        if not script or not self.heard:
            return [None] * len(sentences)

        mapping: Dict[int, int] = {}
        sm = difflib.SequenceMatcher(None, script, [h["t"] for h in self.heard], autojunk=False)
        for a, b, size in sm.get_matching_blocks():
            for n in range(size):
                mapping[a + n] = b + n

        spans: List[Optional[Dict[str, float]]] = []
        for k in range(len(sentences)):
            idx = [i for i, o in enumerate(owner) if o == k]
            hits = [mapping[i] for i in idx if i in mapping]
            if not idx or len(hits) < 0.5 * len(idx):
                spans.append(None)
                continue
            spans.append({"start": self.heard[min(hits)]["start"],
                          "end": self.heard[max(hits)]["end"],
                          "matched": len(hits), "expected": len(idx)})
        return spans


def _classify(text: str, *, slide_kind: str, is_first: bool, is_last: bool,
              has_citation: bool, stats: List[str]) -> tuple[str, List[str]]:
    low = text.lower()
    cues = [c for c in (PROCESS_CUES + COMPARISON_CUES + EVIDENCE_CUES + RECAP_CUES + DEFINITION_CUES
                        + PRACTICE_CUES + NULL_RESULT_CUES) if c in low]

    if slide_kind == "title" or (is_first and len(_norm_words(text)) <= 40):
        return "opening", cues
    if slide_kind == "takeaways" or any(c in low for c in RECAP_CUES):
        return "recap", cues
    if slide_kind == "references" or is_last:
        return "closing", cues
    # Scope and communication instructions are the beats a practitioner must act on,
    # so they are classified before evidence: "Present PBM as a wellness service, not a
    # medical treatment" is guidance, even though it mentions a treatment.
    if any(low.startswith(c) or (" " + c) in low for c in PRACTICE_CUES) and not has_citation:
        return "practice", cues
    if has_citation or any(c in low for c in EVIDENCE_CUES):
        return "evidence", cues
    if stats:
        return "emphasis", cues
    # A short sentence that opens a slide and uses a connective is a hinge, not teaching.
    if len(_norm_words(text)) <= 14 and any(low.startswith(c) for c in TRANSITION_CUES):
        return "transition", cues
    return "teaching", cues


def build_beats(slides: Iterable[Dict[str, Any]],
                transcripts: Optional[Dict[int, Sequence[Dict[str, Any]]]] = None,
                durations: Optional[Dict[int, float]] = None,
                words_per_second: float = 2.6) -> List[Beat]:
    """Turn approved slides into timed beats.

    `transcripts` maps slide index -> word list (from video-use / Scribe). When a
    slide has no transcript, timing falls back to a words-per-second estimate
    scaled to the slide's real audio duration, so the beats still line up with the
    narration file even without a transcript. The fallback is explicitly a
    fallback: QA flags a render built entirely on estimates.
    """
    slides = list(slides)
    beats: List[Beat] = []
    clock = 0.0
    counter = 0

    for s_i, slide in enumerate(slides):
        notes = (slide.get("notes") or "").strip()
        kind = slide.get("kind") or ("title" if s_i == 0 else "content")
        audio_seconds = (durations or {}).get(s_i)
        words = (transcripts or {}).get(s_i)
        timeline = WordTimeline(words) if words else None
        offset = clock

        sentences = split_sentences(notes)
        spans = (timeline.align([strip_markers(x) for x in sentences])
                 if timeline else [None] * len(sentences))
        if not sentences:
            # A slide with no narration still occupies time on screen.
            if audio_seconds:
                clock += audio_seconds
            continue

        est_total = sum(len(_norm_words(x)) for x in sentences) / max(words_per_second, 0.1)
        scale = (audio_seconds / est_total) if (audio_seconds and est_total) else 1.0
        cursor = 0.0

        for j, sentence in enumerate(sentences):
            citation_ids = [int(n) for m in _MARKER.findall(sentence) for n in re.findall(r'\d+', m)]
            spoken = strip_markers(sentence)
            stats = [m.group(0) for m in STATISTIC.finditer(spoken)]

            span = spans[j]
            if span:
                start, end = offset + span["start"], offset + span["end"]
                timing = "transcript"
            else:
                timing = "estimate"
                dur = (len(_norm_words(spoken)) / max(words_per_second, 0.1)) * scale
                start, end = offset + cursor, offset + cursor + dur
                cursor += dur

            beat_type, cues = _classify(
                spoken, slide_kind=kind, is_first=(s_i == 0 and j == 0),
                is_last=(s_i == len(slides) - 1 and j == len(sentences) - 1),
                has_citation=bool(citation_ids), stats=stats,
            )
            counter += 1
            beats.append(Beat(
                beat_id="B%03d" % counter,
                slide_index=s_i,
                text=sentence,
                spoken_text=spoken,
                start=round(max(0.0, start), 3),
                end=round(max(start + 0.2, end), 3),
                citation_ids=citation_ids,
                beat_type=beat_type,
                cues=cues,
                statistics=stats,
                word_count=len(_norm_words(spoken)),
                slide_title=slide.get("title") or "",
                slide_bullets=list(slide.get("bullets") or []),
                is_slide_opening=(j == 0),
                timing=timing,
            ))

        clock = max(clock, beats[-1].end if beats else clock)
        if audio_seconds:
            clock = offset + audio_seconds

    return _repair_monotonic(beats)


def _repair_monotonic(beats: List[Beat]) -> List[Beat]:
    """Guarantee a timeline that only moves forward.

    Overlapping beats would place two visuals on screen at once; a backwards jump
    would make a scene start before the one before it ended. Either is a rendering
    bug that is far cheaper to prevent here than to debug in a frame.
    """
    for i in range(1, len(beats)):
        prev, cur = beats[i - 1], beats[i]
        if cur.start < prev.end:
            cur.start = prev.end
        if cur.end <= cur.start:
            cur.end = round(cur.start + 0.4, 3)
    return beats


def sections_from_beats(beats: Sequence[Beat], slides: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group beats into teaching sections.

    A section starts where the narrative turns: a new slide subject, a recap, or
    the closing. Sections drive where a transition is allowed, which is how the
    video avoids a transition at every cut.
    """
    sections: List[Dict[str, Any]] = []
    for b in beats:
        title = b.slide_title or "Section"
        if not sections or sections[-1]["slide_index"] != b.slide_index:
            sections.append({
                "id": "SEC%02d" % (len(sections) + 1),
                "title": title,
                "start": b.start,
                "end": b.end,
                "slide_index": b.slide_index,
                "slide_indexes": [b.slide_index],
                "beat_ids": [b.beat_id],
            })
        else:
            sections[-1]["end"] = b.end
            sections[-1]["beat_ids"].append(b.beat_id)
    for s in sections:
        s.pop("slide_index", None)
    return sections
