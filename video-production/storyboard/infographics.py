"""Infographic detection: which picture explains this sentence, built from its own words.

Every detector reads one approved sentence and either returns a spec or None. The one
rule they share: **every label in a spec is a verbatim substring of the sentence**
(checked by `labels_of` + the validator), and any number shown is a number the
sentence states. The picture is a way of seeing what is said, never a way of saying
more.

    enumeration   "A, B, and C" / "including A, B, and C"   -> icon nodes or checklist
    roadmap       "what X, what Y, why Z, and how W"         -> numbered path
    scale         "promising in places, mixed in others, and not a guarantee"
    do_dont       "Present PBM as X, not Y"                  -> do / don't split
    devices       "Lasers and LED devices differ"            -> device pair
    wavelengths   "650 nanometre ... 630 plus 850 nanometre" -> spectrum ruler
    light_band    "red or near-infrared light"                -> colour band
    time_points   "... at one hour, but ... at 24 and 48 hours" -> time strip
    contrast      "X, but Y" / "X, though Y"                  -> main + caution
    consequence   "That means ..." / "... because ..."        -> arrow into this item
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from beats import strip_markers

# Keyword -> Lucide icon (templates/motion/icons). Checked in order; first hit wins.
ICON_FOR = [
    (r"wavelength|nanomet|\bnm\b|spectrum", "waves"),
    (r"\bdose|energy dose|intensity", "gauge"),
    (r"timing|\bhours?\b|minutes?", "clock"),
    (r"target|application", "crosshair"),
    (r"laser", "zap"),
    (r"\bled\b|light|red light", "lightbulb"),
    (r"metabolism|bioenerget|mitochond|energy", "battery-charging"),
    (r"oxidative|stress", "flame"),
    (r"inflamm|immune|signal", "activity"),
    (r"safety|adverse|safe", "shield-check"),
    (r"source|claim|reference|literature", "book-open"),
    (r"exam|certification|course", "graduation-cap"),
    (r"research|study|studies|review|evidence", "microscope"),
    (r"discuss|communicat|client|talk", "message-circle"),
    (r"scope|role", "target"),
    (r"pain", "heart-pulse"),
    (r"muscle|strength|endurance|jump|performance", "dumbbell"),
    (r"fatigue|recovery", "battery-charging"),
    (r"protocol|compare", "sliders-horizontal"),
    (r"uncertain|caution|cautious", "circle-alert"),
    (r"understand|learn|what", "lightbulb"),
    (r"wellness", "leaf"),
    (r"medical|treatment", "stethoscope"),
]


def icon_for(text: str, default: str = "circle-dot") -> str:
    low = (text or "").lower()
    for pattern, icon in ICON_FOR:
        if re.search(pattern, low):
            return icon
    return default


_LEADING_JUNK = re.compile(r"^(?:and|or|including|such as|like|the|in|on|of|to)\s+", re.I)
_WH = re.compile(r"^(?:what|why|how|when|where|which|who)\b", re.I)
_NUM_WORD = r"(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty-four)"


def _clean(text: str) -> str:
    return text.strip().strip(" ,.;:")


def _strip_leading(item: str) -> str:
    prev = None
    while prev != item:
        prev = item
        item = _LEADING_JUNK.sub("", item)
    return _clean(item)


def _pieces(sentence: str) -> List[str]:
    return [p for p in re.split(r",\s+", _clean(sentence)) if p]


def _cut_at_preposition(item: str, max_words: int) -> str:
    """'reduced fatigue in sport performance studies' -> 'reduced fatigue'."""
    words = item.split()
    if len(words) <= max_words:
        return item
    m = re.search(r"\s+(?:in|on|for|at|from|with|across|during|than)\s+", item)
    if m and len(item[: m.start()].split()) <= max_words:
        return item[: m.start()]
    return " ".join(words[:max_words])


def enumeration(sentence: str) -> Optional[Dict[str, Any]]:
    """A list of three or more things. Returns lead + items, all verbatim."""
    s = strip_markers(sentence)
    pieces = _pieces(s)
    last = next((i for i, p in enumerate(pieces) if re.match(r"(?:and|or)\s+", p, re.I) and i >= 2), None)
    if last is None:
        return None
    # Walk back over short pieces: those are the list items.
    roadmap = all(_WH.match(_strip_leading(p)) for p in pieces[max(1, last - 1): last + 1])
    limit = 12 if roadmap else 3
    start = last
    if roadmap:
        # A roadmap is a run of wh-clauses; the clause before the run holds the first one.
        while start - 1 > 0 and _WH.match(_strip_leading(pieces[start - 1])):
            start -= 1
    else:
        while start - 1 > 0 and len(pieces[start - 1].split()) <= limit and not re.search(
                r"\b(?:is|are|was|were)\b.*\b(?:that|to)\b", pieces[start - 1]):
            start -= 1
    items: List[str] = []
    for p in pieces[start: last + 1]:
        items.append(_cut_at_preposition(_strip_leading(p), limit))
    head = pieces[start - 1] if start - 1 >= 0 else ""
    lead = ""
    first_is_intro = bool(re.match(r"(?:including|such as)\b", pieces[start], re.I))
    if not first_is_intro and head:
        # The first item hides at the end of the preceding piece.
        if roadmap:
            m = re.search(r"\b(?:what|why|how|when|where|which|who)\b.*$", head, re.I)
            first = m.group(0) if m else ""
        else:
            k = max(len(x.split()) for x in items)
            words = head.split()
            first = " ".join(words[-k:])
            first = _strip_leading(first)
        if first:
            items.insert(0, first)
            lead = _clean(head[: head.rfind(first)])
    else:
        lead = _clean(head)
    lead = re.sub(r"\s+(?:on|in|of|to|for)$", "", lead)
    if len(items) < 3 or any(not i for i in items):
        return None
    # "Protocol design matters because studies vary in" -> lead "Protocol design matters", link "because"
    link = None
    m = re.search(r"\s+(because|so that|so)\s+", lead)
    if m:
        link, lead = m.group(1), lead[: m.start()]
    spec = {"kind": "roadmap" if roadmap else "enumeration", "lead": lead, "link": link,
            "items": [{"label": i, "icon": icon_for(i)} for i in items]}
    return spec


def scale(sentence: str) -> Optional[Dict[str, Any]]:
    s = strip_markers(sentence)
    if not re.search(r"\bin places\b.*\bin others\b", s, re.I):
        return None
    enum = enumeration(s)
    if not enum:
        return None
    lead = enum["lead"]
    return {"kind": "scale", "lead": lead,
            "steps": [{"label": x["label"]} for x in enum["items"]]}


def do_dont(sentence: str) -> Optional[Dict[str, Any]]:
    s = _clean(strip_markers(sentence))
    m = re.match(r"(?P<head>.+?),\s+(?:not|rather than)\s+(?P<dont>.+)$", s, re.I)
    if not m:
        return None
    head = m.group("head")
    do = head
    verb = ""
    am = re.search(r"\s+as\s+", head)
    if am:
        verb, do = head[: am.end()].strip(), head[am.end():]
    return {"kind": "do_dont", "lead": verb, "do": _clean(do), "dont": _clean(m.group("dont"))}


def devices(sentence: str) -> Optional[Dict[str, Any]]:
    s = _clean(strip_markers(sentence))
    laser = re.search(r"\blasers?\b", s, re.I)
    led = re.search(r"\bLEDs?(?:\s+devices)?\b", s)
    if not (laser and led) or re.search(r"\d", s):
        return None
    tail_start = max(laser.end(), led.end())
    predicate = _clean(re.sub(r"^\s*(?:also\s+)?", "", s[tail_start:]))
    if not predicate or len(predicate.split()) > 6:
        return None
    return {"kind": "devices", "items": [{"label": laser.group(0), "icon": "zap"},
                                         {"label": led.group(0), "icon": "lightbulb"}],
            "caption": predicate}


_NM = re.compile(r"(?P<nums>\d+(?:\s+(?:plus|and|to)\s+\d+)*)\s*(?:nm|nanometres?|nanometers?)\b"
                 r"(?P<ctx>[^,.;]*?)(?=\s+and\s+\d|[,.;]|$)", re.I)


def wavelengths(sentence: str) -> Optional[Dict[str, Any]]:
    s = _clean(strip_markers(sentence))
    marks = []
    for m in _NM.finditer(s):
        values = [int(x) for x in re.findall(r"\d+", m.group("nums"))]
        ctx = _clean(m.group("ctx"))
        marks.append({"values": values, "context": ctx, "source": m.group(0).strip()})
    if not marks:
        return None
    return {"kind": "wavelengths", "marks": marks}


def light_band(sentence: str) -> Optional[Dict[str, Any]]:
    s = strip_markers(sentence)
    m = re.search(r"\b(red)\s+(?:or|and)\s+(near-infrared)\b", s, re.I)
    if not m:
        return None
    return {"kind": "light_band", "labels": [m.group(1), m.group(2)]}


_TIME = re.compile(r"\bat\s+(?P<at>" + _NUM_WORD + r"(?:\s+and\s+" + _NUM_WORD + r")?\s+(?:hours?|minutes?|days?|weeks?))\b",
                   re.I)


def time_points(sentence: str) -> Optional[Dict[str, Any]]:
    s = _clean(strip_markers(sentence))
    halves = re.split(r",\s+(?:but|while|whereas)\s+", s, maxsplit=1)
    if len(halves) != 2:
        return None
    points = []
    for half in halves:
        m = _TIME.search(half)
        if not m:
            return None
        text = _clean(half[: m.start()])
        text = re.sub(r"^(?:In|Among|For)\s+[^,]+,\s+", "", text)   # drop the population intro
        points.append({"at": m.group("at"), "text": text})
    return {"kind": "time_points", "points": points}


def contrast(sentence: str) -> Optional[Dict[str, Any]]:
    s = _clean(strip_markers(sentence))
    m = re.search(r",\s+(but|though|although|whereas)\s+", s)
    if not m:
        return None
    return {"kind": "contrast", "main": _clean(s[: m.start()]), "turn": m.group(1),
            "caution": _clean(s[m.end():])}


def consequence(sentence: str) -> Optional[Dict[str, Any]]:
    s = _clean(strip_markers(sentence))
    m = re.match(r"(That means|This means|So|Therefore|As a result)\s*,?\s+(.+)$", s)
    if not m:
        return None
    return {"kind": "consequence", "link": m.group(1), "text": _clean(m.group(2))}


def opens_with_but(sentence: str) -> bool:
    return bool(re.match(r"\s*(?:But|However|Yet)\b", strip_markers(sentence)))


DETECTORS = (scale, do_dont, time_points, devices, wavelengths, enumeration, light_band, contrast)


def detect(sentence: str) -> Optional[Dict[str, Any]]:
    """The most specific picture for this sentence, or None."""
    for fn in DETECTORS:
        spec = fn(sentence)
        if spec:
            return spec
    return None


def labels_of(spec: Dict[str, Any]) -> List[str]:
    """Every string a spec would put on screen (for the verbatim check)."""
    out: List[str] = []
    for key in ("lead", "caption", "main", "caution", "text", "do", "dont"):
        if spec.get(key):
            out.append(spec[key])
    for key in ("items", "steps", "points", "labels"):
        for x in spec.get(key) or []:
            if isinstance(x, dict):
                out += [x[k] for k in ("label", "text") if x.get(k)]
            else:
                out.append(x)
    for mark in spec.get("marks") or []:
        if mark.get("context"):
            out.append(mark["context"])
    return out


def numbers_of(spec: Dict[str, Any]) -> List[str]:
    nums: List[str] = []
    for mark in spec.get("marks") or []:
        nums += [str(v) for v in mark.get("values", [])]
    for p in spec.get("points") or []:
        nums += re.findall(r"\d+", p.get("at", ""))
    return nums
