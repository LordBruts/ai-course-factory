"""Layout director for the face template: where the presenter is on every page.

Three arrangements, chosen per board, with the presenter moving between them:

    glass   presenter full-frame as filmed; the page sits on a translucent navy panel
            on the side away from the presenter (opening, key takeaways, ending)
    split   presenter in a tall rounded window on the right; the page builds on the left
    pip     presenter in a small window in a slim right column; the study gallery takes
            the rest of the frame
    full    presenter alone (the last beat, after the closing page has left)

The page geometry of glass mode follows the footage: the panel starts to the right
of the presenter's measured extent (presenter/ingest.py), so it never covers them.
The inner video transform keeps the presenter's measured centre in the middle of
the window, at no more than native resolution.

Everything here is arithmetic on rects; nothing renders.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "motion"))

from board import Rect  # noqa: E402

W, H = 1920, 1080
MODE_FOR_KIND = {"hero": "glass", "recap": "glass", "outro": "glass", "gallery": "pip"}
TRANSITION = 0.75          # seconds; the presenter moves in the pause between sections
TRANSITION_LEAD = 0.35     # how much of it happens before the board boundary
PAGE_OUT = 0.75            # the outgoing page starts leaving this long before the boundary,
                           # so it is gone before the presenter window moves across it


@dataclass
class Placement:
    """The presenter window and the video inside it."""
    window: Rect
    radius: float
    scale: float               # video pixels per source pixel
    x: float                   # video offset inside the window
    y: float
    punch_origin: str          # transform-origin for punch-ins at jump cuts

    def as_dict(self) -> Dict[str, Any]:
        return {"window": self.window.as_dict(), "radius": self.radius, "scale": round(self.scale, 4),
                "x": round(self.x, 1), "y": round(self.y, 1), "punch_origin": self.punch_origin}


@dataclass
class Mode:
    name: str
    placement: Placement
    surface: str                       # board surface: page | glass
    panel: Optional[Rect] = None       # page content area
    backdrop: Optional[Rect] = None    # glass panel
    forbidden: Sequence[Rect] = ()     # where page content must not go
    punch: bool = True                 # jump cuts get a punch-in in this mode
    dock_rects: Optional[Sequence[Rect]] = None   # where studies dock (split: under the window)
    docked: Optional[str] = None       # the arrangement once a study has docked

    def board_mode(self) -> Dict[str, Any]:
        return {"name": self.name, "panel": self.panel, "surface": self.surface,
                "backdrop": self.backdrop, "forbidden": list(self.forbidden),
                "dock_rects": list(self.dock_rects) if self.dock_rects else None}


def fit_video(win: Rect, cx: float, cy: float, zoom: float) -> Placement:
    """Scale and offset so the presenter's face sits mid-window, a little above centre."""
    cover = max(win.w / W, win.h / H)
    s = min(1.0, max(cover, cover * zoom))
    vw, vh = W * s, H * s
    x = win.w / 2 - cx * vw
    x = min(0.0, max(win.w - vw, x))
    y = 0.45 * win.h - cy * vh
    y = min(0.0, max(win.h - vh, y))
    return Placement(win, 0.0, s, x, y, "50% 38%")


def build_modes(framing: Dict[str, Any], caption_top: int = 804) -> Dict[str, Mode]:
    cx = float(framing.get("subject_center_x", 0.5))
    lo, hi = framing.get("subject_extent_x", [cx - 0.15, cx + 0.15])
    cy = float(framing.get("subject_center_y", 0.5))
    content_bottom = caption_top - 14

    full = Placement(Rect(0, 0, W, H), 0, 1.0, 0, 0, "%.0f%% 38%%" % (cx * 100))

    # glass: the panel starts clear of the presenter, but never narrower than 780 px.
    left = min(max(hi * W + 50, 900), W - 56 - 780 - 88)
    backdrop = Rect(left, 56, W - 56 - left, content_bottom + 10 - 56)
    glass_panel = Rect(left + 44, 88, backdrop.w - 88, content_bottom - 88)
    subject = Rect(max(0, lo * W - 20), 0, (hi - lo) * W + 40, H)
    glass = Mode("glass", full, "glass", glass_panel, backdrop, forbidden=[subject])

    split_win = Rect(1176, 80, 680, 920)
    sp = fit_video(split_win, cx, cy, zoom=1.10)
    sp.radius = 28
    # When a study docks on a split page the window shortens and the study card takes the
    # space below it, so the page itself keeps its full width.
    dock = Rect(1176, content_bottom - 150, 680, 150)
    short_win = Rect(1176, 80, 680, dock.y - 20 - 80)
    ss = fit_video(short_win, cx, cy, zoom=1.10)
    ss.radius = 28
    split = Mode("split", sp, "page", Rect(120, 80, 1000, content_bottom - 80), forbidden=[split_win],
                 dock_rects=[dock], docked="split_docked")
    split_docked = Mode("split_docked", ss, "page", split.panel, forbidden=[short_win])

    pip_win = Rect(1480, 250, 360, 500)
    pp = fit_video(pip_win, cx, cy, zoom=1.35)
    pp.radius = 24
    pip = Mode("pip", pp, "page", Rect(120, 80, 1320, content_bottom - 80), forbidden=[pip_win], punch=False)

    ending = Mode("full", full, "glass", None, None, punch=True)
    return {"glass": glass, "split": split, "split_docked": split_docked, "pip": pip, "full": ending}


FALLBACK = {"split": "pip"}      # a page too dense to sit beside the presenter gets the room of a PiP


def mode_sequence(boards: Sequence[Dict[str, Any]], modes: Optional[Dict[str, Mode]] = None,
                  tokens: Any = None) -> List[str]:
    """Preferred arrangement per board kind; with `modes`, a board that does not fit its
    preferred panel moves to the fallback. Deterministic: same boards, same answer."""
    names = [MODE_FOR_KIND.get(b["kind"], "split") for b in boards]
    if modes is None:
        return names
    from board import BoardRenderer, LayoutError, check_layout
    out = []
    for b, name in zip(boards, names):
        for candidate in (name, FALLBACK.get(name)):
            if candidate is None:
                break
            m = modes[candidate].board_mode()
            try:
                r = BoardRenderer(tokens, b, 10, False, False, panel=m["panel"], surface=m["surface"],
                                  backdrop=m["backdrop"], forbidden=m["forbidden"], dock_rects=m["dock_rects"])
                r.render()
            except LayoutError:
                continue
            entry = {"board_id": b["board_id"], "kind": b["kind"], "rects": r.rects,
                     "panel": m["panel"].as_dict() if m["panel"] else None,
                     "forbidden": [f.as_dict() for f in m["forbidden"]]}
            if not check_layout([entry], tokens):
                name = candidate
                break
        out.append(name)
    return out


def transitions(boards: Sequence[Dict[str, Any]], names: Sequence[str],
                modes: Optional[Dict[str, Mode]] = None) -> List[Dict[str, Any]]:
    """Presenter moves: one per change of arrangement at the pause between boards, and,
    with `modes`, one inside a board when a study docks beside the presenter."""
    out = []
    state = names[0] if names else None
    for i, b in enumerate(boards):
        if i and names[i] != state:
            out.append({"at": round(b["start"] - TRANSITION_LEAD, 3), "duration": TRANSITION,
                        "from": state, "to": names[i], "board_id": b["board_id"]})
        state = names[i]
        mode = modes.get(names[i]) if modes else None
        docks = [e["dock_at"] for e in b["elements"] if e["kind"] == "study" and e.get("dock_at") is not None]
        if mode is not None and mode.docked and docks:
            out.append({"at": round(docks[0] - 0.05, 3), "duration": 0.6, "from": state, "to": mode.docked,
                        "board_id": b["board_id"], "within_board": True})
            state = mode.docked
    return out


def ending_hold(boards: Sequence[Dict[str, Any]], total: float) -> Optional[Dict[str, Any]]:
    """The closing page leaves ~1.2 s before the end; the presenter holds the last beat alone."""
    if not boards or total - boards[-1]["start"] < 4.0:
        return None
    return {"at": round(total - 1.2, 3), "duration": 0.5}
