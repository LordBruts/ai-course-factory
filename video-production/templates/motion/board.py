"""Board layout engine: where each element sits, and how the page builds up.

Deterministic geometry from brand/spacing.json, computed before any browser starts:

    header        eyebrow + title (+ gallery subtitle), stays for the whole board
    content       safe area below the header, above the reserved caption band
    stack         one column, or two when one would overflow; the first item enters
                  large in the middle and rises into its slot when the next arrives
    dock column   studies inside a stack shrink into a right-hand column
    gallery       focus card in the centre, four dock slots in the corners, filled
                  top-right, bottom-right, top-left, bottom-left

Every element has an outer wrapper (position, rise, dim, dock) and an inner box
(its own entrance), so no two tweens ever fight over the same property.

`layout_report()` returns every rect with the time it is visible; the validator uses
it to refuse overlaps and intrusions into the caption band before rendering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import infographic_boxes as ib
from components import Clip, Tokens, esc

DOCK_ORDER = ("top_right", "bottom_right", "top_left", "bottom_left")


class LayoutError(ValueError):
    pass


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def bottom(self) -> float:
        return self.y + self.h

    def overlaps(self, o: "Rect", pad: float = 0) -> bool:
        return not (self.x + self.w + pad <= o.x or o.x + o.w + pad <= self.x or
                    self.y + self.h + pad <= o.y or o.y + o.h + pad <= self.y)

    def as_dict(self) -> Dict[str, float]:
        return {"x": round(self.x), "y": round(self.y), "w": round(self.w), "h": round(self.h)}


class Geometry:
    """Content area of a board. `panel` narrows it (face template: pages beside the
    presenter); without one it is the whole safe area, as in the faceless template."""

    def __init__(self, t: Tokens, panel: Optional[Rect] = None):
        c = t.space["canvas"]
        s = t.space["safeArea"]
        z = t.space["captionZone"]
        self.W, self.H = c["width"], c["height"]
        self.left, self.right, self.top = s["left"], c["width"] - s["right"], s["top"]
        self.width = self.right - self.left
        self.bottom = c["height"] - (z["bottom"] + z["height"]) - 14      # keep clear of captions
        self.caption_top = c["height"] - (z["bottom"] + z["height"])
        self.panel = panel
        if panel is not None:
            self.left, self.right, self.top = panel.x, panel.x + panel.w, panel.y
            self.width = panel.w
            self.bottom = min(self.bottom, panel.bottom)
        self.header_title_y = self.top + 36
        self.content_top = self.top + 146            # below eyebrow + title
        self.plain_title_y = self.top                # a page with no eyebrow starts higher
        self.plain_content_top = self.top + 108
        self.gallery_top = self.top + 164            # below eyebrow + title + subtitle


def _js_sel(s: str) -> str:
    return s


SURFACES = ("full", "page", "glass")
MIN_COLUMN = 380     # narrower columns wrap infographic labels into one another


class BoardRenderer:
    """`surface`:
        full    the board paints the whole canvas (faceless)
        page    transparent: the face composition paints the page under the presenter
        glass   transparent, with a translucent navy panel at `backdrop` behind the content
    """

    def __init__(self, t: Tokens, board: Dict[str, Any], z: int, first: bool, last: bool,
                 panel: Optional[Rect] = None, surface: str = "full", backdrop: Optional[Rect] = None,
                 forbidden: Sequence[Rect] = (), out_lead: float = 0.45,
                 dock_rects: Optional[Sequence[Rect]] = None):
        if surface not in SURFACES:
            raise ValueError("unknown surface %r" % surface)
        self.t = t
        self.g = Geometry(t, panel)
        self.b = board
        self.z = z
        self.first, self.last = first, last
        self.surface, self.backdrop, self.forbidden = surface, backdrop, list(forbidden)
        self.out_lead = out_lead
        # Face template: where a study docks instead of the right-hand dock column (under
        # the presenter window, which makes room for it). The page keeps its full width.
        self.dock_rects = list(dock_rects) if dock_rects else None
        self.dark = board["kind"] in ("hero", "recap", "outro") or surface == "glass"
        self.bid = "bd-" + board["board_id"].lower()
        self.html: List[str] = []
        self.css: List[str] = []
        self.tl: List[str] = []
        self.rects: List[Dict[str, Any]] = []

    # -------------------------------------------------------------- helpers ---
    def hero_metrics(self) -> Tuple[int, float]:
        """Hero/outro title size and wrap width. A narrow panel gets a smaller, wider title."""
        if self.g.panel is None:
            return (92 if self.b["kind"] == "hero" else 80), self.g.width * 0.72
        return (72 if self.b["kind"] == "hero" else 64), self.g.width

    def eid(self, el: Dict[str, Any], suffix: str = "") -> str:
        return (el["element_id"].lower() + suffix).replace("_", "-")

    def place(self, oid: str, box: ib.Box, r: Rect, at: float, times: Sequence[float], until: float,
              origin: str = "top left", element_id: str = "") -> None:
        # outer .el: position, rise, dim, dock.  .gate: hidden until the entrance, so no
        # part of a box can show early even if its own animation forgets it.
        self.html.append(f'<div class="el" id="{oid}" style="left:{r.x:.0f}px;top:{r.y:.0f}px;'
                         f'width:{r.w:.0f}px;transform-origin:{origin}"><div class="gate" id="{oid}-g">'
                         f'{box.html}</div></div>')
        self.css.append(box.css)
        self.tl.append(ib.from_to(f"#{oid}-g", {"autoAlpha": 0}, {"autoAlpha": 1, "duration": 0.01}, max(0.0, at - 0.12)))
        self.tl += box.anim(at, times)
        self.rects.append({"element_id": element_id or oid, "rect": r.as_dict(), "from": round(at, 3),
                           "to": round(until, 3), "kind": box.kind})

    def box_for(self, el: Dict[str, Any], width: float) -> Optional[ib.Box]:
        t, bid = self.t, self.eid(el, "-bx")
        k = el["kind"]
        if k == "term":
            return ib.term_block(t, bid, el["term"], el.get("definition") or "", el.get("spec"), width)
        if k == "statement":
            return ib.statement(t, bid, el["text"], el.get("icon") or "circle-dot", width,
                                el.get("tone", "plain"), el.get("link"), dark=self.dark)
        if k == "chip":
            return ib.chip(t, bid, el["text"], el.get("icon") or "target", width, dark=self.dark)
        if k == "subtitle":
            return ib.subtitle(t, bid, el["text"], el.get("icon") or "microscope", width)
        if k == "infographic":
            spec = el["spec"]
            kind = spec["kind"]
            link = el.get("link")
            if kind in ("enumeration", "roadmap"):
                return ib.node_row(t, bid, spec, width, link, dark=self.dark,
                                   checklist=(self.b["kind"] == "recap" and kind == "enumeration"),
                                   large=(self.b["kind"] == "hero"))
            if kind == "devices":
                return ib.devices_pair(t, bid, spec, width, link)
            if kind == "wavelengths":
                return ib.wavelength_ruler(t, bid, spec, width, link)
            if kind == "scale":
                return ib.scale_bar(t, bid, spec, width, link)
            if kind == "do_dont":
                return ib.do_dont(t, bid, spec, width, link)
            if kind == "contrast":
                return ib.contrast_block(t, bid, spec, width, link, dark=self.dark)
        return None

    # --------------------------------------------------------------- header ---
    def header(self) -> None:
        g, t, b = self.g, self.t, self.b
        ink = "#FFFFFF" if self.dark else t.navy
        eyebrow = b.get("eyebrow") or ("GYMRAMP" if b["kind"] == "hero" else "")
        if eyebrow:
            self.html.append(f'<div class="hd-eb" id="{self.bid}-eb" style="left:{g.left}px;top:{g.top}px">{esc(eyebrow)}</div>')
            self.tl.append(ib.from_to(f"#{self.bid}-eb", {"opacity": 0, "y": 10},
                                      {"opacity": 1, "y": 0, "duration": t.duration("base")}, b["start"] + 0.1))
        hero_title = b["kind"] in ("hero", "outro")
        first_el = next((e for e in b["elements"]), None)
        for i, title in enumerate(b["titles"]):
            tid = f"{self.bid}-t{i}"
            if hero_title:
                # Starts large in the middle, rises into the header when the page starts building.
                big, title_w = self.hero_metrics()
                small = 60 if g.panel is None else 48
                self.html.append(f'<div class="hd-t hero" id="{tid}" style="left:{g.left}px;top:{g.header_title_y}px;'
                                 f'font-size:{big}px;color:{ink};width:{title_w:.0f}px">{esc(title["text"])}'
                                 f'<i class="hd-rule" id="{tid}-rule"></i></div>')
                dy = (300 if b["kind"] == "hero" else 280) if g.panel is None else 220
                entered = max(b["start"], title["at"]) + 0.15 + t.duration("sceneIn")
                # Rise only after the entrance has finished and the title has been read.
                rise_at = max((first_el["enter_at"] - 0.2) if first_el else b["end"], entered + 0.6)
                self.hero_ready = rise_at + t.duration("rise")
                self.tl.append(ib.from_to(f"#{tid}", {"opacity": 0, "y": dy + 30, "scale": 1},
                                          {"opacity": 1, "y": dy, "scale": 1, "duration": t.duration("sceneIn"),
                                           "ease": t.ease("entrance")}, max(b["start"], title["at"]) + 0.15))
                self.tl.append(ib.from_to(f"#{tid}-rule", {"scaleX": 0}, {"scaleX": 1, "duration": 0.6,
                                                                          "ease": t.ease("standard")}, b["start"] + 0.7))
                if first_el:
                    self.tl.append(ib.from_to(f"#{tid}", {"y": dy, "scale": 1},
                                              {"y": 0, "scale": small / big, "duration": t.duration("rise"),
                                               "ease": t.ease("standard"), "immediateRender": False}, rise_at))
                self.rects.append({"element_id": tid, "rect": Rect(g.left, g.header_title_y, title_w, 70).as_dict(),
                                   "from": b["start"], "to": b["end"], "kind": "title"})
                continue
            nxt = b["titles"][i + 1]["at"] if i + 1 < len(b["titles"]) else b["end"]
            ty = g.header_title_y if eyebrow else g.plain_title_y
            self.html.append(f'<div class="hd-t" id="{tid}" style="left:{g.left}px;top:{ty}px;'
                             f'font-size:56px;color:{ink}">{esc(title["text"])}</div>')
            self.tl.append(ib.from_to(f"#{tid}", {"opacity": 0, "x": -24},
                                      {"opacity": 1, "x": 0, "duration": t.duration("base"), "ease": t.ease("entrance")},
                                      max(b["start"], title["at"]) + 0.05))
            if i + 1 < len(b["titles"]):
                self.tl.append(ib.from_to(f"#{tid}", {"opacity": 1}, {"opacity": 0, "duration": 0.3, "immediateRender": False}, nxt - 0.25))
            self.rects.append({"element_id": tid, "rect": Rect(g.left, ty, g.width, 66).as_dict(),
                               "from": title["at"], "to": nxt, "kind": "title"})
        self.css.append(f"""
#{self.bid} .hd-eb {{ position:absolute; font-size:26px; font-weight:700; letter-spacing:.14em;
  color:{t.accent if self.dark else t.colors['accent']['primaryDeep']}; }}
#{self.bid} .hd-t {{ position:absolute; font-weight:700; line-height:1.1; letter-spacing:-.015em; transform-origin:left top; }}
#{self.bid} .hd-t .hd-rule {{ display:block; width:160px; height:8px; margin-top:26px; background:{t.accent}; border-radius:4px;
  transform-origin:left center; }}""")

    # ---------------------------------------------------------------- stack ---
    def stack(self) -> None:
        g, t, b = self.g, self.t, self.b
        main = [e for e in b["elements"] if e["kind"] not in ("study",)]
        studies = [e for e in b["elements"] if e["kind"] == "study"]
        top = g.content_top if b.get("eyebrow") else g.plain_content_top
        hero_delay = 0.0
        if b["kind"] in ("hero", "outro") and b["titles"]:
            big, title_w = self.hero_metrics()
            small = 60 if g.panel is None else 48
            n = ib.lines(b["titles"][0]["text"], big, title_w)
            top = g.header_title_y + (n * big * 1.1 + 34) * (small / big) + 44
            hero_delay = None      # set from the title's rise, below
        avail = g.bottom - top
        main_w = g.width - (400 if studies and not self.dock_rects else 0)

        def measure(width: float) -> List[Tuple[Dict[str, Any], ib.Box]]:
            return [(e, self.box_for(e, width)) for e in main]

        def gap_before(e: Dict[str, Any]) -> float:
            return 42 if e.get("link") else 24

        slack = 14    # heights are estimated pessimistically; do not split a page over a few pixels

        layout: List[Tuple[Dict[str, Any], ib.Box, Rect]] = []
        for cols in (1, 2):
            col_w = main_w if cols == 1 else (main_w - 64) / 2
            if col_w < MIN_COLUMN:
                continue
            boxes = measure(col_w)
            if any(bx is None for _, bx in boxes):
                raise LayoutError("%s: an element has no renderer" % b["board_id"])
            placed, col, y = [], 0, top
            ok = True
            for e, bx in boxes:
                need = (gap_before(e) if y > top else 0) + bx.h
                if y + need > top + avail + slack:
                    if cols == 2 and col == 0:
                        col, y = 1, top
                        need = bx.h
                    else:
                        ok = False
                        break
                y += need - bx.h
                x = g.left + col * (col_w + 64)
                placed.append((e, bx, Rect(x, y, col_w, bx.h)))
                y += bx.h
            if ok:
                layout = placed
                break
        if main and not layout:
            raise LayoutError("%s: content does not fit even in two columns" % b["board_id"])

        # When a single column leaves space, centre the block vertically so the page is balanced.
        if layout and all(r.x == g.left for _, _, r in layout):
            used = layout[-1][2].bottom - top
            shift = max(0.0, (avail - used) / 2) * 0.6
            layout = [(e, bx, Rect(r.x, r.y + shift, r.w, r.h)) for e, bx, r in layout]

        # Entrance times: an item after a rise waits for the rise to clear.
        rise_idx = None
        if len(layout) >= 2 and layout[1][0]["enter_at"] - layout[0][0]["enter_at"] >= 1.5:
            rise_idx = 0
        dims = {s["element_id"]: (s["enter_at"] - 0.05, s["dock_at"] + 0.25) for s in studies}

        for i, (e, bx, r) in enumerate(layout):
            oid = self.eid(e)
            at = e["enter_at"] + (0.45 if (rise_idx is not None and i == 1) else 0)
            if hero_delay is None and i == 0 and getattr(self, "hero_ready", None):
                at = max(at, self.hero_ready - 0.1)      # the page builds once the title has risen
            times = e.get("item_times", [])
            self.place(oid, bx, r, at, times, b["end"], element_id=e["element_id"])
            if i == rise_idx:
                hero_y = top + (avail - bx.h) / 2
                hero_x = g.left + (g.width - r.w) / 2
                rise_at = layout[1][0]["enter_at"] - 0.25
                self.tl.append(ib.from_to(f"#{oid}", {"x": hero_x - r.x, "y": hero_y - r.y},
                                          {"x": 0, "y": 0, "duration": self.t.duration("rise"),
                                           "ease": self.t.ease("standard")}, rise_at))
                self.rects[-1]["hero_rect"] = Rect(hero_x, hero_y, r.w, r.h).as_dict()
                self.rects[-1]["hero_until"] = round(rise_at, 3)
            # connector: same column, directly below its predecessor
            if i and e.get("link") and layout[i - 1][2].x == r.x:
                prev = layout[i - 1][2]
                cx = r.x + 38
                y0, y1 = prev.bottom + 6, r.y - 4
                if y1 - y0 > 12:
                    cid = oid + "-cn"
                    self.html.append(f'<div class="cn" id="{cid}" style="left:{cx - 2:.0f}px;top:{y0:.0f}px;height:{y1 - y0:.0f}px"><i></i></div>')
                    self.tl.append(ib.from_to(f"#{cid}", {"scaleY": 0}, {"scaleY": 1, "duration": 0.4, "ease": "none"},
                                              at - 0.35))
            # a study in focus hides whatever it would cover, then gives the page back
            for sid, (d0, d1) in dims.items():
                if e["enter_at"] < d0:
                    self.tl.append(ib.from_to(f"#{oid}", {"opacity": 1}, {"opacity": 0, "duration": self.t.duration("dim"), "immediateRender": False}, d0))
                    self.tl.append(ib.from_to(f"#{oid}", {"opacity": 0}, {"opacity": 1, "duration": self.t.duration("dim"), "immediateRender": False}, d1))
                    self.rects[-1].setdefault("hidden", []).append([round(d0, 3), round(d1, 3)])

        # studies: focus in the middle, then dock into the right-hand column
        for k, s in enumerate(studies):
            if self.dock_rects is not None:
                if k >= len(self.dock_rects):
                    raise LayoutError("%s: too many studies for the presenter dock" % b["board_id"])
                dock = self.dock_rects[k]
            else:
                dock = Rect(g.right - 360, top + k * (262 + 18), 360, 262)
            if dock.bottom > g.bottom:
                raise LayoutError("%s: too many studies for the dock column" % b["board_id"])
            focus_w = min(1000, g.width)
            fbox = ib.study_focus(t, self.eid(s, "-fbx"), s["study"], focus_w, max_h=avail)
            if fbox.h > avail:
                raise LayoutError("%s: study card too tall (%dpx)" % (s["element_id"], fbox.h))
            frect = Rect(g.left + (g.width - focus_w) / 2, top + (avail - fbox.h) / 2, focus_w, fbox.h)
            self._focus_and_dock(s, fbox, frect, dock, earlier_docks=[self.eid(x, "-mini") for x in studies[:k]])

    # --------------------------------------------------------------- gallery ---
    def gallery(self) -> None:
        g, t, b = self.g, self.t, self.b
        top = g.gallery_top
        avail = g.bottom - top
        slot_w = 340 if g.panel is None else min(340, (g.width - 88 - 560) / 2)
        slot_h = (avail - 18) / 2
        slots = {
            "top_right": Rect(g.right - slot_w, top, slot_w, slot_h),
            "bottom_right": Rect(g.right - slot_w, top + slot_h + 18, slot_w, slot_h),
            "top_left": Rect(g.left, top, slot_w, slot_h),
            "bottom_left": Rect(g.left, top + slot_h + 18, slot_w, slot_h),
        }
        focus_w = g.width - 2 * slot_w - 2 * 44
        subtitles = [e for e in b["elements"] if e["kind"] == "subtitle"]
        for i, e in enumerate(subtitles):
            bx = self.box_for(e, g.width)
            until = next((x["at"] for x in b["titles"] if x["at"] > e["enter_at"]), b["end"])
            self.place(self.eid(e), bx, Rect(g.left, g.top + 100, g.width, 48), e["enter_at"], [], until,
                       element_id=e["element_id"])
        studies = [e for e in b["elements"] if e["kind"] == "study"]
        if len(studies) > len(DOCK_ORDER):
            raise LayoutError("%s: more studies than dock slots" % b["board_id"])
        if g.panel is not None:
            # A narrow gallery cannot fit a readable card between two columns. The focus
            # card takes the left side instead, over the left slots, which fill last; a
            # study already docked there steps back while the next one is read.
            focus_w = g.width - slot_w - 44
        boxes, frects = [], []
        for k, s in enumerate(studies):
            fbox = ib.study_focus(t, self.eid(s, "-fbx"), s["study"], focus_w, max_h=avail)
            if fbox.h > avail:
                raise LayoutError("%s: study card too tall (%dpx)" % (s["element_id"], fbox.h))
            x = g.left + (g.width - focus_w) / 2 if g.panel is None else g.left
            boxes.append(fbox)
            frects.append(Rect(x, top + (avail - fbox.h) / 2, focus_w, fbox.h))
        # When each docked card appears. In a narrow gallery a card whose slot the next focus
        # card covers would appear and vanish at once, so it waits until that study has docked.
        mini_at = [s["dock_at"] + t.duration("dock") * 0.55 for s in studies]
        if g.panel is not None:
            for j in range(len(studies)):
                for k in range(j):
                    if slots[DOCK_ORDER[k]].overlaps(frects[j]) and mini_at[k] > studies[j]["enter_at"] - 0.6:
                        mini_at[k] = max(mini_at[k], studies[j]["dock_at"] + 0.3)
        for k, s in enumerate(studies):
            covered = []
            if g.panel is not None:
                covered = [self.eid(x, "-mini") for j, x in enumerate(studies[:k])
                           if slots[DOCK_ORDER[j]].overlaps(frects[k]) and mini_at[j] <= s["enter_at"] - 0.6]
            s["slot_name"] = DOCK_ORDER[k]
            self._focus_and_dock(s, boxes[k], frects[k], slots[DOCK_ORDER[k]], earlier_docks=covered,
                                 mini_at=mini_at[k] if g.panel is not None else None)

    def _focus_and_dock(self, s: Dict[str, Any], fbox: ib.Box, frect: Rect, dock: Rect,
                        earlier_docks: Sequence[str], mini_at: Optional[float] = None) -> None:
        t = self.t
        fid, mid = self.eid(s, "-focus"), self.eid(s, "-mini")
        at, dock_at = s["enter_at"], s["dock_at"]
        # For the overlap check the focus card is gone once it is well into its shrink.
        self.place(fid, fbox, frect, at, s.get("item_times", []), dock_at + 0.3,
                   element_id=s["element_id"] + ":focus")
        scale = dock.w / frect.w
        self.tl.append(ib.from_to(f"#{fid}", {"x": 0, "y": 0, "scale": 1, "opacity": 1},
                                  {"x": dock.x - frect.x, "y": dock.y - frect.y, "scale": scale, "opacity": 0,
                                   "duration": t.duration("dock"), "ease": t.ease("standard"),
                                   "immediateRender": False}, dock_at))
        mbox = ib.study_mini(t, self.eid(s, "-mbx"), s["study"], dock.w, dock.h)
        self.html.append(f'<div class="el" id="{mid}" style="left:{dock.x:.0f}px;top:{dock.y:.0f}px;width:{dock.w:.0f}px">{mbox.html}</div>')
        self.css.append(mbox.css)
        shown = dock_at + t.duration("dock") * 0.55 if mini_at is None else mini_at
        self.tl.append(ib.from_to(f"#{mid}", {"opacity": 0, "scale": 1.15},
                                  {"opacity": 1, "scale": 1, "duration": t.duration("base"), "ease": t.ease("entrance")},
                                  shown))
        self.rects.append({"element_id": s["element_id"] + ":dock", "rect": dock.as_dict(),
                           "from": round(shown, 3), "to": self.b["end"], "kind": "study_mini",
                           # docked beside the presenter, in the room the shortened window leaves
                           "beside_presenter": bool(self.dock_rects)})
        for d in earlier_docks:
            self.tl.append(ib.from_to(f"#{d}", {"opacity": 1}, {"opacity": 0, "duration": t.duration("dim"), "immediateRender": False}, at - 0.05))
            self.tl.append(ib.from_to(f"#{d}", {"opacity": 0}, {"opacity": 1, "duration": t.duration("dim"), "immediateRender": False}, dock_at + 0.25))
            for r in self.rects:
                if r["element_id"] == d.replace("-mini", "").upper() + ":dock" or r.get("_dom") == d:
                    r.setdefault("hidden", []).append([round(at - 0.05, 3), round(dock_at + 0.25, 3)])

    # ---------------------------------------------------------------- render ---
    def render(self) -> Clip:
        b, t = self.b, self.t
        self.header()
        if b["kind"] == "gallery":
            self.gallery()
        else:
            self.stack()
        dur = b["end"] - b["start"]
        bg = t.colors["surface"]["dark"] if self.dark else t.page
        if self.surface != "full":
            # The presenter shows through: the board paints nothing but its content.
            bg = "transparent"
            if not self.last:
                # Transparent boards cannot hide their predecessor by covering it, so each
                # one leaves on its own before the next arrives.
                self.tl.append(ib.from_to(f"#{self.bid}", {"opacity": 1},
                                          {"opacity": 0, "duration": 0.4, "immediateRender": False}, b["end"] - self.out_lead))
        if self.surface == "glass" and self.backdrop is not None:
            r = self.backdrop
            self.html.insert(0, f'<div class="glass" style="left:{r.x:.0f}px;top:{r.y:.0f}px;'
                                f'width:{r.w:.0f}px;height:{r.h:.0f}px"></div>')
            self.css.append(f"""
#{self.bid} .glass {{ position:absolute; border-radius:32px; background:rgba(11,31,51,.80);
  box-shadow:0 30px 80px rgba(0,0,0,.35); border:1px solid rgba(255,255,255,.10); }}""")
        if not self.first:
            self.tl.insert(0, ib.from_to(f"#{self.bid}", {"opacity": 0}, {"opacity": 1, "duration": 0.4}, b["start"]))
        css = f"""
#{self.bid} {{ background:{bg}; }}
#{self.bid} .el {{ position:absolute; }}
#{self.bid} .cn {{ position:absolute; width:4px; background:{t.accent}; transform-origin:top center; border-radius:2px; }}
#{self.bid} .cn i {{ position:absolute; left:-8px; bottom:-10px; border:10px solid transparent; border-top:12px solid {t.accent};
  border-bottom:0; }}""" + "".join(self.css)
        html = (f'<section id="{self.bid}" class="clip board" data-start="{b["start"]:.3f}" data-duration="{dur:.3f}" '
                f'data-track-index="1" style="z-index:{self.z}">' + "".join(self.html) + "</section>")
        return Clip(html, css, self.tl)


def render_boards(t: Tokens, boards: Sequence[Dict[str, Any]],
                  modes: Optional[Sequence[Dict[str, Any]]] = None) -> Tuple[List[Clip], List[Dict[str, Any]]]:
    """`modes` (face template): per board {panel, surface, backdrop, forbidden} as Rects."""
    clips, report = [], []
    for i, b in enumerate(boards):
        m = (modes or [None] * len(boards))[i] or {}
        r = BoardRenderer(t, b, z=10 + i, first=(i == 0), last=(i == len(boards) - 1),
                          panel=m.get("panel"), surface=m.get("surface", "full"),
                          backdrop=m.get("backdrop"), forbidden=m.get("forbidden", ()),
                          out_lead=m.get("out_lead", 0.45), dock_rects=m.get("dock_rects"))
        clips.append(r.render())
        entry = {"board_id": b["board_id"], "kind": b["kind"], "start": b["start"], "end": b["end"],
                 "rects": r.rects}
        if m:
            entry.update({"mode": m.get("name"), "surface": r.surface,
                          "panel": m["panel"].as_dict() if m.get("panel") else None,
                          "forbidden": [f.as_dict() for f in r.forbidden]})
        report.append(entry)
    return clips, report


def check_layout(report: Sequence[Dict[str, Any]], t: Tokens) -> List[str]:
    """Overlaps between things visible at the same time, and caption-band intrusions."""
    problems = []
    for b in report:
        g = Geometry(t, Rect(**b["panel"]) if b.get("panel") else None)
        forbidden = [Rect(**f) for f in b.get("forbidden") or []]
        rects = b["rects"]
        for r in rects:
            rr = Rect(**r["rect"])
            if r.get("beside_presenter"):
                continue      # outside the page panel by design; checked against the short window
            if rr.bottom > g.caption_top or rr.x < g.left - 1 or rr.x + rr.w > g.right + 1 or rr.y < g.top - 1:
                problems.append("%s: %s leaves the safe area or enters the caption band (%s)"
                                % (b["board_id"], r["element_id"], r["rect"]))
            for f in forbidden:
                if rr.overlaps(f):
                    problems.append("%s: %s covers the presenter (%s)" % (b["board_id"], r["element_id"], r["rect"]))
        for i, a in enumerate(rects):
            for c in rects[i + 1:]:
                if a["kind"] == "title" or c["kind"] == "title":
                    continue
                t0, t1 = max(a["from"], c["from"]), min(a["to"], c["to"])
                if t1 - t0 <= 0.05:
                    continue
                if _hidden_throughout(a, t0, t1) or _hidden_throughout(c, t0, t1):
                    continue
                ra, rc = Rect(**a["rect"]), Rect(**c["rect"])
                if ra.overlaps(rc):
                    problems.append("%s: %s overlaps %s between %.1fs and %.1fs"
                                    % (b["board_id"], a["element_id"], c["element_id"], t0, t1))
    return problems


def _hidden_throughout(r: Dict[str, Any], t0: float, t1: float) -> bool:
    return any(h0 <= t0 + 0.4 and h1 >= t1 - 0.4 for h0, h1 in r.get("hidden", []))
