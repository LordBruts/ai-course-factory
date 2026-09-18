"""Build a storyboard from an approved course package.

    python video-production/storyboard/build.py \
        --package samples/source/package.json \
        --durations samples/source/durations.json \
        --transcripts samples/source/transcripts \
        --out samples/faceless/storyboard.json

Deterministic: the same package, durations and transcripts always produce the same
storyboard, which is what makes the cache safe and the output reviewable. The LLM
refinement pass is a separate, optional step (llm_pass.py) and is re-validated
afterwards by rules.validate_storyboard.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from beats import build_beats, sections_from_beats  # noqa: E402
from deck import to_slides, video_deck, video_script  # noqa: E402
from rules import build_storyboard, validate_storyboard  # noqa: E402
from boards import pace_gaps, plan_boards, validate_boards  # noqa: E402


def content_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def load_transcripts(directory: str | None, count: int):
    """Word-level transcripts, one JSON per audio index, as video-use writes them."""
    if not directory or not os.path.isdir(directory):
        return None
    out = {}
    for i in range(count):
        for name in ("audio_%02d.json" % i, "narration_%02d.json" % i):
            path = os.path.join(directory, name)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                words = data.get("words") if isinstance(data, dict) else data
                if words:
                    out[i] = words
                break
    return out or None


def _timing_source(beats, durations) -> str:
    placed = sum(1 for b in beats if b.timing == "transcript")
    if placed == len(beats):
        return "transcript"
    if placed:
        return "transcript_partial"
    return "audio_durations" if durations else "estimate"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True)
    ap.add_argument("--durations", help="JSON: {audio_index: seconds}")
    ap.add_argument("--transcripts", help="directory of word-level transcripts")
    ap.add_argument("--words", help="presenter slides.json (presenter/takes.py): one edited recording, "
                                    "word timings per slide; replaces --durations and --transcripts")
    ap.add_argument("--template", default="faceless", choices=["faceless", "face"])
    ap.add_argument("--layout", default="boards", choices=["boards", "beats"],
                    help="boards: pages that build up (default); beats: one visual per sentence")
    ap.add_argument("--config", default=os.path.join(_HERE, "..", "config", "video.config.json"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.package, encoding="utf-8") as fh:
        pkg = json.load(fh)
    config = {}
    if args.config and os.path.exists(args.config):
        with open(args.config, encoding="utf-8") as fh:
            config = json.load(fh)

    kept, dropped = video_deck(pkg)
    slides = to_slides(kept)

    raw_durations = {}
    if args.durations and os.path.exists(args.durations):
        with open(args.durations, encoding="utf-8") as fh:
            raw_durations = {int(k): float(v) for k, v in json.load(fh).items()}
    # Durations are keyed by the ORIGINAL audio index; beats work in deck position.
    durations = {i: raw_durations[s["audio_index"]]
                 for i, s in enumerate(slides) if s.get("audio_index") in raw_durations}

    transcripts_by_audio = None if args.words else load_transcripts(args.transcripts, count=32)
    transcripts = None
    if args.words:
        # The face template: timing comes from the presenter's kept takes, slide by slide.
        with open(args.words, encoding="utf-8") as fh:
            per_slide = {e["deck_position"]: e for e in json.load(fh)["slides"]}
        durations = {i: per_slide[i]["seconds"] for i in range(len(slides)) if i in per_slide}
        transcripts = {i: per_slide[i]["words"] for i in range(len(slides)) if i in per_slide}
    if transcripts_by_audio:
        transcripts = {i: transcripts_by_audio[s["audio_index"]]
                       for i, s in enumerate(slides)
                       if s.get("audio_index") in transcripts_by_audio}

    beats = build_beats(slides, transcripts=transcripts, durations=durations)
    if not beats:
        print("no narration in the approved package: nothing to storyboard", file=sys.stderr)
        return 2
    sections = sections_from_beats(beats, slides)
    storyboard = build_storyboard(beats, pkg.get("references") or [], sections,
                                  template=args.template, config=config)

    storyboard.update({
        "version_id": pkg.get("version_id"),
        "course_slug": pkg.get("course_slug"),
        "content_hash": content_hash(video_script(kept), args.template,
                                     str(config.get("storyboard", {}).get("rules_version", 1))),
        "narration_plan": [{"deck_position": i, "audio_index": s.get("audio_index"),
                            "kind": s.get("kind"), "title": s.get("title"),
                            "seconds": durations.get(i)}
                           for i, s in enumerate(slides)],
        "dropped_narration": dropped,
        # Report what actually placed the beats, not what was supplied: a transcript
        # that failed to align must not be advertised as transcript timing.
        "timing_source": ("presenter_" if args.words else "") + _timing_source(beats, durations),
        "timing_coverage": round(sum(1 for b in beats if b.timing == "transcript") / len(beats), 3),
    })

    approved_bullets = [b for sl in (pkg.get("slides") or []) for b in (sl.get("bullets") or [])]
    problems = validate_storyboard(storyboard, pkg.get("references") or [],
                                   approved_bullets=approved_bullets)

    if args.layout == "boards":
        # Pages that build up, with a study gallery and infographics (storyboard/boards.py).
        storyboard["boards"] = plan_boards(storyboard, slides, pkg.get("references") or [],
                                           course_title=pkg.get("title") or "")
        approved = " ".join([video_script(kept), pkg.get("title") or ""] + [s["title"] for s in slides])
        problems += validate_boards(storyboard["boards"], approved, approved_bullets, pkg.get("references") or [])
        gaps = pace_gaps(storyboard["boards"], float(config.get("storyboard", {}).get("max_scene_seconds", 14)))
        problems += ["nothing changes on screen for %.1fs from %.1fs" % (g["seconds"], g["from"]) for g in gaps]
    if problems:
        print("storyboard failed validation:", file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(storyboard, fh, indent=2)

    visuals = [s for s in storyboard["segments"] if s["visual_type"] != "NONE"]
    by_type: dict = {}
    for s in visuals:
        by_type[s["visual_type"]] = by_type.get(s["visual_type"], 0) + 1
    print("wrote %s" % args.out)
    print("  %.1fs · %d beats · %d visual · %d quiet · timing from %s (%.0f%% of beats)"
          % (storyboard["total_seconds"], len(storyboard["segments"]), len(visuals),
             len(storyboard["segments"]) - len(visuals), storyboard["timing_source"],
             100 * storyboard["timing_coverage"]))
    for k, v in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print("    %-20s %d" % (k, v))
    if dropped:
        print("  dropped narration: %s" % ", ".join(d["title"] for d in dropped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
