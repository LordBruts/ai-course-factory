"""Beats -> visual treatments (the deterministic half of the storyboard).

The question this module answers for every beat is the one from the brief:

    "What visual would make this sentence easier to understand?"

and NOT "what animation can I put here?". So the default answer is NONE, and a
visual has to earn its place by matching something real in the sentence: a study
being introduced, a number worth reading, a sequence, a contrast, a definition,
a turn in the argument.

Three properties this file is built around:

1. **Quiet is a decision.** A run of beats with no visual is correct when the
   narration is doing the work. The budget below enforces a floor of quiet beats,
   because a video where every sentence gets a card is exhausting and reads as
   generated.
2. **Repetition is the tell.** Three EVIDENCE_CARDs in a row look like a template.
   Variety is enforced structurally, not left to taste.
3. **Nothing on screen may be invented.** Props are assembled from approved text
   and from the reference list computed by the claim gate. A citation that is not
   in `references` cannot be rendered — it raises instead.

The LLM refinement pass (llm_pass.py) may change treatment, emphasis words and
wording of the reason. It may never introduce content, and its output is
re-validated by `validate_storyboard` here.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from beats import (Beat, STATISTIC, PROCESS_CUES, COMPARISON_CUES, DEFINITION_CUES,
                   PRACTICE_CUES, NULL_RESULT_CUES, strip_markers)

VISUAL_TYPES = (
    "NONE", "TITLE", "TEXT_EMPHASIS", "DIAGRAM", "PROCESS", "COMPARISON", "STATISTIC",
    "CHART", "B_ROLL", "IMAGE", "SCREEN_CAPTURE", "QUOTE", "EVIDENCE_CARD", "TIMELINE",
    "ICON_SEQUENCE", "SECTION_TRANSITION", "RECAP",
)

COMPONENT_FOR = {
    "TITLE": "TitleReveal",
    "SECTION_TRANSITION": "SectionIntro",
    "TEXT_EMPHASIS": "KeywordHighlight",
    "EVIDENCE_CARD": "EvidenceCard",
    "STATISTIC": "StatisticCard",
    "COMPARISON": "ComparisonCard",
    "PROCESS": "ProcessFlow",
    "TIMELINE": "Timeline",
    "QUOTE": "QuoteCard",
    "CHART": "ChartCard",
    "RECAP": "Recap",
    "DIAGRAM": "ProcessFlow",
    "ICON_SEQUENCE": "IconSequence",
    "B_ROLL": "BRoll",
    "IMAGE": "ImagePlate",
    "SCREEN_CAPTURE": "ScreenInsert",
}

ANIMATION_FOR = {
    "TITLE": "subtle_reveal",
    "SECTION_TRANSITION": "wipe_up",
    "TEXT_EMPHASIS": "highlight_sweep",
    "EVIDENCE_CARD": "subtle_reveal",
    "STATISTIC": "count_up",
    "COMPARISON": "stagger_children",
    "PROCESS": "draw_connector",
    "TIMELINE": "draw_connector",
    "QUOTE": "fade",
    "CHART": "stagger_children",
    "RECAP": "stagger_children",
    "DIAGRAM": "draw_connector",
    "ICON_SEQUENCE": "stagger_children",
    "B_ROLL": "fade",
    "IMAGE": "fade",
    "SCREEN_CAPTURE": "subtle_reveal",
}

# Words that never carry the point of a sentence, so never worth emphasising.
_STOP = set("""a an the and or but if then than that this these those of in on at to for with from by as is are was
were be been being it its their there here we you they he she them our your his her not no do does did can could
may might will would should must have has had how what when where which who why into over under about across""".split())

_TERM = re.compile(r"[A-Za-z][A-Za-z\-']+")


class StoryboardError(ValueError):
    """Raised when a storyboard would put something unsupported on screen."""


def _reference_index(references: Sequence[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    idx = {}
    for r in references or []:
        try:
            idx[int(r.get("n"))] = r
        except (TypeError, ValueError):
            continue
    return idx


def _emphasis_words(beat: Beat, limit: int = 3) -> List[str]:
    """Pick the words worth highlighting, from the sentence itself.

    Preference order: the numbers (a viewer wants to read those), then terms the
    slide itself names (they are the vocabulary being taught), then the longest
    content words. Everything returned appears verbatim in the spoken sentence,
    which is what lets the renderer highlight it in the caption.
    """
    picked: List[str] = []
    for stat in beat.statistics:
        if stat not in picked:
            picked.append(stat)

    spoken_low = beat.spoken_text.lower()
    slide_terms = []
    for b in [beat.slide_title, *beat.slide_bullets]:
        for t in _TERM.findall(b or ""):
            tl = t.lower()
            if len(tl) > 4 and tl not in _STOP and tl in spoken_low:
                slide_terms.append(t)
    for t in slide_terms:
        if len(picked) >= limit:
            break
        if all(t.lower() != p.lower() for p in picked):
            picked.append(t)

    if len(picked) < limit:
        words = sorted(
            (w for w in _TERM.findall(beat.spoken_text) if w.lower() not in _STOP and len(w) > 6),
            key=len, reverse=True,
        )
        for w in words:
            if len(picked) >= limit:
                break
            if all(w.lower() != p.lower() for p in picked):
                picked.append(w)
    return picked[:limit]


def _process_steps(beat: Beat) -> List[str]:
    """Extract an ordered sequence from the sentence, or fall back to slide bullets."""
    text = beat.spoken_text
    parts = re.split(r"\b(?:first|then|next|after that|finally|followed by)\b[,:]?\s*", text, flags=re.I)
    steps = [p.strip(" ,.;:") for p in parts[1:] if len(p.strip()) > 3]
    if len(steps) >= 2:
        return [s[:70] for s in steps[:4]]
    bullets = [b.strip() for b in beat.slide_bullets if b.strip()]
    return [b[:70] for b in bullets[:4]] if len(bullets) >= 2 else []


def _comparison_sides(beat: Beat) -> Optional[Dict[str, str]]:
    m = re.split(r"\b(?:versus|compared with|compared to|rather than|whereas|unlike|in contrast to)\b",
                 beat.spoken_text, flags=re.I)
    if len(m) >= 2:
        left, right = m[0].strip(" ,.;:"), m[1].strip(" ,.;:")
        if left and right:
            return {"left": left[-70:], "right": right[:70]}
    return None


def _evidence_props(beat: Beat, refs: Dict[int, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    n = beat.citation_ids[0]
    ref = refs[n]
    finding = _clause_or_none(beat.spoken_text, 180)
    if not finding:
        return None
    return {
        "marker": n,
        "citation": ref.get("citation", ""),
        "design": ref.get("design") or "",
        "year": ref.get("year"),
        "journal": ref.get("journal") or "",
        "population": ref.get("population") or "",
        "outcome": ref.get("outcome") or "",
        # The finding leads; the source is available underneath it. The viewer
        # should understand what was found before reading who found it.
        "finding": finding,
        # The headline figure must come from the words on the card. Taking it from the
        # whole sentence once put "48 hours" above a finding that, as shown, was about
        # one hour: a number the viewer cannot find in the text is a misleading number.
        "statistic": next((x for x in beat.statistics if x in finding and _is_headline_statistic(x)), None),
    }


# A study being reported reads differently from a general statement that happens to
# carry a citation. "A review reports promising effects [4]" is a finding and earns a
# card; "PBM uses red light [1, 2]" is a definition that merely cites its source. Giving
# both the same card is what turns an evidence-led course into a deck of identical boxes.
_REPORT_SUBJECT = re.compile(
    r"\b(?:systematic\s+)?(?:review|reviews|meta-analysis|study|studies|trial|trials|"
    r"rct|analysis|survey|experiment)\b", re.I)
_REPORT_VERB = re.compile(
    r"\b(?:found|finds?|reports?|reported|shows?|showed|demonstrated|observed|concluded|"
    r"failed to|did not|was not superior|were not|measured|compared|beat)\b", re.I)
_POPULATION = re.compile(
    r"\b(?:in|among)\s+(?:\d+\s+)?(?:adults|athletes|participants|patients|women|men|people|"
    r"crossfit\s+athletes|healthy\s+[a-z]+)\b", re.I)


_PARAMETER_UNIT = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:nm|nanometres?|nanometers?|hz|hertz|micrometres?|micrometers?|w|watts?|milliwatts?|j|joules?)\b", re.I)


def _is_headline_statistic(stat: str) -> bool:
    """True for a figure worth putting on screen on its own.

    Outcomes, doses in time, and multipliers answer 'what happened'. Wavelengths and
    power settings answer 'how was it configured', which belongs beside the finding,
    not in 150px type.
    """
    return not bool(_PARAMETER_UNIT.fullmatch(stat.strip()))


def _is_study_report(beat: Beat) -> bool:
    """True when the sentence actually tells the viewer what a study found."""
    text = beat.spoken_text
    has_subject = bool(_REPORT_SUBJECT.search(text)) or bool(_POPULATION.search(text))
    return has_subject and bool(_REPORT_VERB.search(text))


# ---- on-screen text -----------------------------------------------------------------
#
# Text on screen is chosen, never written, and never cut mid-thought. A card ending in
# "..." is worse than no card: it tells the viewer the point is somewhere they cannot
# see. In order of preference:
#   1. the approved slide bullet that states this sentence's point (already written
#      for the screen, short, and reviewed with the course);
#   2. the sentence itself, when it fits;
#   3. its leading clause, cut only at a clause boundary;
#   4. nothing: the beat stays quiet.

SCREEN_LINE_MAX = 120

_CLAUSE_BREAK = re.compile(
    r"(?:,\s+(?:but|though|although|while|whereas|and\s+not)\s+|;\s+|\s+[-–—]\s+)", re.I)


# Units a script spells out and a slide abbreviates: "650 nanometre" is "650 nm".
_UNIT_CANON = {"nm": "nm", "nanometre": "nm", "nanometres": "nm", "nanometer": "nm", "nanometers": "nm",
               "j": "j", "joule": "j", "joules": "j", "hz": "hz", "hertz": "hz",
               "mw": "mw", "milliwatt": "mw", "milliwatts": "mw", "w": "w", "watt": "w", "watts": "w",
               "min": "min", "minute": "min", "minutes": "min", "s": "s", "sec": "s", "seconds": "s"}
_CONTENT_TOKEN = re.compile(r"[A-Za-z][A-Za-z\-']*|\d+(?:\.\d+)?")


def _content(text: str) -> set:
    """Content words, numbers and canonical units: what a sentence and a bullet share."""
    out = set()
    for w in _CONTENT_TOKEN.findall(text or ""):
        low = w.lower()
        if low in _UNIT_CANON:
            out.add(_UNIT_CANON[low])
        elif low[0].isdigit():
            out.add(low)
        elif low not in _STOP and len(low) > 3:
            out.add(low.rstrip("s"))
    return out


def _best_bullet(text: str, bullets: Sequence[str], used: set) -> Optional[str]:
    said = _content(text)
    best, best_score = None, 0.0
    for b in bullets or []:
        shown = strip_markers(b).strip()
        if not shown or shown in used:
            continue
        mine = _content(shown)
        if not mine:
            continue
        shared = len(said & mine)
        score = shared / len(mine)
        if shared >= 2 and score >= 0.5 and score > best_score:
            best, best_score = shown, score
    return best


def _leading_clause(text: str, limit: int) -> Optional[str]:
    m = _CLAUSE_BREAK.search(text)
    if not m:
        return None
    clause = text[: m.start()].strip(" ,;:")
    if len(_TERM.findall(clause)) >= 5 and len(clause) <= limit:
        return clause
    return None


def screen_line(text: str, bullets: Sequence[str] = (), used: Optional[set] = None,
                limit: int = SCREEN_LINE_MAX) -> Optional[Dict[str, str]]:
    """Approved words for the screen, or None. Marks the chosen bullet as used."""
    used = used if used is not None else set()
    spoken = strip_markers(text).strip()
    bullet = _best_bullet(spoken, bullets, used)
    if bullet and len(bullet) <= limit:
        used.add(bullet)
        return {"text": bullet, "source": "slide_bullet"}
    if len(spoken) <= limit:
        return {"text": spoken, "source": "narration"}
    clause = _leading_clause(spoken, limit)
    if clause:
        return {"text": clause, "source": "narration"}
    return None


_DEFINED = re.compile(
    r"^(?P<term>[A-Z][\w\-]*(?:\s+[\w\-]+){0,4}?)"
    r"(?:,\s*or\s+(?P<abbr>[A-Z][A-Z0-9]{1,6}),)?"
    r"\s+(?:is defined as|refers to|means|describes|stands for|uses|is|are)\b")


def _defined_term(text: str) -> Optional[str]:
    """The thing a definition sentence defines: its subject, with its abbreviation."""
    m = _DEFINED.match(strip_markers(text).strip())
    if not m:
        return None
    term = m.group("term").strip()
    if term.lower() in _STOP or len(term) < 3:
        return None
    return "%s (%s)" % (term, m.group("abbr")) if m.group("abbr") else term


def _clause_or_none(text: str, limit: int) -> Optional[str]:
    spoken = strip_markers(text).strip()
    if len(spoken) <= limit:
        return spoken
    return _leading_clause(spoken, limit)


def decide_visual(beat: Beat, refs: Dict[int, Dict[str, Any]], *, template: str = "faceless",
                  used: Optional[set] = None) -> Dict[str, Any]:
    """Choose the treatment for one beat, in priority order, with a stated reason."""
    used = used if used is not None else set()
    text = beat.spoken_text
    low = text.lower()

    if beat.beat_type == "opening" and beat.is_slide_opening and beat.slide_index == 0:
        return {"visual_type": "TITLE",
                "reason": "Opens the course: title, audience and identity establish what this is.",
                "props": {"title": beat.slide_title, "subtitle": ""}}

    if beat.beat_type == "recap":
        bullets = [b for b in beat.slide_bullets if b.strip()][:4]
        if bullets:
            return {"visual_type": "RECAP",
                    "reason": "Closing summary: the takeaways are worth seeing together, not only hearing.",
                    "props": {"items": bullets, "title": beat.slide_title or "Key takeaways"}}

    # Every citation must resolve, whatever treatment the beat ends up with.
    for n in beat.citation_ids:
        if n not in refs:
            raise StoryboardError(
                "beat %s cites [%d], which is not in the approved reference list" % (beat.beat_id, n))

    # A reported study earns the card. A sentence that merely carries a citation does
    # not: it is treated by what it is (a definition, guidance, a figure) and its source
    # stays in the course materials, where the claim gate already verified it.
    evidence = _evidence_props(beat, refs) if beat.citation_ids and _is_study_report(beat) else None
    if evidence:
        return {"visual_type": "EVIDENCE_CARD",
                "reason": "Reports what a study found; the finding leads and its source sits underneath.",
                "props": evidence}

    # A number worth reading — an outcome, not a device setting.
    headline = [x for x in beat.statistics if _is_headline_statistic(x)]
    if headline and beat.beat_type != "transition":
        beat = beat  # treatment below uses the first headline figure
        return {"visual_type": "STATISTIC",
                "reason": "States a figure: showing it makes it readable and memorable, not just audible.",
                "props": {"value": headline[0],
                          "label": _statistic_label(text, headline[0]),
                          "context": beat.slide_title}}

    sides = _comparison_sides(beat) if any(c in low for c in COMPARISON_CUES) else None
    if sides:
        return {"visual_type": "COMPARISON",
                "reason": "Contrasts two things; side-by-side shows the difference the sentence describes.",
                "props": sides}

    if any(c in low for c in PROCESS_CUES):
        steps = _process_steps(beat)
        if len(steps) >= 2:
            return {"visual_type": "PROCESS",
                    "reason": "Describes a sequence; a staged diagram carries the order better than speech alone.",
                    "props": {"steps": steps, "title": beat.slide_title}}

    if any(c in low for c in DEFINITION_CUES) and beat.word_count >= 8:
        term = _defined_term(text)
        definition = _clause_or_none(text, 140)
        if term and definition:
            return {"visual_type": "TEXT_EMPHASIS",
                    "reason": "Defines the term being taught; the term itself is what should be on screen.",
                    "props": {"term": term, "definition": definition}}

    # Guidance the practitioner must act on: short, imperative, and easy to miss when
    # it is only spoken. It earns the screen more than most cited sentences do.
    if beat.beat_type == "practice":
        line = screen_line(text, beat.slide_bullets, used)
        if line:
            return {"visual_type": "TEXT_EMPHASIS", "component": "KeyTakeaway",
                    "reason": "Scope guidance the learner must apply; stated on screen so it is not missed.",
                    "props": line}

    # "Did not increase", "was not superior": a null result teaches as much as a
    # positive one and is the easiest thing to mishear as its opposite.
    if any(c in low for c in NULL_RESULT_CUES) and beat.word_count >= 8:
        line = screen_line(text, beat.slide_bullets, used)
        if line:
            return {"visual_type": "TEXT_EMPHASIS", "component": "KeyTakeaway",
                    "reason": "Reports what was NOT shown; on screen so the negative finding is not misheard.",
                    "props": line}

    if beat.beat_type == "closing":
        return {"visual_type": "RECAP", "component": "Outro",
                "reason": "Closes the course and points to the sources and next step.",
                "props": {"title": "Sources and next step",
                          "message": _clause_or_none(text, 140) or "",
                          "course_code": ""}}

    if beat.beat_type == "transition" or (beat.is_slide_opening and beat.beat_type == "teaching"):
        return {"visual_type": "SECTION_TRANSITION",
                "reason": "Turns to a new part of the lesson; a section title orients the viewer.",
                "props": {"title": beat.slide_title, "eyebrow": ""}}

    return {"visual_type": "NONE",
            "reason": "Narration carries this on its own; adding a visual here would be decoration.",
            "props": {}}


def _statistic_label(text: str, stat: str) -> str:
    """The few words around a number that say what it measures."""
    i = text.find(stat)
    if i < 0:
        return ""
    tail = text[i + len(stat):].strip(" ,.;:")
    words = tail.split()
    label = " ".join(words[:7]).strip(" ,.;:")
    if not label:
        head = text[:i].strip().split()
        label = " ".join(head[-7:])
    return label[:70]


def _definition_clause(text: str) -> str:
    m = re.search(r"\b(?:is defined as|refers to|means|describes)\b(.+)", text, re.I)
    return (m.group(1).strip(" ,.;:")[:140] if m else text[:140])


def build_storyboard(beats: Sequence[Beat],
                     references: Sequence[Dict[str, Any]],
                     sections: Sequence[Dict[str, Any]],
                     *,
                     template: str = "faceless",
                     config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Decide every beat, then apply the composition rules that keep it watchable."""
    cfg = (config or {}).get("storyboard", {}) if config else {}
    min_scene = float(cfg.get("min_scene_seconds", 2.2))
    max_scene = float(cfg.get("max_scene_seconds", 14))
    quiet_cfg = cfg.get("quiet_beat_ratio", {}) or {}
    quiet_min = float(quiet_cfg.get("min", 0.12))
    refs = _reference_index(references)

    segments: List[Dict[str, Any]] = []
    used: set = set()        # slide bullets already shown: each appears at most once
    for i, beat in enumerate(beats):
        choice = decide_visual(beat, refs, template=template, used=used)
        segments.append({
            "segment_id": "S%03d" % (i + 1),
            "section_id": _section_for(beat, sections),
            "slide_index": beat.slide_index,
            "start": beat.start,
            "end": beat.end,
            "narration": beat.text,
            "beat_type": beat.beat_type,
            "visual_type": choice["visual_type"],
            "visual_reason": choice["reason"],
            "component": choice.get("component") or COMPONENT_FOR.get(choice["visual_type"]),
            "props": choice["props"],
            "animation": ANIMATION_FOR.get(choice["visual_type"], "fade"),
            "emphasis_words": _emphasis_words(beat) if choice["visual_type"] != "NONE" else [],
            "citation_ids": [str(n) for n in beat.citation_ids],
            "quiet": choice["visual_type"] == "NONE",
            "asset_requirements": [],
            "_bullets": list(beat.slide_bullets),
        })

    segments = _merge_guidance(segments)
    segments = _enforce_variety(segments)
    segments = _enforce_durations(segments, min_scene, max_scene)
    segments = _enforce_quiet_floor(segments, quiet_min)
    segments = _enforce_quiet_ceiling(segments, float(quiet_cfg.get('max', 0.35)), refs, used)
    segments = _limit_transitions(segments, sections)
    segments = _enforce_pace(segments, max_scene, used)
    segments = _drop_redundant_titles(segments)
    for seg in segments:
        seg.pop("_bullets", None)

    return {
        "template": template,
        "decided_by": "rules",
        "rules_version": int(cfg.get("rules_version", 1)),
        "total_seconds": round(segments[-1]["end"], 3) if segments else 0.0,
        "sections": [{k: v for k, v in s.items() if k in ("id", "title", "start", "end", "slide_indexes")}
                     for s in sections],
        "segments": segments,
    }


def _section_for(beat: Beat, sections: Sequence[Dict[str, Any]]) -> Optional[str]:
    for s in sections:
        if beat.beat_id in s.get("beat_ids", []):
            return s["id"]
    return None


def _merge_guidance(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Consecutive guidance beats are one point, so they get one card.

    "Stay within scope. Present PBM as a wellness service, not a medical treatment."
    is a single instruction delivered in two sentences. Two cards in a row would cut
    between them for no reason; one card holds while both are spoken, and it shows the
    more specific sentence — still verbatim, never a summary written here.
    """
    out: List[Dict[str, Any]] = []
    for seg in segments:
        prev = out[-1] if out else None
        is_guidance = seg.get("component") == "KeyTakeaway"
        if prev is not None and is_guidance and prev.get("component") == "KeyTakeaway":
            prev["end"] = seg["end"]
            candidate = (seg.get("props") or {}).get("text") or ""
            current = (prev.get("props") or {}).get("text") or ""
            prev.setdefault("covers", []).append(seg["segment_id"])
            if len(candidate) > len(current):
                prev["props"] = dict(seg.get("props") or {})
            prev["visual_reason"] = ("Holds one guidance card across both sentences: they state a single "
                                     "instruction, and cutting between them would add a change with no meaning.")
            seg.update({"visual_type": "NONE", "component": None, "props": {}, "quiet": True,
                        "emphasis_words": [],
                        "visual_reason": "Covered by the guidance card already on screen."})
        out.append(seg)
    return segments


def _enforce_variety(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """No more than two identical treatments in a row.

    Three of the same card back to back is the single clearest sign of a template
    filling time. The third becomes quiet: the narration still delivers it, and
    the two that remain carry more weight for it.
    """
    run_type, run_len = None, 0
    for seg in segments:
        vt = seg["visual_type"]
        if vt == "NONE":
            run_type, run_len = None, 0
            continue
        if vt == run_type:
            run_len += 1
            if run_len >= 3:
                seg.update({
                    "visual_type": "NONE", "component": None, "props": {}, "quiet": True,
                    "emphasis_words": [],
                    "visual_reason": "Third %s in a row would read as a template; the narration carries this beat." % run_type,
                })
                run_type, run_len = None, 0
        else:
            run_type, run_len = vt, 1
    return segments


def _enforce_durations(segments: List[Dict[str, Any]], min_scene: float, max_scene: float) -> List[Dict[str, Any]]:
    """Merge visuals too short to read; split nothing, but cap how long one holds.

    A card that flashes for 0.8 s is worse than no card: the viewer registers
    movement, fails to read it, and loses the narration while trying.
    """
    for i, seg in enumerate(segments):
        if seg["visual_type"] == "NONE":
            continue
        duration = seg["end"] - seg["start"]
        if duration >= min_scene:
            continue
        nxt = segments[i + 1] if i + 1 < len(segments) else None
        if nxt and nxt["visual_type"] in (seg["visual_type"], "NONE"):
            # Extend this visual over the next beat instead of cutting to another.
            seg["end"] = nxt["end"]
            nxt.update({"visual_type": "NONE", "component": None, "props": {}, "quiet": True,
                        "emphasis_words": [],
                        "visual_reason": "Held the previous visual: this beat is too short to justify a new one."})
        else:
            seg.update({"visual_type": "NONE", "component": None, "props": {}, "quiet": True,
                        "emphasis_words": [],
                        "visual_reason": "Too short to be read at %.1fs; kept visually quiet." % duration})
    for seg in segments:
        if seg["visual_type"] != "NONE" and (seg["end"] - seg["start"]) > max_scene:
            seg["hold_until"] = round(seg["start"] + max_scene, 3)
    return segments


def _enforce_quiet_floor(segments: List[Dict[str, Any]], quiet_min: float) -> List[Dict[str, Any]]:
    """Guarantee some breathing room.

    If almost every beat has a visual, the ones that matter stop standing out. The
    beats given back to silence are the weakest ones: plain teaching sentences with
    no citation and no number.
    """
    if not segments:
        return segments
    quiet = sum(1 for s in segments if s["visual_type"] == "NONE")
    target = int(len(segments) * quiet_min)
    if quiet >= target:
        return segments

    candidates = [s for s in segments
                  if s["visual_type"] in ("SECTION_TRANSITION", "TEXT_EMPHASIS")
                  and not s["citation_ids"]]
    candidates.sort(key=lambda s: s["end"] - s["start"])
    for seg in candidates:
        if quiet >= target:
            break
        seg.update({"visual_type": "NONE", "component": None, "props": {}, "quiet": True,
                    "emphasis_words": [],
                    "visual_reason": "Left quiet so the surrounding visuals carry weight."})
        quiet += 1
    return segments


def _enforce_quiet_ceiling(segments: List[Dict[str, Any]], quiet_max: float,
                           refs: Dict[int, Dict[str, Any]], used: Optional[set] = None) -> List[Dict[str, Any]]:
    """Give the screen back to the strongest silent beats when too much is quiet.

    A floor stops the video being busy; without a ceiling the same rules produce a
    lecture over a static frame, which is the other way to look unfinished. Promotion
    is by salience, not by order: a number the viewer should read, then a null result,
    then the longest teaching sentence.
    """
    if not segments:
        return segments
    quiet = [s for s in segments if s["visual_type"] == "NONE"]
    allowed = int(len(segments) * quiet_max)
    if len(quiet) <= allowed:
        return segments

    def salience(seg: Dict[str, Any]) -> tuple:
        text = seg.get("narration") or ""
        has_stat = bool(STATISTIC.search(text))
        is_null = any(c in text.lower() for c in NULL_RESULT_CUES)
        return (has_stat, is_null, seg["end"] - seg["start"])

    for seg in sorted(quiet, key=salience, reverse=True):
        if len(quiet) <= allowed:
            break
        text = seg.get("narration") or ""
        if seg.get('slide_index') == 0:
            continue  # the title card is already holding; do not stack on it
        stat = next((m.group(0) for m in STATISTIC.finditer(text)
                     if _is_headline_statistic(m.group(0))), None)
        if stat:
            seg.update({"visual_type": "STATISTIC", "component": COMPONENT_FOR["STATISTIC"],
                        "animation": ANIMATION_FOR["STATISTIC"],
                        "props": {"value": stat, "label": _statistic_label(text, stat),
                                  "context": ""},
                        "visual_reason": "Carries a figure the viewer should be able to read.",
                        "quiet": False})
        elif (seg["end"] - seg["start"]) >= 3.0 and screen_line(text, seg.get("_bullets", ()), set(used or ())):
            line = screen_line(text, seg.get("_bullets", ()), used if used is not None else set())
            seg.update({"visual_type": "TEXT_EMPHASIS", "component": "KeyTakeaway",
                        "animation": ANIMATION_FOR["TEXT_EMPHASIS"],
                        "props": line,
                        "visual_reason": "Too long a stretch with nothing on screen; states the point being made.",
                        "quiet": False})
        else:
            continue
        quiet = [s for s in segments if s["visual_type"] == "NONE"]
    return segments


def _limit_transitions(segments: List[Dict[str, Any]], sections: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A transition marks a section change, never merely a cut."""
    starts = {round(s["start"], 2) for s in sections}
    for seg in segments:
        if seg["visual_type"] == "SECTION_TRANSITION" and round(seg["start"], 2) not in starts:
            seg.update({"visual_type": "TEXT_EMPHASIS", "component": COMPONENT_FOR["TEXT_EMPHASIS"],
                        "animation": ANIMATION_FOR["TEXT_EMPHASIS"],
                        "visual_reason": "Not a section boundary, so emphasis rather than a section title."})
            if not seg["props"].get("term"):
                seg["props"] = {"term": (seg["props"].get("title") or "").strip(), "definition": ""}
    return segments


def _drop_redundant_titles(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A section title immediately followed by a card with the same title says it twice."""
    visuals = [s for s in segments if s["visual_type"] != "NONE"]
    for a, b in zip(visuals, visuals[1:]):
        if a["visual_type"] != "SECTION_TRANSITION":
            continue
        ta = str((a.get("props") or {}).get("title") or "").strip().lower()
        tb = str((b.get("props") or {}).get("title") or "").strip().lower()
        if ta and ta == tb:
            a.update({"visual_type": "NONE", "component": None, "props": {}, "quiet": True,
                      "emphasis_words": [],
                      "visual_reason": "The next card carries the same title; a section title here would repeat it."})
    return segments


def _enforce_pace(segments: List[Dict[str, Any]], max_hold: float,
                  used: Optional[set] = None) -> List[Dict[str, Any]]:
    """The screen must change at least every `max_hold` seconds.

    A visual holds until the next one starts, which is what keeps frames from going
    empty — but held too long it stops being restraint and becomes a stall. Where a
    gap is too wide, the strongest quiet beat inside it is promoted so the picture
    moves with the narration instead of waiting for it.
    """
    used = used if used is not None else set()
    tried: set = set()       # beats with nothing showable; never picked again
    guard = 0
    while guard < 40:
        guard += 1
        visuals = [i for i, s in enumerate(segments) if s["visual_type"] != "NONE"]
        if not visuals:
            return segments
        promoted = False
        for pos, idx in enumerate(visuals):
            start = segments[idx]["start"]
            nxt = segments[visuals[pos + 1]]["start"] if pos + 1 < len(visuals) else segments[-1]["end"]
            if nxt - start <= max_hold:
                continue
            gap = [j for j in range(idx + 1, len(segments))
                   if segments[j]["visual_type"] == "NONE" and segments[j]["start"] < nxt
                   and j not in tried]
            if not gap:
                continue
            # Prefer a beat near the middle of the gap with something concrete to show.
            def score(j: int) -> tuple:
                seg = segments[j]
                text = seg.get("narration") or ""
                return (bool(STATISTIC.search(text)), seg["end"] - seg["start"])

            j = max(gap, key=score)
            seg = segments[j]
            text = seg.get("narration") or ""
            stat = next((m.group(0) for m in STATISTIC.finditer(text) if _is_headline_statistic(m.group(0))), None)
            if stat:
                seg.update({"visual_type": "STATISTIC", "component": COMPONENT_FOR["STATISTIC"],
                            "animation": ANIMATION_FOR["STATISTIC"],
                            "props": {"value": stat, "label": _statistic_label(text, stat), "context": ""}})
            else:
                line = screen_line(text, seg.get("_bullets", ()), used)
                if not line:
                    tried.add(j)
                    promoted = True     # re-scan the same gap without this beat
                    break
                seg.update({"visual_type": "TEXT_EMPHASIS", "component": "KeyTakeaway",
                            "animation": ANIMATION_FOR["TEXT_EMPHASIS"], "props": line})
            seg.update({"quiet": False,
                        "visual_reason": "The previous visual would otherwise hold for %.0fs; the screen "
                                         "should move with the narration." % (nxt - start)})
            promoted = True
            break
        if not promoted:
            return segments
    return segments


def validate_storyboard(storyboard: Dict[str, Any],
                        references: Sequence[Dict[str, Any]],
                        narration_by_segment: Optional[Dict[str, str]] = None,
                        approved_bullets: Optional[Iterable[str]] = None) -> List[str]:
    """Check a storyboard is renderable and honest. Returns a list of problems.

    Run on rules output AND on anything an LLM or agent produced, because the point
    of the check is to catch content that was invented rather than selected.
    """
    problems: List[str] = []
    refs = _reference_index(references)
    bullets = {strip_markers(b).strip() for b in (approved_bullets or [])}
    said = {s.get("segment_id"): strip_markers(s.get("narration") or "")
            for s in storyboard.get("segments", [])}
    for seg in storyboard.get("segments", []):
        sid = seg.get("segment_id", "?")
        # A card held across several sentences may show any of them, verbatim.
        spoken = " ".join([said.get(sid, "")] + [said.get(c, "") for c in seg.get("covers", [])])
        props = seg.get("props") or {}
        for key in ("text", "finding", "message", "definition"):
            shown = props.get(key)
            if not shown:
                continue
            if shown.rstrip().endswith(("...", "\u2026")) and not spoken.rstrip().endswith(("...", "\u2026")):
                problems.append("%s: on-screen %s is cut off mid-thought" % (sid, key))
            source = props.get("source") if key == "text" else "narration"
            if source == "slide_bullet":
                if approved_bullets is not None and shown not in bullets:
                    problems.append("%s: on-screen text claims to be a slide bullet but is not one" % sid)
            elif shown.lower() not in spoken.lower():
                problems.append("%s: on-screen %s is not verbatim narration" % (sid, key))
        term = props.get("term")
        if term and seg.get("component") == "KeywordHighlight":
            missing = [w for w in _TERM.findall(term) if w.lower() not in spoken.lower()]
            if missing:
                problems.append("%s: highlighted term %r is not spoken" % (sid, term))
        if seg.get("visual_type") not in VISUAL_TYPES:
            problems.append("%s: unknown visual_type %r" % (sid, seg.get("visual_type")))
        if not str(seg.get("visual_reason") or "").strip():
            problems.append("%s: no visual_reason" % sid)
        if seg.get("end", 0) <= seg.get("start", 0):
            problems.append("%s: end is not after start" % sid)
        for cid in seg.get("citation_ids", []):
            try:
                if int(cid) not in refs:
                    problems.append("%s: cites [%s], not in the approved reference list" % (sid, cid))
            except (TypeError, ValueError):
                problems.append("%s: citation id %r is not a number" % (sid, cid))
        narration = (narration_by_segment or {}).get(sid)
        if narration is not None and seg.get("narration") != narration:
            problems.append("%s: narration was modified; approved wording must be verbatim" % sid)
        for word in seg.get("emphasis_words", []):
            if word and word.lower() not in (seg.get("narration") or "").lower():
                problems.append("%s: emphasis word %r is not in the narration" % (sid, word))
        stat = props.get("statistic") or props.get("value")
        shown_text = props.get("finding") if seg.get("component") == "EvidenceCard" else None
        if stat and shown_text and str(stat) not in shown_text:
            problems.append("%s: headline figure %r is not in the finding shown with it" % (sid, stat))
        if seg.get("visual_type") == "EVIDENCE_CARD" and not seg.get("citation_ids"):
            problems.append("%s: evidence card with no citation" % sid)
    return problems
