"""Storyboard -> a HyperFrames project for the faceless template.

Output is a directory containing `index.html` and `assets/`, which is exactly what
`hyperframes lint` and `hyperframes render` expect (docs/reference/html-schema.mdx).

Two decisions worth knowing about:

**Quiet beats hold the previous visual.** A beat the storyboard left visually quiet
does not mean an empty frame — it means no NEW visual. The current scene stays up
and the narration carries the moment. That is the difference between restraint and
a black hole in the middle of a course, and it is why the QA black-frame check can
be strict.

**Captions are not in this file.** HyperFrames composes the picture; subtitles are
burned afterwards by the editing layer, because video-use's rule is that subtitles
go on last, after every overlay. Anything drawn here stays clear of the reserved
caption zone in brand/spacing.json.
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, List, Optional, Sequence

import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "motion"))

from components import REGISTRY, Clip, Tokens, esc  # noqa: E402

# GSAP ships inside the project rather than loading from a CDN: the render must not
# depend on the network (a slow CDN pushed page load past HyperFrames' 10 s navigation
# limit), and a pinned local file is part of what makes a render reproducible.
# Copied from HyperFrames' own talking-head-recut skill, GSAP 3.15.0, licence header kept.
GSAP_LOCAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "motion", "vendor", "gsap.min.js")


class CompositionError(ValueError):
    pass


def _fonts_css(tokens: Tokens, font_dir: Optional[str]) -> str:
    """Embed Montserrat by @font-face when the files are available.

    Chrome in a container has no Montserrat unless it is installed or declared.
    Falling back to a system sans would silently change every frame, so the font
    is declared explicitly and QA compares against a reference frame.
    """
    if not font_dir or not os.path.isdir(font_dir):
        return ""
    faces = []
    for weight, filename in ((400, "Montserrat-Regular.ttf"), (500, "Montserrat-Medium.ttf"),
                             (600, "Montserrat-SemiBold.ttf"), (700, "Montserrat-Bold.ttf")):
        path = os.path.join(font_dir, filename)
        if os.path.exists(path):
            faces.append("@font-face{font-family:'Montserrat';font-style:normal;font-weight:%d;"
                         "src:url('assets/fonts/%s') format('truetype');font-display:block;}"
                         % (weight, filename))
    return "\n".join(faces)


def _copy_fonts(font_dir: Optional[str], out_dir: str) -> None:
    if not font_dir or not os.path.isdir(font_dir):
        return
    dest = os.path.join(out_dir, "assets", "fonts")
    os.makedirs(dest, exist_ok=True)
    for filename in ("Montserrat-Regular.ttf", "Montserrat-Medium.ttf",
                     "Montserrat-SemiBold.ttf", "Montserrat-Bold.ttf"):
        src = os.path.join(font_dir, filename)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dest, filename))


def _visual_segments(storyboard: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [s for s in storyboard.get("segments", []) if s.get("visual_type") not in (None, "NONE")]


def _hold_until_next(visuals: List[Dict[str, Any]], total: float) -> List[Dict[str, Any]]:
    """Extend each visual to the start of the next one, so no frame is ever empty."""
    out = []
    for i, seg in enumerate(visuals):
        start = float(seg["start"])
        end = float(visuals[i + 1]["start"]) if i + 1 < len(visuals) else total
        if end <= start:
            end = start + max(0.5, float(seg["end"]) - start)
        out.append({**seg, "_clip_start": round(start, 3), "_clip_duration": round(end - start, 3)})
    return out


def _props_for(seg: Dict[str, Any]) -> Dict[str, Any]:
    """Map storyboard props onto component keyword arguments.

    Storyboard props are written for humans reading a storyboard; components take
    explicit arguments. Doing the mapping here means an unexpected key fails at
    build time with a clear message instead of rendering a blank card.
    """
    component = seg.get("component")
    p = dict(seg.get("props") or {})

    if component == "TitleReveal":
        return {"title": p.get("title") or "", "subtitle": p.get("subtitle") or ""}
    if component == "SectionIntro":
        return {"title": p.get("title") or "", "eyebrow": p.get("eyebrow") or ""}
    if component == "KeywordHighlight":
        return {"term": p.get("term") or "", "definition": p.get("definition") or ""}
    if component == "EvidenceCard":
        return {"finding": p.get("finding") or "", "citation": p.get("citation") or "",
                "design": p.get("design") or "", "year": p.get("year"),
                "journal": p.get("journal") or "", "population": p.get("population") or "",
                "outcome": p.get("outcome") or "", "statistic": p.get("statistic"),
                "marker": p.get("marker")}
    if component == "StatisticCard":
        return {"value": p.get("value") or "", "label": p.get("label") or "", "context": p.get("context") or ""}
    if component == "ComparisonCard":
        return {"left": p.get("left") or "", "right": p.get("right") or "",
                "left_label": p.get("left_label") or "", "right_label": p.get("right_label") or ""}
    if component == "ProcessFlow":
        return {"steps": list(p.get("steps") or []), "title": p.get("title") or ""}
    if component == "Recap":
        return {"items": list(p.get("items") or []), "title": p.get("title") or "Key takeaways"}
    if component == "Outro":
        return {"title": p.get("title") or "", "message": p.get("message") or "",
                "course_code": p.get("course_code") or ""}
    if component == "QuoteCard":
        return {"quote": p.get("quote") or "", "attribution": p.get("attribution") or ""}
    if component == "ChartCard":
        return {"bars": [tuple(b) for b in (p.get("bars") or [])], "title": p.get("title") or "",
                "unit": p.get("unit") or ""}
    if component == "Timeline":
        return {"points": [tuple(x) for x in (p.get("points") or [])], "title": p.get("title") or ""}
    if component == "IconSequence":
        return {"items": list(p.get("items") or []), "title": p.get("title") or ""}
    if component == "LowerThird":
        return {"primary": p.get("primary") or "", "secondary": p.get("secondary") or ""}
    if component == "SourceCitation":
        return {"citation": p.get("citation") or "", "marker": p.get("marker")}
    if component == "KeyTakeaway":
        return {"text": p.get("text") or "", "variant": p.get("variant") or "statement"}
    raise CompositionError("no prop mapping for component %r" % component)


def build_composition(storyboard: Dict[str, Any],
                      out_dir: str,
                      *,
                      narration: Optional[Sequence[Dict[str, Any]]] = None,
                      total_seconds: Optional[float] = None,
                      width: int = 1920,
                      height: int = 1080,
                      fps: int = 30,
                      font_dir: Optional[str] = None,
                      course_title: str = "",
                      brand_dir: Optional[str] = None) -> Dict[str, Any]:
    """Write a renderable HyperFrames project. Returns a manifest of what was built."""
    tokens = Tokens(brand_dir) if brand_dir else Tokens()
    os.makedirs(os.path.join(out_dir, "assets"), exist_ok=True)

    boards = storyboard.get("boards") or []
    visuals = _visual_segments(storyboard)
    if not visuals and not boards:
        raise CompositionError("storyboard has no visual segments; a course video cannot be entirely quiet")

    total = float(total_seconds or storyboard.get("total_seconds") or 0)
    if total <= 0:
        total = max(float(s["end"]) for s in storyboard["segments"])

    # ---- audio: one element per narration file, placed at its own offset --------
    audio_html: List[str] = []
    audio_manifest: List[Dict[str, Any]] = []
    for item in (narration or []):
        src = item.get("path")
        if not src or not os.path.exists(src):
            raise CompositionError("narration file missing: %r" % src)
        name = "narration_%02d%s" % (int(item.get("index", len(audio_manifest))), os.path.splitext(src)[1])
        shutil.copy2(src, os.path.join(out_dir, "assets", name))
        start = float(item.get("start", 0.0))
        seconds = item.get("seconds")
        if not seconds:
            # Without a duration HyperFrames treats the clip as running to the end of the
            # timeline, and every later narration file then layers on top of it.
            raise CompositionError("narration %s has no duration" % name)
        audio_html.append(
            '  <audio id="aud-%02d" src="assets/%s" data-start="%.3f" data-duration="%.3f" '
            'data-media-start="0" data-track-index="%d" data-volume="1"></audio>'
            # Back-to-back clips share an edge; float addition can put one clip's end a
            # hair past the next start, which HyperFrames reads as layered audio. Two
            # alternating tracks make adjacency unambiguous without trimming any audio.
            % (int(item.get("index", 0)), name, start, float(seconds), 9 + len(audio_html) % 2))
        audio_manifest.append({"index": int(item.get("index", 0)), "file": name,
                               "start": round(start, 3), "seconds": item.get("seconds")})

    # ---- clips ------------------------------------------------------------------
    clips: List[Clip] = []
    used: List[Dict[str, Any]] = []
    layout: List[Dict[str, Any]] = []
    extra_css = ""
    if boards:
        # Boards: pages that build up (templates/motion/board.py). The per-beat clip path
        # below stays for the presenter template's overlays.
        from board import LayoutError, check_layout, render_boards  # noqa: E402
        from infographic_boxes import base_css  # noqa: E402
        try:
            clips, layout = render_boards(tokens, boards)
        except LayoutError as exc:
            raise CompositionError(str(exc)) from exc
        problems = check_layout(layout, tokens)
        if problems:
            raise CompositionError("board layout: " + "; ".join(problems))
        extra_css = base_css(tokens)
        for b in boards:
            for e in b["elements"]:
                used.append({"segment_id": e.get("segment_id"), "component": e["kind"],
                             "clip_id": e["element_id"], "start": e["enter_at"],
                             "duration": round(b["end"] - e["enter_at"], 3), "board_id": b["board_id"],
                             "dock_at": e.get("dock_at")})
    takeaways = 0
    for i, seg in enumerate([] if boards else _hold_until_next(visuals, total)):
        if seg.get("component") == "KeyTakeaway" and not (seg.get("props") or {}).get("variant"):
            # Same words, alternating layout: consecutive cards must not look like a loop.
            seg = {**seg, "props": {**(seg.get("props") or {}),
                                    "variant": ("statement", "panel")[takeaways % 2]}}
            takeaways += 1
        component = seg.get("component")
        builder = REGISTRY.get(component or "")
        if not builder:
            raise CompositionError("segment %s names unknown component %r" % (seg.get("segment_id"), component))
        clip_id = "sc-%s" % str(seg.get("segment_id") or i).lower()
        clip = builder(tokens, clip_id, seg["_clip_start"], seg["_clip_duration"],
                       z=10 + i, **_props_for(seg))
        clips.append(clip)
        used.append({"segment_id": seg.get("segment_id"), "component": component,
                     "clip_id": clip_id, "start": seg["_clip_start"], "duration": seg["_clip_duration"],
                     "visual_type": seg.get("visual_type"), "reason": seg.get("visual_reason")})

    css = extra_css + "\n".join(c.css for c in clips)
    body = "\n".join(c.html for c in clips)
    timeline = "\n      ".join(line for c in clips for line in c.timeline)
    caption_zone = tokens.space["captionZone"]

    html_doc = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={width}, height={height}" />
    <title>{esc(course_title or 'GymRamp course')}</title>
    <script src="assets/gsap.min.js"></script>
    <style>
      {_fonts_css(tokens, font_dir)}
      body {{ margin:0; background:{tokens.page}; }}
      #root {{ position:relative; width:{width}px; height:{height}px; overflow:hidden;
        font-family:{tokens.font('body')}; -webkit-font-smoothing:antialiased; }}
      .clip {{ position:absolute; inset:0; }}
      .clip.overlay {{ background:transparent; }}
      /* The base layer means a frame is never empty, even between visuals. It carries no
         text: a mark here sat under every opaque scene (invisible, and flagged by
         `hyperframes check` as occluded, low-contrast and touching the caption band). */
      #base {{ position:absolute; inset:0; background:{tokens.page}; z-index:0; }}
      /* Reserved for burned-in subtitles, applied after this render. Nothing is drawn here. */
      #caption-zone {{ position:absolute; left:0; right:0; bottom:0;
        height:{caption_zone['bottom'] + caption_zone['height']}px; pointer-events:none; z-index:1; }}
{css}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="course" data-start="0" data-duration="{total:.3f}"
         data-width="{width}" data-height="{height}" data-fps="{fps}">
      <div id="base"></div>
      <div id="caption-zone"></div>
{body}
{os.linesep.join(audio_html)}
    </div>
    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
      {timeline}
      window.__timelines.course = tl;
    </script>
  </body>
</html>
"""

    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(html_doc)
    _copy_fonts(font_dir, out_dir)
    if not os.path.exists(GSAP_LOCAL):
        raise CompositionError("vendored GSAP missing: %s" % GSAP_LOCAL)
    shutil.copy2(GSAP_LOCAL, os.path.join(out_dir, "assets", "gsap.min.js"))

    manifest = {
        "index": index_path,
        "template": "faceless",
        "width": width, "height": height, "fps": fps,
        "duration": round(total, 3),
        "clips": used,
        "boards": layout,
        "audio": audio_manifest,
        "quiet_segments": [s["segment_id"] for s in storyboard.get("segments", [])
                           if s.get("visual_type") in (None, "NONE")],
    }
    with open(os.path.join(out_dir, "composition.manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest
