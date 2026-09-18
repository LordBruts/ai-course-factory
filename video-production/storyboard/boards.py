"""Boards: pages that build up while the narration speaks.

The first faceless design showed one statement per screen, each replacing the last. A
course is taught the other way: a page stays up and grows. This module turns the beat
decisions from `rules.build_storyboard` into boards:

    hero      course title, then it rises into a header while the roadmap draws in
    stack     a topic header that stays; each point enters below the last and stays
    gallery   "THE RESEARCH": each study enters large in the centre, then shrinks
              into a corner slot (top-right, bottom-right, top-left, bottom-left)
              and the next study takes the centre
    recap     key takeaways, building item by item
    outro     sources and next step

It decides WHAT appears and WHEN; `templates/motion/board.py` decides WHERE and how it
moves. Everything an element shows is approved text (verbatim sentence fragments,
approved slide bullets, fields of the approved reference list) — the validator in this
module checks that before anything is rendered.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence

import infographics as ig
from beats import STATISTIC, NULL_RESULT_CUES, strip_markers
from rules import _is_study_report, screen_line

GALLERY_EYEBROW = "THE RESEARCH"
FIXED_LABELS = {GALLERY_EYEBROW, "KEY TAKEAWAYS", "STUDY", "REVIEW", "TRIAL", "TRIALS",
                "COURSE", "SOURCES", "NEXT STEP", "DO", "DON'T", "GYMRAMP"}

_OUTCOME = re.compile(
    r"\b(reported no adverse events|was not superior to placebo|reports? promising effects"
    r"|reported consistent short-term pain and quality-of-life improvements"
    r"|(?:did not (?:beat|increase)|showed better) [^,.;]*?(?=\s+(?:for|in|at|on)\b|[,.;]|$))", re.I)
_SUBJECT = re.compile(
    r"\b((?:A|One|Some|Two|Several)\s+(?:[\w\-]+\s+){0,3}?(?:systematic\s+)?(?:review|study|trial|trials|meta-analysis))\b",
    re.I)
_POP = re.compile(r"^(In|Among)\s+([^,]+),")


def short_citation(ref: Dict[str, Any]) -> Dict[str, str]:
    """'Lawrence, J., & Sorra, K. (2024). Title. Journal. doi' -> parts for a card."""
    text = ref.get("citation") or ""
    m = re.match(r"(?P<authors>.+?)\s*\((?P<year>\d{4})[^)]*\)\.\s*(?P<title>.+?)\.\s+(?P<journal>[^.]+?)\.(?:\s|$)", text)
    if not m:
        return {"short": "[%s]" % ref.get("n"), "year": "", "journal": ""}
    surnames = re.findall(r"(?:^|&\s*|\.,\s*)([A-Z][A-Za-z'\-]+(?:\s[A-Z][A-Za-z'\-]+)?),", m.group("authors"))
    first = surnames[0] if surnames else m.group("authors").split(",")[0]
    if len(surnames) == 2 and "&" in m.group("authors") and m.group("authors").count(",") <= 4:
        short = "%s & %s" % (surnames[0], surnames[1])
    elif len(surnames) >= 2 or m.group("authors").count(",") > 2:
        short = "%s et al." % first
    else:
        short = first
    return {"short": short, "year": m.group("year"), "journal": m.group("journal").strip()}


def _study_like(seg: Dict[str, Any]) -> bool:
    if not seg.get("citation_ids"):
        return False
    text = strip_markers(seg.get("narration") or "")
    low = text.lower()
    beat = SimpleNamespace(spoken_text=text)
    return (_is_study_report(beat) or any(c in low for c in NULL_RESULT_CUES)
            or bool(_POP.match(text) and len(text.split()) >= 10))


def study_props(seg: Dict[str, Any], refs: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    text = strip_markers(seg["narration"]).strip().rstrip(".")
    markers = [int(c) for c in seg.get("citation_ids", [])]
    ref = refs.get(markers[0], {}) if markers else {}
    cite = short_citation(ref) if ref else {"short": "", "year": "", "journal": ""}
    subject = _SUBJECT.search(text)
    pop = _POP.match(text)
    title = subject.group(1) if subject else (pop.group(2) if pop else "")
    outcome = _OUTCOME.search(text)
    spec = ig.time_points(text) or ig.contrast(text) or ig.enumeration(text) or ig.wavelengths(text)
    finding_line = screen_line(text, (), set(), limit=180)
    finding = (spec or {}).get("main") if (spec or {}).get("kind") == "contrast" else \
        (finding_line or {}).get("text")
    if (spec or {}).get("kind") == "time_points":
        finding = None
    if (spec or {}).get("kind") == "enumeration":
        finding = spec["lead"] or finding
    kind = "REVIEW" if re.search(r"\breview\b|meta-analysis", text, re.I) else (
        "TRIALS" if re.search(r"\btrials\b", text, re.I) else "STUDY")
    return {
        "markers": markers,
        "kind_label": kind,
        "title": title,
        "finding": finding,
        "outcome": outcome.group(1) if outcome else "",
        "null_result": any(c in text.lower() for c in NULL_RESULT_CUES) and not re.search(
            r"reported no adverse events", text, re.I),
        "short_citation": cite["short"],
        "year": cite["year"],
        "journal": cite["journal"],
        "spec": spec if (spec or {}).get("kind") != "contrast" else {
            "kind": "contrast", "main": spec["main"], "turn": spec["turn"], "caution": spec["caution"]},
    }


def _element_for(seg: Dict[str, Any], bullets: Sequence[str], used: set) -> Optional[Dict[str, Any]]:
    """What a non-study sentence adds to a stack board."""
    text = strip_markers(seg["narration"]).strip()
    words = len(text.split())
    props = seg.get("props") or {}
    cons = ig.consequence(text)
    if cons:
        return {"kind": "statement", "text": cons["text"], "link": cons["link"],
                "icon": "circle-alert" if re.search(r"caut|careful|limit", text, re.I) else ig.icon_for(text),
                "tone": "caution"}
    spec = ig.detect(text)
    if seg.get("component") == "KeywordHighlight" and props.get("term"):
        return {"kind": "term", "term": props["term"], "definition": props.get("definition") or "",
                "spec": spec if (spec or {}).get("kind") == "light_band" else None}
    link = "But" if ig.opens_with_but(text) else None
    if spec and spec["kind"] != "light_band":
        return {"kind": "infographic", "spec": spec, "link": link or spec.get("link")}
    if words <= 6 and seg.get("beat_type") == "practice":
        return {"kind": "chip", "text": text.rstrip("."), "icon": ig.icon_for(text, "target"), "tone": "accent"}
    if words < 6:
        return None
    line = screen_line(text, bullets, used)
    if not line:
        return None
    return {"kind": "statement", "text": line["text"], "source": line["source"], "link": link,
            "icon": ig.icon_for(line["text"] + " " + text)}


def plan_boards(storyboard: Dict[str, Any], slides: Sequence[Dict[str, Any]],
                references: Sequence[Dict[str, Any]], course_title: str = "") -> List[Dict[str, Any]]:
    refs = {int(r["n"]): r for r in references or [] if r.get("n") is not None}
    segs = storyboard["segments"]
    total = float(storyboard.get("total_seconds") or segs[-1]["end"])

    # -- group sentences by slide, then merge research slides into one gallery ------
    by_slide: Dict[int, List[Dict[str, Any]]] = {}
    for s in segs:
        by_slide.setdefault(s["slide_index"], []).append(s)
    order = sorted(by_slide)

    def kind_of(idx: int) -> str:
        slide = slides[idx] if idx < len(slides) else {}
        k = slide.get("deck_kind") or slide.get("kind") or ("title" if idx == 0 else "content")
        if k == "title":
            return "hero"
        if k == "takeaways":
            return "recap"
        if k in ("references", "closing"):
            return "outro"
        items = [s for s in by_slide[idx] if len(strip_markers(s["narration"]).split()) >= 8]
        studies = [s for s in items if _study_like(s)]
        return "gallery" if items and len(studies) * 2 >= len(items) and len(studies) >= 2 else "stack"

    groups: List[Dict[str, Any]] = []
    for idx in order:
        k = kind_of(idx)
        if k == "gallery" and groups and groups[-1]["kind"] == "gallery":
            groups[-1]["slides"].append(idx)
        else:
            groups.append({"kind": k, "slides": [idx]})

    boards: List[Dict[str, Any]] = []
    used: set = set()
    for g_i, g in enumerate(groups):
        g_segs = [s for idx in g["slides"] for s in by_slide[idx]]
        start = 0.0 if g_i == 0 else round(g_segs[0]["start"] - 0.25, 3)
        board = {"board_id": "B%02d" % (g_i + 1), "kind": g["kind"], "start": start, "end": None,
                 "eyebrow": "", "titles": [], "elements": []}
        counter = 0

        def add(el: Dict[str, Any]) -> None:
            nonlocal counter
            counter += 1
            el.setdefault("element_id", "%s-E%02d" % (board["board_id"], counter))
            board["elements"].append(el)

        for idx in g["slides"]:
            slide = slides[idx] if idx < len(slides) else {}
            first = by_slide[idx][0]
            title = slide.get("title") or ""
            if g["kind"] == "hero":
                title = course_title or title
            board["titles"].append({"text": title, "at": start if not board["titles"] else round(first["start"] - 0.2, 3),
                                    "slide_index": idx})
        if g["kind"] == "gallery":
            board["eyebrow"] = GALLERY_EYEBROW

        for idx in g["slides"]:
            bullets = (slides[idx] if idx < len(slides) else {}).get("bullets") or []
            for seg in by_slide[idx]:
                at = round(max(board["start"], seg["start"] - 0.1), 3)
                base = {"segment_id": seg["segment_id"], "enter_at": at,
                        "speak_start": seg["start"], "speak_end": seg["end"],
                        "sentence": strip_markers(seg["narration"]).strip(), "slide_index": idx}
                if g["kind"] in ("stack", "gallery") and _study_like(seg):
                    add({**base, "kind": "study", "study": study_props(seg, refs)})
                    continue
                if g["kind"] == "gallery":
                    text = base["sentence"].rstrip(".")
                    if len(text.split()) >= 4:
                        add({**base, "kind": "subtitle", "text": text, "icon": ig.icon_for(text, "microscope")})
                    continue
                if g["kind"] == "outro":
                    text = base["sentence"].rstrip(".")
                    icon = ig.icon_for(text, "book-open")
                    add({**base, "kind": "statement", "text": text, "icon": icon,
                         "tone": "accent" if len(board["elements"]) else "plain"})
                    continue
                el = _element_for(seg, bullets, used)
                if el:
                    add({**base, **el})

        boards.append(board)

    for i, b in enumerate(boards):
        b["end"] = round(boards[i + 1]["start"], 3) if i + 1 < len(boards) else round(total, 3)
        _schedule(b)
    return boards


def _schedule(board: Dict[str, Any]) -> None:
    """Dock times for studies, stagger times for list items."""
    els = board["elements"]
    studies = [e for e in els if e["kind"] == "study"]
    for i, e in enumerate(els):
        if e["kind"] != "study":
            continue
        following = next((x for x in els[i + 1:]), None)
        nxt = following["enter_at"] if following else board["end"]
        # The focus card is still shrinking 0.3 s into its dock, so whatever comes next
        # waits for it; a gallery subtitle sits in the header row and never meets it.
        gap = 0.15 if following is not None and following["kind"] == "subtitle" else 0.35
        dock = max(e["speak_end"] + 0.2, e["enter_at"] + 3.4)
        if e is studies[-1]:
            # The assembled gallery is the payoff: let it be seen before the page turns.
            dock = min(dock, max(board["end"] - 1.8, e["enter_at"] + 3.4))
        e["dock_at"] = round(min(dock, nxt - gap, board["end"] - 0.6), 3)
        e["slot"] = studies.index(e)
    for e in els:
        spec = e.get("spec") or (e.get("study") or {}).get("spec")
        labels = []
        if spec and spec.get("kind") in ("enumeration", "roadmap"):
            labels = [x["label"] for x in spec["items"]]
        elif spec and spec.get("kind") == "scale":
            labels = [x["label"] for x in spec["steps"]]
        elif spec and spec.get("kind") == "time_points":
            labels = [x["text"] for x in spec["points"]]
        elif spec and spec.get("kind") == "wavelengths":
            labels = [x["source"] for x in spec["marks"]]
        if labels:
            e["item_times"] = _word_times(e["sentence"], labels, e["speak_start"], e["speak_end"], e["enter_at"])
            if board["kind"] == "hero" and e["kind"] == "infographic":
                # The title holds until the list is about to be spoken, then the roadmap draws.
                e["enter_at"] = round(max(e["enter_at"], e["item_times"][0] - 1.0), 3)


def _word_times(sentence: str, labels: Sequence[str], start: float, end: float, floor: float) -> List[float]:
    """When each label is spoken, by its position in the sentence (proportional)."""
    n = max(1, len(sentence))
    out = []
    for lab in labels:
        pos = sentence.find(lab)
        frac = (pos / n) if pos >= 0 else 0.0
        out.append(round(max(floor + 0.25, start + frac * (end - start)), 3))
    for i in range(1, len(out)):
        out[i] = max(out[i], out[i - 1] + 0.25)
    return out


# ---------------------------------------------------------------- validation ---

_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _texts(el: Dict[str, Any]) -> List[Dict[str, str]]:
    """(field, value, kind) for everything an element would draw."""
    out = []
    for key in ("text", "term", "definition"):
        if el.get(key):
            out.append({"field": key, "value": el[key]})
    spec = el.get("spec")
    study = el.get("study")
    if study:
        for key in ("title", "finding", "outcome"):
            if study.get(key):
                out.append({"field": "study." + key, "value": study[key]})
        spec = study.get("spec")
    if spec:
        for lab in ig.labels_of(spec):
            out.append({"field": "spec.%s" % spec["kind"], "value": lab})
    return out


def validate_boards(boards: Sequence[Dict[str, Any]], approved_text: str,
                    bullets: Sequence[str], references: Sequence[Dict[str, Any]]) -> List[str]:
    problems: List[str] = []
    approved = strip_markers(approved_text)
    shown_bullets = {strip_markers(b).strip() for b in bullets}
    cite_text = " ".join(r.get("citation", "") for r in references or [])
    allowed_numbers = set(_NUM.findall(approved + " " + " ".join(shown_bullets))) | set(_NUM.findall(cite_text))
    for b in boards:
        if b["end"] <= b["start"]:
            problems.append("%s: board ends before it starts" % b["board_id"])
        slots = [e.get("slot") for e in b["elements"] if e["kind"] == "study"]
        if len(slots) != len(set(slots)):
            problems.append("%s: two studies share a dock slot" % b["board_id"])
        for e in b["elements"]:
            if not (b["start"] - 0.01 <= e["enter_at"] < b["end"]):
                problems.append("%s: enters outside its board" % e["element_id"])
            if e["kind"] == "study" and not (e["enter_at"] < e["dock_at"] <= b["end"]):
                problems.append("%s: dock time outside the focus window" % e["element_id"])
            for t in _texts(e):
                v = t["value"]
                if v in shown_bullets or v in approved:
                    continue
                if t["field"] == "term" and all(w in approved for w in re.findall(r"[A-Za-z][\w\-]*", v)):
                    continue   # "Photobiomodulation (PBM)": every word of it is spoken
                problems.append("%s: %s %r is not approved wording" % (e["element_id"], t["field"], v))
            study = e.get("study") or {}
            for field in ("short_citation", "journal"):
                if study.get(field) and not all(part in cite_text for part in
                                                re.split(r"\s+(?:&|et al\.)\s*", study[field]) if part):
                    problems.append("%s: %s %r is not from the reference list" % (e["element_id"], field, study[field]))
            for n in study.get("markers", []):
                if n not in {int(r["n"]) for r in references}:
                    problems.append("%s: cites [%s], not in the reference list" % (e["element_id"], n))
            spec = e.get("spec") or study.get("spec") or {}
            for num in ig.numbers_of(spec) + [x for t in _texts(e) for x in _NUM.findall(t["value"])]:
                if num not in allowed_numbers:
                    problems.append("%s: number %s is not in the approved course" % (e["element_id"], num))
        for t in b["titles"]:
            if t["text"] and t["text"] not in approved:
                problems.append("%s: title %r is not an approved slide or course title" % (b["board_id"], t["text"]))
    return problems


def pace_gaps(boards: Sequence[Dict[str, Any]], limit: float) -> List[Dict[str, Any]]:
    """Stretches longer than `limit` in which nothing enters, docks or changes."""
    events = []
    for b in boards:
        events.append(b["start"])
        for e in b["elements"]:
            events.append(e["enter_at"])
            if e.get("dock_at"):
                events.append(e["dock_at"])
            events += e.get("item_times", [])
        events += [t["at"] for t in b["titles"]]
    events = sorted(set(round(x, 2) for x in events))
    end = boards[-1]["end"] if boards else 0
    gaps = []
    for a, z in zip(events, events[1:] + [end]):
        if z - a > limit:
            gaps.append({"from": a, "to": z, "seconds": round(z - a, 2)})
    return gaps
