"""The presenter layer a pages-only render leaves out, rebuilt frame by frame.

`face_composition.build_face_composition(..., presenter_layer=False)` renders the pages
over transparency and records, in the manifest, every schedule the browser would have
animated: the mode placements, the moves between them, the punch-in steps at jump cuts
and the window chrome. This module replays those schedules in Python and paints what CSS
would have painted:

    page colour                      what #base was
    the presenter, scaled and offset what #pv was, inside #pv-punch
    clipped to the rounded window    what #pv-wrap's clip-path was
    a white edge around the window   what #pv-edge was

The pages layer then composites over this with its own alpha (rendering/composite.py), so
a glass panel still dims the presenter exactly as a translucent panel over a video would.

Geometry note: #pv carries `transform: translate(x,y) scale(s)` with origin 0 0, and
#pv-punch scales by `p` about a canvas-space origin O, so a source pixel lands at
`O + p * ((x, y) + s * pixel - O)` — an effective scale of `p * s` at an effective offset
of `O + p * ((x, y) - O)`.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

W, H = 1920, 1080
SS = 4          # mask supersampling, for anti-aliased window corners


def _bezier(css: str):
    """A CSS cubic-bezier as a function of linear progress, by bisection on x."""
    m = re.findall(r"-?\d*\.?\d+", css or "")
    if len(m) != 4:
        return lambda u: u
    x1, y1, x2, y2 = (float(v) for v in m)

    def curve(a, b, u):
        return 3 * a * (1 - u) ** 2 * u + 3 * b * (1 - u) * u ** 2 + u ** 3

    def ease(u: float) -> float:
        if u <= 0:
            return 0.0
        if u >= 1:
            return 1.0
        lo, hi = 0.0, 1.0
        for _ in range(24):
            mid = (lo + hi) / 2
            if curve(x1, x2, mid) < u:
                lo = mid
            else:
                hi = mid
        return curve(y1, y2, (lo + hi) / 2)

    return ease


def _hex_rgb(value: str) -> Tuple[int, int, int]:
    v = (value or "#000000").lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def _vector(state: Dict[str, Any], chrome: float) -> List[float]:
    """The animated properties, in the order CSS tweens them."""
    w = state["window"]
    return [w["y"], W - (w["x"] + w["w"]), H - (w["y"] + w["h"]), w["x"],   # clip insets
            state["radius"], w["x"] + state["x"], w["y"] + state["y"], state["scale"], chrome]


class PresenterTrack:
    """Per-frame presenter geometry, and the frames themselves."""

    def __init__(self, manifest: Dict[str, Any]):
        self.states = manifest["presenter_states"]
        self.moves = sorted(manifest.get("transitions", []), key=lambda m: m["at"])
        self.first = manifest.get("first_mode") or (manifest["layout_modes"][0]["mode"])
        self.chrome = manifest.get("mode_chrome", {})
        self.origins = {k: tuple(v) for k, v in manifest.get("punch_origins", {}).items()}
        self.steps = sorted(manifest.get("punch_steps", []), key=lambda s: s["at"])
        self.ease = _bezier(manifest.get("ease", ""))
        self.page = _hex_rgb(manifest.get("page_color", "#F2F4F7"))
        edge = manifest.get("edge") or {}
        self.edge_rgb = tuple(edge.get("color", [255, 255, 255]))
        self.edge_alpha = float(edge.get("alpha", 0.92))
        self.edge_width = int(edge.get("width", 3))
        self._masks: Dict[Tuple, Image.Image] = {}
        self._edges: Dict[Tuple, Image.Image] = {}

    # -- geometry -------------------------------------------------------------
    def _vec_at(self, t: float) -> Tuple[List[float], str]:
        mode = self.first
        for mv in self.moves:
            if t >= mv["at"] + mv["duration"]:
                mode = mv["to"]
                continue
            if t >= mv["at"]:
                a = _vector(self.states[mv["from"]], self.chrome.get(mv["from"], 0))
                b = _vector(self.states[mv["to"]], self.chrome.get(mv["to"], 0))
                e = self.ease((t - mv["at"]) / mv["duration"])
                return [p + (q - p) * e for p, q in zip(a, b)], mv["from"]
            break
        return _vector(self.states[mode], self.chrome.get(mode, 0)), mode

    def _punch_at(self, t: float) -> float:
        scale = 1.0
        for s in self.steps:
            if s["at"] <= t:
                scale = float(s["scale"])
            else:
                break
        return scale

    def state(self, t: float) -> Dict[str, Any]:
        v, mode = self._vec_at(t)
        ct, cr, cb, cl, radius, vx, vy, scale, chrome = v
        punch = self._punch_at(t)
        ox, oy = self.origins.get(mode, (W / 2, H * 0.45))
        return {"window": (cl, ct, W - cr - cl, H - cb - ct), "radius": max(0.0, radius),
                "scale": scale * punch, "x": ox + punch * (vx - ox), "y": oy + punch * (vy - oy),
                "edge": chrome, "mode": mode, "punch": punch}

    # -- painting -------------------------------------------------------------
    def _mask(self, win, radius: float) -> Image.Image:
        key = (round(win[0]), round(win[1]), round(win[2]), round(win[3]), round(radius))
        hit = self._masks.get(key)
        if hit is None:
            big = Image.new("L", (W * SS // 4, H * SS // 4), 0)
            d = ImageDraw.Draw(big)
            box = [key[0] * SS / 4, key[1] * SS / 4,
                   (key[0] + key[2]) * SS / 4 - 1, (key[1] + key[3]) * SS / 4 - 1]
            if key[4] > 0:
                d.rounded_rectangle(box, radius=key[4] * SS / 4, fill=255)
            else:
                d.rectangle(box, fill=255)
            hit = big.resize((W, H), Image.LANCZOS)
            if len(self._masks) > 64:
                self._masks.clear()
            self._masks[key] = hit
        return hit

    def _edge(self, win, radius: float) -> Image.Image:
        """The white ring #pv-edge drew: the window grown by its width, minus the window."""
        key = (round(win[0]), round(win[1]), round(win[2]), round(win[3]), round(radius))
        hit = self._edges.get(key)
        if hit is None:
            g = self.edge_width
            big = Image.new("L", (W * SS // 4, H * SS // 4), 0)
            d = ImageDraw.Draw(big)
            outer = [(key[0] - g) * SS / 4, (key[1] - g) * SS / 4,
                     (key[0] + key[2] + g) * SS / 4 - 1, (key[1] + key[3] + g) * SS / 4 - 1]
            inner = [key[0] * SS / 4, key[1] * SS / 4,
                     (key[0] + key[2]) * SS / 4 - 1, (key[1] + key[3]) * SS / 4 - 1]
            if key[4] > 0:
                d.rounded_rectangle(outer, radius=(key[4] + g) * SS / 4, fill=255)
                d.rounded_rectangle(inner, radius=key[4] * SS / 4, fill=0)
            else:
                d.rectangle(outer, fill=255)
                d.rectangle(inner, fill=0)
            hit = big.resize((W, H), Image.LANCZOS)
            if len(self._edges) > 64:
                self._edges.clear()
            self._edges[key] = hit
        return hit

    def frame(self, source: Image.Image, t: float) -> Image.Image:
        """One composited presenter frame: page colour, the presenter, the window edge."""
        st = self.state(t)
        canvas = Image.new("RGB", (W, H), self.page)
        s = st["scale"]
        vw, vh = max(1, round(W * s)), max(1, round(H * s))
        scaled = source.resize((vw, vh), Image.BILINEAR)
        layer = Image.new("RGB", (W, H), self.page)
        layer.paste(scaled, (round(st["x"]), round(st["y"])))
        canvas.paste(layer, (0, 0), self._mask(st["window"], st["radius"]))
        if st["edge"] > 0.001:
            ring = self._edge(st["window"], st["radius"])
            if st["edge"] * self.edge_alpha < 0.999:
                ring = ring.point(lambda p: int(p * st["edge"] * self.edge_alpha))
            canvas.paste(Image.new("RGB", (W, H), self.edge_rgb), (0, 0), ring)
        return canvas
