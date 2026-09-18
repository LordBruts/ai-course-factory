"""Storyboard + presenter edit -> a HyperFrames project for the face template.

Layers, bottom to top:

    #base         brand page colour (visible around the presenter in split and pip)
    #pv-wrap      the presenter window: position, size and corner radius per mode
      #pv-punch     punch-in at jump cuts (scale about the face)
        #pv         the muted presenter video, scaled and offset inside the window
    boards        the Phase 3 pages, confined to the mode's panel (templates/motion/board.py)
    <audio>       the presenter's own edited audio

The presenter moves between arrangements once per change of mode, in the pause
the edit leaves between sections (presenter/takes.py), while the outgoing page
fades. Every move is a tween on the one paused timeline, so any frame can be
rendered on its own.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from typing import Any, Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_TEMPLATES = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_TEMPLATES, "motion"))
sys.path.insert(0, _HERE)

import importlib.util  # noqa: E402

from board import LayoutError, check_layout, render_boards  # noqa: E402
from components import Tokens, esc  # noqa: E402
from infographic_boxes import base_css, from_to  # noqa: E402
import layouts as lay  # noqa: E402

_spec = importlib.util.spec_from_file_location("faceless_composition",
                                               os.path.join(_TEMPLATES, "faceless", "composition.py"))
faceless = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(faceless)
CompositionError = faceless.CompositionError


CLIP = "inset(var(--ct) var(--cr) var(--cb) var(--cl) round var(--cq))"


def _inset(w, radius: float, grow: float = 0.0) -> Dict[str, str]:
    """The window as clip-path variables.

    Clipping is paint-only and moves at sub-pixel precision (left/top/width/height snap to
    whole pixels and stutter under frame-by-frame capture). The inset lives in custom
    properties because Chrome normalises an inset() string ("0px 0px 0px 0px" becomes
    "0px"), after which GSAP cannot pair the numbers and the window jumps instead of moving.
    """
    return {"--ct": "%.1fpx" % (w.y - grow), "--cr": "%.1fpx" % (lay.W - (w.x + w.w) - grow),
            "--cb": "%.1fpx" % (lay.H - (w.y + w.h) - grow), "--cl": "%.1fpx" % (w.x - grow),
            "--cq": "%.1fpx" % ((radius + grow) if radius else 0.0)}


def _vars_css(v: Dict[str, str]) -> str:
    return " ".join("%s:%s;" % kv for kv in v.items())


def _placement_css(p: lay.Placement) -> Dict[str, Dict[str, Any]]:
    w = p.window
    # The video sits in canvas coordinates: window origin plus its offset inside the window.
    return {"wrap": _inset(w, p.radius),
            "edge": _inset(w, p.radius, grow=3 if p.radius else 0),
            "video": {"x": round(w.x + p.x, 1), "y": round(w.y + p.y, 1), "scale": round(p.scale, 4)}}


def _chrome(p: lay.Placement) -> int:
    """1 where the presenter sits in a rounded window, which is where the edge shows."""
    return 1 if p.radius else 0


def _origin_xy(p: lay.Placement):
    """Punch-ins scale about the middle of the window, in canvas pixels."""
    w = p.window
    return round(w.x + w.w / 2), round(w.y + w.h * 0.45)


def _origin(p: lay.Placement) -> str:
    return "%dpx %dpx" % _origin_xy(p)


def build_face_composition(storyboard: Dict[str, Any], out_dir: str, *, presenter_video: str,
                           edl: Dict[str, Any], framing: Dict[str, Any], total_seconds: float,
                           width: int = 1920, height: int = 1080, fps: int = 30,
                           font_dir: Optional[str] = None, course_title: str = "",
                           presenter_layer: bool = True) -> Dict[str, Any]:
    """`presenter_layer=False` builds the pages alone, over transparency.

    A <video> in the composition forces HyperFrames to screenshot every frame with the
    presenter decoded inside Chrome: ~1.2 s per frame here against 0.15 s for the pages
    alone, and memory that grows until the render stalls. The pages then render to an
    alpha format and rendering/composite.py lays them over a presenter track built from
    this manifest's own geometry, which is why the schedules below are recorded in it.
    """
    tokens = Tokens()
    boards = storyboard.get("boards") or []
    if not boards:
        raise CompositionError("the face template needs boards (storyboard --layout boards)")
    if not os.path.exists(presenter_video):
        raise CompositionError("presenter video missing: %s" % presenter_video)
    os.makedirs(os.path.join(out_dir, "assets"), exist_ok=True)
    total = float(total_seconds)

    caption = tokens.space["captionZone"]
    modes = lay.build_modes(framing, caption_top=height - (caption["bottom"] + caption["height"]))
    names = lay.mode_sequence(boards, modes, tokens)
    try:
        # A page whose successor moves the presenter leaves early, clearing the path.
        board_modes = []
        for i, n in enumerate(names):
            m = modes[n].board_mode()
            if i + 1 < len(names) and names[i + 1] != n:
                m["out_lead"] = lay.PAGE_OUT
            board_modes.append(m)
        clips, layout = render_boards(tokens, boards, modes=board_modes)
    except LayoutError as exc:
        raise CompositionError(str(exc)) from exc
    problems = check_layout(layout, tokens)
    if problems:
        raise CompositionError("board layout: " + "; ".join(problems))

    # ---- presenter timeline --------------------------------------------------
    tl: List[str] = []
    pv: List[str] = []          # presenter-layer tweens; a pages build drops them
    # (time, tie-break, scale) for the punch-in step function, so a pages build can hand
    # composite.py the same framing the browser would have produced.
    steps: List[tuple] = []
    first = _placement_css(modes[names[0]].placement)
    moves = lay.transitions(boards, names, modes)
    for mv in moves:
        a, b = modes[mv["from"]].placement, modes[mv["to"]].placement
        pa, pb = _placement_css(a), _placement_css(b)
        ease = tokens.ease("standard")
        pv.append(from_to("#pv-wrap", pa["wrap"], {**pb["wrap"], "duration": mv["duration"], "ease": ease,
                                                   "immediateRender": False}, mv["at"]))
        pv.append(from_to("#pv-edge", pa["edge"], {**pb["edge"], "duration": mv["duration"], "ease": ease,
                                                   "immediateRender": False}, mv["at"]))
        pv.append(from_to("#pv", pa["video"], {**pb["video"], "duration": mv["duration"], "ease": ease,
                                               "immediateRender": False}, mv["at"]))
        # Window chrome: a rounded window carries the white edge, a full-frame presenter
        # has none. Keyed on the corner radius, so the shortened window a docking study
        # leaves (split_docked) keeps its edge instead of losing it mid-page.
        chrome = _chrome(modes[mv["to"]].placement)
        pv.append(from_to("#pv-edge", {"opacity": 1 - chrome}, {"opacity": chrome, "duration": mv["duration"],
                                                                "immediateRender": False}, mv["at"]))

    # Punch-ins: alternate framing at each visible jump cut, never during a move.
    punches = []
    zoomed = False
    board_at = [(b["start"], b["end"], names[i]) for i, b in enumerate(boards)]
    last_t = -1.0
    for r in edl.get("ranges", []):
        t0 = float(r["out_start"])
        if any(last_t < mv["at"] <= t0 for mv in moves):
            zoomed = False        # the move below resets the framing
        last_t = t0
        mode_now = next((n for s, e, n in board_at if s <= t0 < e), names[-1])
        mode_now = next((mv["to"] for mv in reversed(moves) if mv["at"] <= t0), mode_now)
        near_move = any(mv["at"] - 0.1 <= t0 <= mv["at"] + mv["duration"] + 0.1 for mv in moves)
        if not r.get("jump_cut_before"):
            if zoomed:
                pv.append(from_to("#pv-punch", {"scale": 1.06}, {"scale": 1, "duration": 0.001,
                                                                 "immediateRender": False}, t0))
                steps.append((t0, 0, 1.0))
                zoomed = False
            continue
        if near_move or not modes[mode_now].punch:
            continue
        zoomed = not zoomed
        s0, s1 = (1, 1.06) if zoomed else (1.06, 1)
        pv.append(from_to("#pv-punch", {"scale": s0}, {"scale": s1, "duration": 0.001, "immediateRender": False}, t0))
        steps.append((t0, 0, float(s1)))
        punches.append(round(t0, 3))
    for mv in moves:      # a move always starts from the unzoomed framing
        pv.append(from_to("#pv-punch", {"scale": 1}, {"scale": 1, "duration": 0.001, "immediateRender": False}, mv["at"]))
        # Tweens added later win at the same instant, which is why the reset sorts after
        # any cut landing on the move's own start.
        steps.append((mv["at"], 1, 1.0))
        pv.append(from_to("#pv-punch", {"transformOrigin": _origin(modes[mv["from"]].placement)},
                          {"transformOrigin": _origin(modes[mv["to"]].placement),
                           "duration": 0.001, "immediateRender": False}, mv["at"] + mv["duration"]))
    punch_steps = [{"at": round(t, 3), "scale": s} for t, _, s in sorted(steps)]

    hold = lay.ending_hold(boards, total)
    if hold:
        last = boards[-1]["board_id"].lower()
        tl.append(from_to("#bd-" + last, {"opacity": 1}, {"opacity": 0, "duration": hold["duration"],
                                                          "immediateRender": False}, hold["at"]))

    # ---- assets ----------------------------------------------------------------
    if presenter_layer:
        shutil.copy2(presenter_video, os.path.join(out_dir, "assets", "presenter.mp4"))
    faceless._copy_fonts(font_dir, out_dir)
    shutil.copy2(faceless.GSAP_LOCAL, os.path.join(out_dir, "assets", "gsap.min.js"))

    css = base_css(tokens) + "\n".join(c.css for c in clips)
    body = "\n".join(c.html for c in clips)
    timeline = "\n      ".join([line for c in clips for line in c.timeline] + tl + (pv if presenter_layer else []))
    w0, v0 = first["wrap"], first["video"]
    p0 = modes[names[0]].placement
    edge0 = _chrome(modes[names[0]].placement)

    if presenter_layer:
        # The presenter layer covers the canvas; clip-path cuts the window out of it.
        presenter_css = f"""      #base {{ position:absolute; inset:0; background:{tokens.page}; z-index:0; }}
      #pv-edge {{ position:absolute; inset:0; z-index:4; background:rgba(255,255,255,.92);
        {_vars_css(first['edge'])} clip-path:{CLIP}; opacity:{edge0}; }}
      #pv-wrap {{ position:absolute; inset:0; overflow:hidden; z-index:5; background:{tokens.navy};
        {_vars_css(w0)} clip-path:{CLIP}; }}
      #pv-punch {{ position:absolute; inset:0; transform-origin:{_origin(p0)}; }}
      #pv {{ position:absolute; left:0; top:0; width:{width}px; height:{height}px; transform-origin:0 0; }}"""
        presenter_html = f"""      <div id="base"></div>
      <div id="pv-edge"></div>
      <div id="pv-wrap">
        <div id="pv-punch">
          <video id="pv" src="assets/presenter.mp4" muted playsinline
                 data-start="0" data-duration="{total:.3f}" data-media-start="0" data-track-index="2"></video>
        </div>
      </div>"""
        presenter_set = (f'gsap.set("#pv", {{ x: {v0["x"]}, y: {v0["y"]}, scale: {v0["scale"]}, '
                         'transformOrigin: "0 0" }});')
        audio_html = (f'    <audio id="pa" src="assets/presenter.mp4" data-start="0" data-duration="{total:.3f}"\n'
                      '             data-media-start="0" data-track-index="10" data-volume="1"></audio>')
        page_bg = tokens.page
    else:
        # Pages alone: no page colour, no window chrome, nothing where the presenter goes.
        # composite.py paints the page colour and the window edge under this layer, so
        # everything here composites over the presenter through its own alpha.
        presenter_css = "      #base { position:absolute; inset:0; background:transparent; z-index:0; }"
        presenter_html = '      <div id="base"></div>'
        presenter_set = ""
        audio_html = ""
        page_bg = "transparent"

    html_doc = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={width}, height={height}" />
    <title>{esc(course_title or 'GymRamp course')}</title>
    <script src="assets/gsap.min.js"></script>
    <style>
      {faceless._fonts_css(tokens, font_dir)}
      body {{ margin:0; background:{page_bg}; }}
      #root {{ position:relative; width:{width}px; height:{height}px; overflow:hidden;
        font-family:{tokens.font('body')}; -webkit-font-smoothing:antialiased; }}
      .clip {{ position:absolute; inset:0; }}
{presenter_css}
{css}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="course" data-start="0" data-duration="{total:.3f}"
         data-width="{width}" data-height="{height}" data-fps="{fps}">
{presenter_html}
{body}
{audio_html}
    </div>
    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
      {presenter_set}
      {timeline}
      window.__timelines.course = tl;
    </script>
  </body>
</html>
"""
    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(html_doc)

    manifest = {
        "index": index_path, "template": "face", "width": width, "height": height, "fps": fps,
        "duration": round(total, 3),
        "clips": [{"segment_id": e.get("segment_id"), "component": e["kind"], "clip_id": e["element_id"],
                   "start": e["enter_at"], "duration": round(b["end"] - e["enter_at"], 3),
                   "board_id": b["board_id"], "dock_at": e.get("dock_at")}
                  for b in boards for e in b["elements"]],
        "boards": layout,
        "layout_modes": [{"board_id": b["board_id"], "mode": n, "start": b["start"], "end": b["end"],
                          "presenter": modes[n].placement.as_dict()} for b, n in zip(boards, names)],
        "transitions": moves, "punch_ins": punches, "ending_hold": hold,
        "presenter_states": {k: modes[k].placement.as_dict() for k in sorted({m["to"] for m in moves} | set(names))},
        "audio": [{"file": "presenter.mp4", "start": 0.0, "seconds": round(total, 3)}],
        "quiet_segments": [],
        # What composite.py needs to rebuild the presenter under a pages-only render.
        "presenter_layer": presenter_layer,
        "punch_steps": punch_steps,
        "punch_origins": {k: list(_origin_xy(modes[k].placement)) for k in modes},
        "mode_chrome": {k: _chrome(m.placement) for k, m in modes.items()},
        "first_mode": names[0],
        "ease": tokens.ease("standard"),
        "page_color": tokens.page,
        "edge": {"color": [255, 255, 255], "alpha": 0.92, "width": 3},
    }
    with open(os.path.join(out_dir, "composition.manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest
