"""The approved course package -> the video's narration deck.

The course worker already builds a deck for the PPTX, the slide images and the TTS
(`narration_plan` in worker/app.py): title, one entry per slide, takeaways, then one
or more **reference pages** whose narration is "References, continued."

A deck is not a video. Two deliberate differences, both recorded on every entry so
QA and the reviewer can see them rather than discover them:

1. **Reference pages are not read aloud beyond the first.** Three slides of
   bibliography narrated as "References, continued" is the padding this project
   exists to avoid. The first closing line stays (it tells the learner where the
   sources are); the repeats are dropped, and sources appear where they belong —
   on the evidence cards, beside the finding they support.
2. **Nothing is rewritten.** Every retained entry keeps its approved wording
   verbatim, and `audio_index` points at the narration file the course already
   rendered and a human already approved, so the video reuses that exact audio.

`dropped` is returned, not hidden, so the QA editorial check can compare the
rendered audio against the *video* script and still prove no approved sentence was
altered.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

REFS_PER_SLIDE = 4  # matches worker/app.py, so audio indexes line up exactly


def full_deck(pkg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Reproduce the course worker's deck, in the same order, with audio indexes."""
    deck: List[Dict[str, Any]] = [{
        "kind": "title",
        "title": pkg.get("title", ""),
        "subtitle": pkg.get("subtitle", ""),
        "bullets": [],
        "refs": [],
        "notes": pkg.get("intro_notes") or ("Welcome to %s. %s" % (pkg.get("title", ""), pkg.get("subtitle", ""))),
    }]
    for s in pkg.get("slides", []):
        deck.append({"kind": "content", "title": s.get("title", ""), "bullets": list(s.get("bullets") or []),
                     "notes": s.get("notes", ""), "refs": list(s.get("refs") or [])})
    if pkg.get("takeaways"):
        deck.append({"kind": "takeaways", "title": "Key Takeaways", "bullets": list(pkg["takeaways"]),
                     "refs": [],
                     "notes": pkg.get("takeaways_notes")
                              or ("Let's recap the key takeaways. " + " ".join(pkg["takeaways"]))})
    references = pkg.get("references") or []
    pages = [references[i:i + REFS_PER_SLIDE] for i in range(0, len(references), REFS_PER_SLIDE)]
    for p, chunk in enumerate(pages):
        deck.append({
            "kind": "references",
            "title": "References" if len(pages) == 1 else "References (%d of %d)" % (p + 1, len(pages)),
            "bullets": [], "refs": [r.get("n") for r in chunk],
            "notes": ("Every claim in this course is linked to the sources listed here. "
                      "Review them in the course materials before your certification exam.")
                     if p == 0 else "References, continued.",
        })
    for i, entry in enumerate(deck):
        entry["audio_index"] = i
    return deck


def video_deck(pkg: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (kept, dropped) entries for the video.

    Kept entries carry `audio_index`, so the renderer reuses the approved narration
    files rather than paying to synthesise the same words again.
    """
    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    seen_reference_page = False

    for entry in full_deck(pkg):
        if entry["kind"] == "references":
            if seen_reference_page:
                dropped.append({
                    "audio_index": entry["audio_index"],
                    "title": entry["title"],
                    "notes": entry["notes"],
                    "reason": "A second bibliography slide narrated as 'References, continued' adds no "
                              "teaching; sources appear on the evidence cards instead.",
                })
                continue
            seen_reference_page = True
            # The first one is kept, but it plays as the closing beat, not a wall of
            # citations: the learner is told where the sources are, and the outro shows it.
            entry = {**entry, "kind": "closing", "title": "Sources and next step"}
        kept.append(entry)

    return kept, dropped


def video_script(kept: List[Dict[str, Any]]) -> str:
    """The narration the video actually speaks, for the editorial QA comparison."""
    return " ".join((e.get("notes") or "").strip() for e in kept if (e.get("notes") or "").strip())


def to_slides(kept: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Shape deck entries the way beats.build_beats expects."""
    out = []
    for e in kept:
        kind = e["kind"]
        out.append({
            "title": e.get("title", ""),
            "bullets": list(e.get("bullets") or []),
            "notes": e.get("notes", ""),
            "refs": list(e.get("refs") or []),
            "kind": {"title": "title", "takeaways": "takeaways", "closing": "content",
                     "references": "references"}.get(kind, "content"),
            "audio_index": e.get("audio_index"),
            "deck_kind": kind,     # the board planner needs "closing" as itself
        })
    return out
