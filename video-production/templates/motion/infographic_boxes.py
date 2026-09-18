"""Infographic and card builders for boards.

Each builder returns a `Box`: fixed width, a height computed from its content, its
markup and CSS scoped to its id, and an `anim(start, item_times)` that returns the GSAP
lines for its own entrance. Boxes know nothing about where they sit — `board.py`
places them and moves them. Keeping measurement here, next to the markup it measures,
is what lets the layout engine refuse a page that would overflow before any browser
is started.

Text is escaped and never rewritten. Where a design needs capitals, CSS does it, so
the words in the DOM stay the approved words.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from components import Tokens, esc

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
_ICON_CACHE: Dict[str, str] = {}

K_BOLD = 0.64      # average advance of Montserrat 600-700, in em (measured: 0.58 wrapped early)
K_REGULAR = 0.57


def icon_svg(name: str) -> str:
    if name not in _ICON_CACHE:
        path = os.path.join(ICON_DIR, name + ".svg")
        if not os.path.exists(path):
            path = os.path.join(ICON_DIR, "circle-dot.svg")
        with open(path, encoding="utf-8") as fh:
            svg = fh.read()
        svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S).strip()
        svg = re.sub(r'\s(width|height)="24"', "", svg)
        svg = svg.replace('class="lucide', 'aria-hidden="true" class="lucide', 1)
        _ICON_CACHE[name] = re.sub(r"\s+", " ", svg)
    return _ICON_CACHE[name]


def lines(text: str, px: float, width: float, bold: bool = True) -> int:
    """Estimated wrapped line count (a little pessimistic on purpose)."""
    if not text:
        return 0
    k = K_BOLD if bold else K_REGULAR
    words = text.split()
    count, cur = 1, 0.0
    space = px * 0.28
    for w in words:
        ww = len(w) * px * k
        if cur and cur + space + ww > width:
            count += 1
            cur = ww
        else:
            cur = cur + (space if cur else 0) + ww
    return count


def fit_px(text: str, width: float, start: int, floor: int, max_lines: int, bold: bool = True) -> int:
    px = start
    while px > floor and lines(text, px, width, bold) > max_lines:
        px -= 2
    return px


def js(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, separators=(",", ":"))


def from_to(sel: str, frm: Dict[str, Any], to: Dict[str, Any], at: float) -> str:
    """A seekable tween. Entrances render their start state at once (the element is
    hidden until it enters); a later change of state must pass immediateRender False,
    or it would overwrite the entrance's hidden start at load."""
    to = dict(to)
    to.setdefault("immediateRender", True)
    return "tl.fromTo(%s, %s, %s, %.3f);" % (json.dumps(sel), js(frm), js(to), at)


@dataclass
class Box:
    id: str
    w: float
    h: float
    html: str
    css: str
    anim: Callable[[float, Sequence[float]], List[str]] = field(default=lambda s, t: [])
    kind: str = ""


def _enter(t: Tokens, sel: str, at: float, y: int = 26) -> str:
    return from_to(sel, {"opacity": 0, "y": y}, {"opacity": 1, "y": 0, "duration": t.duration("base"),
                                                   "ease": t.ease("entrance")}, at)


def _pop(t: Tokens, sel: str, at: float) -> str:
    return from_to(sel, {"opacity": 0, "scale": 0.6}, {"opacity": 1, "scale": 1, "duration": t.duration("base"),
                                                       "ease": t.ease("emphasis")}, at)


def _link_pill(t: Tokens, text: Optional[str]) -> str:
    if not text:
        return ""
    return '<div class="link-pill">%s</div>' % esc(text)


def base_css(t: Tokens) -> str:
    """Shared classes used by every box."""
    return f"""
.bx {{ position:absolute; left:0; top:0; }}
.ic {{ display:inline-grid; place-items:center; flex:none; }}
.ic svg {{ width:100%; height:100%; stroke-width:1.9; }}
.link-pill.inl {{ margin:0 18px 0 0; vertical-align:middle; }}
.link-pill {{ display:inline-block; font-size:26px; font-weight:700; letter-spacing:.08em; text-transform:uppercase;
  color:{t.colors['accent']['primaryDeep']}; background:{t.accent_soft}; border-radius:999px; padding:4px 16px;
  margin-bottom:12px; }}
.muted {{ color:{t.muted}; }}
"""


# ---------------------------------------------------------------- builders ---

def statement(t: Tokens, bid: str, text: str, icon: str, width: float, tone: str = "plain",
              link: Optional[str] = None, dark: bool = False) -> Box:
    px = fit_px(text, width - 110, 42, 32, 3)
    n = lines(text, px, width - 110)
    link_h = 48 if link else 0
    h = link_h + max(76, n * px * 1.25) + 8
    color = {"caution": t.colors["status"]["warn"], "accent": t.accent}.get(tone, t.navy if not dark else t.accent)
    ink = "#FFFFFF" if dark else t.navy
    html = f"""<div class="bx st" id="{bid}">{_link_pill(t, link)}
  <div class="st-row"><span class="ic st-ic" id="{bid}-ic">{icon_svg(icon)}</span>
  <div class="st-tx" style="font-size:{px}px">{esc(text)}</div></div></div>"""
    css = f"""
#{bid} {{ width:{width:.0f}px; }}
#{bid} .st-row {{ display:flex; gap:28px; align-items:flex-start; }}
#{bid} .st-ic {{ width:76px; height:76px; border-radius:22px; color:{color};
  background:{'rgba(255,255,255,.08)' if dark else t.card}; box-shadow:{'none' if dark else '0 6px 18px rgba(11,31,51,.08)'}; }}
#{bid} .st-ic svg {{ width:40px; height:40px; }}
#{bid} .st-tx {{ font-weight:600; line-height:1.25; color:{ink}; padding-top:6px; }}"""

    def anim(at: float, _t: Sequence[float]) -> List[str]:
        out = [_pop(t, f"#{bid}-ic", at), _enter(t, f"#{bid} .st-tx", at + 0.08)]
        if link:
            out.append(_enter(t, f"#{bid} .link-pill", at - 0.1, 10))
        return out

    return Box(bid, width, h, html, css, anim, "statement")


def chip(t: Tokens, bid: str, text: str, icon: str, width: float, dark: bool = False) -> Box:
    px = fit_px(text, width - 120, 38, 30, 2)
    n = lines(text, px, width - 120)
    h = max(84, n * px * 1.25 + 32)
    html = f"""<div class="bx ch" id="{bid}"><span class="ic">{icon_svg(icon)}</span>
  <span class="ch-tx" style="font-size:{px}px">{esc(text)}</span></div>"""
    css = f"""
#{bid} {{ display:inline-flex; gap:18px; align-items:center; max-width:{width:.0f}px; padding:16px 30px;
  border-radius:999px; background:{t.colors['accent']['primaryDeep']}; color:#fff; box-shadow:0 10px 26px rgba(199,78,23,.28); }}
#{bid} .ic {{ width:40px; height:40px; }}
#{bid} .ch-tx {{ font-weight:700; line-height:1.2; }}"""

    def anim(at: float, _t: Sequence[float]) -> List[str]:
        return [from_to(f"#{bid}", {"opacity": 0, "scale": 0.85}, {"opacity": 1, "scale": 1, "duration": t.duration("base"),
                                                                   "ease": t.ease("emphasis")}, at)]

    return Box(bid, width, h, html, css, anim, "chip")


def light_band_html(t: Tokens, bid: str, labels: Sequence[str], width: float) -> (str, str, float):
    red, nir = labels[0], labels[1]
    html = f"""<div class="lb" id="{bid}-lb"><div class="lb-bar" id="{bid}-lbbar"></div>
  <div class="lb-labels"><span>{esc(red)}</span><span>{esc(nir)}</span></div></div>"""
    css = f"""
#{bid}-lb {{ width:{width:.0f}px; margin-top:26px; }}
#{bid}-lb .lb-bar {{ height:34px; border-radius:17px; transform-origin:left center;
  background:linear-gradient(90deg,#FF3B30 0%,#D7263D 38%,#7A1020 58%,#3A0A14 78%,rgba(58,10,20,.25) 100%); }}
#{bid}-lb .lb-labels {{ display:flex; justify-content:space-between; margin-top:10px; font-size:28px; font-weight:600;
  color:{t.muted}; }}
#{bid}-lb .lb-labels span:first-child {{ color:#D7263D; }}"""
    return html, css, 26 + 34 + 10 + 36


def term_block(t: Tokens, bid: str, term: str, definition: str, band: Optional[Dict[str, Any]], width: float) -> Box:
    tpx = fit_px(term, width, 66, 44, 1)
    dpx = fit_px(definition, width, 34, 28, 3, bold=False)
    h = tpx * 1.15 + 16 + lines(definition, dpx, width, False) * dpx * 1.4
    band_html, band_css = "", ""
    if band:
        band_html, band_css, bh = light_band_html(t, bid, band["labels"], width)
        h += bh
    html = f"""<div class="bx tm" id="{bid}"><div class="tm-term" style="font-size:{tpx}px"><span>{esc(term)}</span>
  <i class="tm-sweep" id="{bid}-sweep"></i></div>
  <div class="tm-def" style="font-size:{dpx}px">{esc(definition)}</div>{band_html}</div>"""
    css = f"""
#{bid} {{ width:{width:.0f}px; }}
#{bid} .tm-term {{ position:relative; display:inline-block; font-weight:700; color:{t.navy}; line-height:1.15; }}
#{bid} .tm-term span {{ position:relative; z-index:1; }}
#{bid} .tm-sweep {{ position:absolute; left:-6px; right:-6px; bottom:6px; height:22px; background:{t.accent_soft};
  transform-origin:left center; z-index:0; }}
#{bid} .tm-def {{ margin-top:16px; color:{t.text}; line-height:1.4; font-weight:500; }}{band_css}"""

    def anim(at: float, _t: Sequence[float]) -> List[str]:
        out = [_enter(t, f"#{bid} .tm-term", at),
               from_to(f"#{bid}-sweep", {"scaleX": 0}, {"scaleX": 1, "duration": 0.45, "ease": t.ease("emphasis")}, at + 0.35),
               _enter(t, f"#{bid} .tm-def", at + 0.5)]
        if band:
            out.append(from_to(f"#{bid}-lbbar", {"scaleX": 0}, {"scaleX": 1, "duration": t.duration("slow"),
                                                               "ease": t.ease("standard")}, at + 1.4))
            out.append(_enter(t, f"#{bid}-lb .lb-labels", at + 1.8, 10))
        return out

    return Box(bid, width, h, html, css, anim, "term")


def _lead_row(t: Tokens, link: Optional[str], lead: str, px: int) -> str:
    if not lead:
        return _link_pill(t, link)
    pill = ('<span class="link-pill inl">%s</span>' % esc(link)) if link else ""
    return '<div class="nr-lead" style="font-size:%dpx">%s<span>%s</span></div>' % (px, pill, esc(lead))


def node_row(t: Tokens, bid: str, spec: Dict[str, Any], width: float, link: Optional[str] = None,
             dark: bool = False, checklist: bool = False, large: bool = False) -> Box:
    items = spec["items"]
    lead = spec.get("lead") or ""
    ink = "#FFFFFF" if dark else t.navy
    lead_px = fit_px(lead, width - (220 if link else 0), 34, 28, 2) if lead else 0
    lead_h = (max(48, lines(lead, lead_px, width - (220 if link else 0)) * lead_px * 1.3) + 18) if lead else 0
    link_h = 48 if (link and not lead) else 0
    n = len(items)
    roadmap = spec["kind"] == "roadmap"
    if checklist:
        row_px = fit_px(max((i["label"] for i in items), key=len), width - 90, 36, 28, 2)
        rows_h = sum(max(64, lines(i["label"], row_px, width - 90) * row_px * 1.3) + 18 for i in items)
        h = link_h + lead_h + rows_h
        rows = "".join(
            f'<div class="cl-row" id="{bid}-n{k}"><span class="ic cl-ic">{icon_svg("check")}</span>'
            f'<span class="cl-tx" style="font-size:{row_px}px">{esc(i["label"])}</span></div>' for k, i in enumerate(items))
        html = f"""<div class="bx nr" id="{bid}">{_lead_row(t, link, lead, lead_px)}{rows}</div>"""
        css = f"""
#{bid} {{ width:{width:.0f}px; }}
#{bid} .nr-lead {{ font-weight:600; color:{t.muted if not dark else 'rgba(255,255,255,.7)'}; margin-bottom:18px; line-height:1.3; }}
#{bid} .cl-row {{ display:flex; gap:22px; align-items:center; margin-bottom:18px; }}
#{bid} .cl-ic {{ width:64px; height:64px; border-radius:50%; background:{t.accent}; color:#fff; }}
#{bid} .cl-ic svg {{ width:34px; height:34px; stroke-width:2.6; }}
#{bid} .cl-tx {{ font-weight:600; color:{ink}; line-height:1.3; }}"""
    else:
        longest = max((len(wd) for i in items for wd in i["label"].split()), default=1)

        def arrange(cols: int, grid: bool):
            cell_w = (width - (cols - 1) * 28) / cols
            circle = (128 if large else 96) if not grid else 76
            text_w = cell_w - (0 if not grid else circle + 18)
            px = min(fit_px(i["label"], text_w, 38 if large else 32, 26, 3) for i in items)
            return cell_w, circle, px, text_w / (K_BOLD * longest)

        grid = (n >= 4 and width < 1100)
        cols = 2 if grid else n
        cell_w, circle, label_px, word_px = arrange(cols, grid)
        # A word wider than its cell spills into the next one. Narrow pages (the face
        # template's panels) fall back to two columns, then to a list.
        for fewer in (2, 1):
            if word_px < 24 and cols > fewer:
                cols, grid = fewer, True
                cell_w, circle, label_px, word_px = arrange(cols, grid)
        label_px = int(min(label_px, word_px))
        if grid:
            cell_h = max(circle, max(lines(i["label"], label_px, cell_w - circle - 18) for i in items) * label_px * 1.25) + 20
            body_h = cell_h * math.ceil(n / cols)
        else:
            body_h = circle + 16 + max(lines(i["label"], label_px, cell_w) for i in items) * label_px * 1.25
        h = link_h + lead_h + body_h + 6
        cells = []
        for k, i in enumerate(items):
            num = f'<b class="nd-num">{k + 1}</b>' if roadmap else ""
            cells.append(f'<div class="nd" id="{bid}-n{k}"><span class="ic nd-ic">{icon_svg(i["icon"])}{num}</span>'
                         f'<span class="nd-tx" style="font-size:{label_px}px">{esc(i["label"])}</span></div>')
        track = "" if grid else f'<i class="nd-track" id="{bid}-track"></i>'
        html = f"""<div class="bx nr" id="{bid}">{_lead_row(t, link, lead, lead_px)}
  <div class="nd-wrap">{track}{''.join(cells)}</div></div>"""
        css = f"""
#{bid} {{ width:{width:.0f}px; }}
#{bid} .nr-lead {{ font-weight:600; color:{t.muted if not dark else 'rgba(255,255,255,.72)'}; margin-bottom:18px; line-height:1.3;
  {'text-transform:uppercase; letter-spacing:.06em;' if roadmap else ''} }}
#{bid} .nd-wrap {{ position:relative; display:grid; grid-template-columns:repeat({cols}, {cell_w:.0f}px); gap:{'20px 28px' if grid else '0 28px'}; }}
#{bid} .nd-track {{ position:absolute; left:{cell_w / 2:.0f}px; right:{cell_w / 2:.0f}px; top:{circle / 2 - 2:.0f}px; height:4px;
  background:{t.accent if roadmap else (t.rule if not dark else 'rgba(255,255,255,.2)')}; transform-origin:left center; }}
#{bid} .nd {{ position:relative; display:flex; {'flex-direction:row; align-items:center; gap:18px;' if grid else 'flex-direction:column; align-items:center; text-align:center; gap:16px;'} }}
#{bid} .nd-ic {{ position:relative; width:{circle}px; height:{circle}px; border-radius:50%;
  background:{'#FFFFFF' if not dark else t.colors['surface']['darkAlt']}; color:{t.accent};
  box-shadow:{'0 8px 22px rgba(11,31,51,.10)' if not dark else 'none'}; border:3px solid {t.accent if roadmap else (t.rule if not dark else 'rgba(255,255,255,.18)')}; }}
#{bid} .nd-ic svg {{ width:{circle * 0.46:.0f}px; height:{circle * 0.46:.0f}px; }}
#{bid} .nd-num {{ position:absolute; right:-8px; top:-8px; width:36px; height:36px; border-radius:50%; background:{t.colors['accent']['primaryDeep']};
  color:#fff; font-size:20px; display:grid; place-items:center; }}
#{bid} .nd-tx {{ font-weight:600; color:{ink}; line-height:1.25; }}"""

    def anim(at: float, times: Sequence[float]) -> List[str]:
        out = []
        cur = at
        if link:
            out.append(_enter(t, f"#{bid} .link-pill", cur, 10))
        if lead:
            out.append(_enter(t, f"#{bid} .nr-lead", cur + 0.05))
        if not checklist and not grid:
            end = (times[-1] if times else at + 0.4 * n) + 0.2
            out.append(from_to(f"#{bid}-track", {"scaleX": 0}, {"scaleX": 1, "duration": max(0.6, end - at - 0.3),
                                                               "ease": "none"}, at + 0.3))
        for k in range(n):
            tk = times[k] if k < len(times) else at + 0.4 + k * t.duration("stagger")
            out.append(_pop(t, f"#{bid}-n{k} .{'cl-ic' if checklist else 'nd-ic'}", tk))
            out.append(_enter(t, f"#{bid}-n{k} .{'cl-tx' if checklist else 'nd-tx'}", tk + 0.1, 14))
        return out

    return Box(bid, width, h, html, css, anim, "nodes")


def devices_pair(t: Tokens, bid: str, spec: Dict[str, Any], width: float, link: Optional[str] = None) -> Box:
    a, b = spec["items"]
    cap = spec["caption"]
    tile_w = min(360, (width - 200) / 2)
    h = (48 if link else 0) + 210
    html = f"""<div class="bx dv" id="{bid}">{_link_pill(t, link)}<div class="dv-row">
  <div class="dv-tile" id="{bid}-a"><span class="ic">{icon_svg(a['icon'])}</span><b>{esc(a['label'])}</b></div>
  <div class="dv-mid" id="{bid}-m"><span class="ic">{icon_svg('git-compare')}</span><em>{esc(cap)}</em></div>
  <div class="dv-tile" id="{bid}-b"><span class="ic">{icon_svg(b['icon'])}</span><b>{esc(b['label'])}</b></div></div></div>"""
    css = f"""
#{bid} {{ width:{width:.0f}px; }}
#{bid} .dv-row {{ display:flex; align-items:center; gap:24px; }}
#{bid} .dv-tile {{ width:{tile_w:.0f}px; height:190px; border-radius:26px; background:{t.card};
  box-shadow:0 10px 28px rgba(11,31,51,.10); display:flex; flex-direction:column; align-items:center; justify-content:center; gap:14px; }}
#{bid} .dv-tile .ic {{ width:78px; height:78px; color:{t.accent}; }}
#{bid} .dv-tile b {{ font-size:34px; color:{t.navy}; }}
#{bid} .dv-mid {{ flex:1; display:flex; flex-direction:column; align-items:center; gap:10px; color:{t.muted}; }}
#{bid} .dv-mid .ic {{ width:56px; height:56px; color:{t.navy}; }}
#{bid} .dv-mid em {{ font-style:normal; font-size:30px; font-weight:600; text-align:center; line-height:1.2; }}"""

    def anim(at: float, _t: Sequence[float]) -> List[str]:
        return [from_to(f"#{bid}-a", {"opacity": 0, "x": -40}, {"opacity": 1, "x": 0, "duration": t.duration("base"), "ease": t.ease("entrance")}, at),
                from_to(f"#{bid}-b", {"opacity": 0, "x": 40}, {"opacity": 1, "x": 0, "duration": t.duration("base"), "ease": t.ease("entrance")}, at + 0.25),
                _pop(t, f"#{bid}-m", at + 0.7)] + ([_enter(t, f"#{bid} .link-pill", at, 10)] if link else [])

    return Box(bid, width, h, html, css, anim, "devices")


def wavelength_ruler(t: Tokens, bid: str, spec: Dict[str, Any], width: float, link: Optional[str] = None) -> Box:
    """Spectrum bar with only the stated wavelengths marked, and what each was used for.

    Pins alternate above and below the bar by group, so close values (630 and 650) never
    share a row; the contexts sit in a legend underneath, keyed by the same accent dot.
    """
    marks = spec["marks"]
    values = [v for m in marks for v in m["values"]]
    lo = min(600, (min(values) // 50) * 50 - 50)
    hi = max(900, (max(values) // 50) * 50 + 100)
    link_h = 48 if link else 0
    pin_row = 44          # value label + tick
    bar_h = 40            # tall enough to carry its end labels inside
    cols = 2 if (len(marks) > 1 and width >= 1100) else 1
    col_w = (width - 40 * (cols - 1)) / cols
    leg_px = min(fit_px(m["context"], col_w - 150, 30, 26, 2, bold=False) for m in marks)
    row_h = max(lines(m["context"], leg_px, col_w - 150, False) for m in marks) * leg_px * 1.3
    leg_h = row_h * math.ceil(len(marks) / cols) + 14 * (math.ceil(len(marks) / cols) - 1)
    h = link_h + pin_row + bar_h + pin_row + 18 + leg_h + 6
    series = t.colors["chart"]["series"]

    def x_of(v: float) -> float:
        return (v - lo) / (hi - lo) * width

    pins, legend = [], []
    for gi, m in enumerate(marks):
        up = gi % 2 == 0
        # Small text on the bright accent fails WCAG 3:1; the deep accent passes.
        colr = series[gi % len(series)] if gi else t.colors["accent"]["primaryDeep"]
        for v in m["values"]:
            pins.append(f'<div class="wr-pin {"up" if up else "dn"}" id="{bid}-p{gi}-{v}" style="left:{x_of(v):.0f}px">'
                        f'<b style="color:{colr}">{v} nm</b><i style="background:{colr}"></i></div>')
        label = " + ".join("%d nm" % v for v in m["values"])
        legend.append(f'<div class="wr-leg" id="{bid}-c{gi}"><span class="wr-key" style="background:{colr}">{label}</span>'
                      f'<span class="wr-lt" style="font-size:{leg_px}px">{esc(m["context"])}</span></div>')
    bar_top = link_h + pin_row
    html = f"""<div class="bx wr" id="{bid}">{_link_pill(t, link)}<div class="wr-stage">
  <div class="wr-bar" id="{bid}-bar"></div>
  <span class="wr-end l" id="{bid}-el">red</span><span class="wr-end r" id="{bid}-er">near-infrared</span>
  {''.join(pins)}</div>
  <div class="wr-legend">{''.join(legend)}</div></div>"""
    css = f"""
#{bid} {{ width:{width:.0f}px; }}
#{bid} .wr-stage {{ position:relative; width:{width:.0f}px; height:{pin_row * 2 + bar_h:.0f}px; }}
#{bid} .wr-bar {{ position:absolute; left:0; right:0; top:{pin_row}px; height:{bar_h}px; border-radius:{bar_h // 2}px;
  transform-origin:left center;
  background:linear-gradient(90deg,#FF5A3C 0%,#D7263D {x_of(700) / width * 100:.0f}%,#5A0F1E {x_of(760) / width * 100:.0f}%,#2A0A12 100%); }}
#{bid} .wr-end {{ position:absolute; top:{pin_row + 3}px; font-size:26px; font-weight:700; color:#fff; line-height:34px; }}
#{bid} .wr-end.l {{ left:18px; }} #{bid} .wr-end.r {{ right:18px; }}
#{bid} .wr-pin {{ position:absolute; transform:translateX(-50%); display:flex; flex-direction:column; align-items:center; }}
#{bid} .wr-pin i {{ width:4px; height:14px; border-radius:2px; }}
#{bid} .wr-pin b {{ font-size:28px; white-space:nowrap; line-height:30px; }}
#{bid} .wr-pin.up {{ top:0; }}
#{bid} .wr-pin.dn {{ top:{pin_row + bar_h}px; flex-direction:column-reverse; }}
#{bid} .wr-legend {{ display:grid; grid-template-columns:repeat({cols}, {col_w:.0f}px); gap:14px 40px; margin-top:18px; }}
#{bid} .wr-leg {{ display:flex; gap:16px; align-items:flex-start; }}
#{bid} .wr-key {{ flex:none; color:#fff; font-size:24px; font-weight:700; padding:6px 12px; border-radius:10px; white-space:nowrap; }}
#{bid} .wr-lt {{ color:{t.text}; line-height:1.3; font-weight:500; }}"""

    def anim(at: float, times: Sequence[float]) -> List[str]:
        out = [from_to(f"#{bid}-bar", {"scaleX": 0}, {"scaleX": 1, "duration": t.duration("slow"), "ease": t.ease("standard")}, at),
               _enter(t, f"#{bid}-el", at + 0.5, 8), _enter(t, f"#{bid}-er", at + 0.6, 8)]
        if link:
            out.append(_enter(t, f"#{bid} .link-pill", at, 10))
        for gi, m in enumerate(marks):
            tg = times[gi] if gi < len(times) else at + 0.8 + gi
            for j, v in enumerate(m["values"]):
                out.append(_pop(t, f"#{bid}-p{gi}-{v}", tg + j * 0.2))
            out.append(_enter(t, f"#{bid}-c{gi}", tg + 0.25, 12))
        return out

    return Box(bid, width, h, html, css, anim, "wavelengths")


def scale_bar(t: Tokens, bid: str, spec: Dict[str, Any], width: float, link: Optional[str] = None) -> Box:
    steps = spec["steps"]
    lead = spec.get("lead") or ""
    colors = [t.colors["status"]["ok"], t.colors["status"]["warn"], t.muted]
    seg_w = (width - 16 * (len(steps) - 1)) / len(steps)
    lpx = fit_px(max((s["label"] for s in steps), key=len), seg_w, 32, 26, 2)
    h = (48 if link else 0) + (52 if lead else 0) + 22 + 18 + 2 * lpx * 1.25 + 10
    segs = "".join(
        f'<div class="sc-seg" id="{bid}-s{k}"><i style="background:{colors[k % 3]}"></i>'
        f'<b style="font-size:{lpx}px;color:{colors[k % 3]}">{esc(s["label"])}</b></div>' for k, s in enumerate(steps))
    html = f"""<div class="bx sc" id="{bid}">{_link_pill(t, link)}{'<div class="sc-lead">%s</div>' % esc(lead) if lead else ''}
  <div class="sc-row">{segs}</div></div>"""
    css = f"""
#{bid} {{ width:{width:.0f}px; }}
#{bid} .sc-lead {{ font-size:32px; font-weight:600; color:{t.muted}; margin-bottom:18px; }}
#{bid} .sc-row {{ display:flex; gap:16px; }}
#{bid} .sc-seg {{ width:{seg_w:.0f}px; display:flex; flex-direction:column; gap:16px; }}
#{bid} .sc-seg i {{ display:block; height:22px; border-radius:11px; transform-origin:left center; }}
#{bid} .sc-seg b {{ line-height:1.25; }}"""

    def anim(at: float, times: Sequence[float]) -> List[str]:
        out = [_enter(t, f"#{bid} .sc-lead", at)] if lead else []
        if link:
            out.append(_enter(t, f"#{bid} .link-pill", at, 10))
        for k in range(len(steps)):
            tk = times[k] if k < len(times) else at + 0.3 + 0.4 * k
            out.append(from_to(f"#{bid}-s{k} i", {"scaleX": 0}, {"scaleX": 1, "duration": t.duration("base"), "ease": t.ease("standard")}, tk))
            out.append(_enter(t, f"#{bid}-s{k} b", tk + 0.12, 10))
        return out

    return Box(bid, width, h, html, css, anim, "scale")


def do_dont(t: Tokens, bid: str, spec: Dict[str, Any], width: float, link: Optional[str] = None) -> Box:
    lead = spec.get("lead") or ""
    # Side by side when each tile leaves room for its words; stacked on a narrow page.
    stacked = (width - 28) / 2 - 130 < 260
    tile_w = width if stacked else (width - 28) / 2
    px = min(fit_px(spec["do"], tile_w - 130, 36, 28, 2), fit_px(spec["dont"], tile_w - 130, 36, 28, 2))
    n_lines = max(2, lines(spec["do"], px, tile_w - 130), lines(spec["dont"], px, tile_w - 130))
    tile_h = max(130, n_lines * px * 1.25 + 56)
    if stacked:
        n_lines = max(lines(spec["do"], px, tile_w - 130), lines(spec["dont"], px, tile_w - 130))
        tile_h = max(110, n_lines * px * 1.25 + 56)
    h = (48 if link else 0) + (52 if lead else 0) + (2 * tile_h + 18 if stacked else tile_h)
    ok, bad = t.colors["status"]["ok"], t.colors["status"]["bad"]
    html = f"""<div class="bx dd" id="{bid}">{_link_pill(t, link)}{'<div class="dd-lead">%s</div>' % esc(lead) if lead else ''}
  <div class="dd-row"><div class="dd-t do" id="{bid}-do"><span class="ic">{icon_svg('check')}</span><b style="font-size:{px}px">{esc(spec['do'])}</b></div>
  <div class="dd-t no" id="{bid}-no"><span class="ic">{icon_svg('x')}</span><b style="font-size:{px}px">{esc(spec['dont'])}</b></div></div></div>"""
    css = f"""
#{bid} {{ width:{width:.0f}px; }}
#{bid} .dd-lead {{ font-size:32px; font-weight:600; color:{t.muted}; margin-bottom:18px; }}
#{bid} .dd-row {{ display:flex; gap:{'18px; flex-direction:column' if stacked else '28px'}; }}
#{bid} .dd-t {{ width:{tile_w:.0f}px; min-height:{110 if stacked else 130}px; box-sizing:border-box; border-radius:24px; padding:26px 28px;
  display:flex; gap:22px; align-items:center; background:{t.card}; box-shadow:0 10px 26px rgba(11,31,51,.08); }}
#{bid} .dd-t .ic {{ width:72px; height:72px; border-radius:50%; color:#fff; }}
#{bid} .dd-t .ic svg {{ width:40px; height:40px; stroke-width:2.8; }}
#{bid} .dd-t.do .ic {{ background:{ok}; }} #{bid} .dd-t.no .ic {{ background:{bad}; }}
#{bid} .dd-t.do {{ border-left:8px solid {ok}; }} #{bid} .dd-t.no {{ border-left:8px solid {bad}; }}
#{bid} .dd-t b {{ color:{t.navy}; line-height:1.25; }}
#{bid} .dd-t.no b {{ text-decoration:line-through; text-decoration-color:{bad}; text-decoration-thickness:3px; }}"""

    def anim(at: float, times: Sequence[float]) -> List[str]:
        return ([_enter(t, f"#{bid} .dd-lead", at)] if lead else []) + (
            [_enter(t, f"#{bid} .link-pill", at, 10)] if link else []) + [
            _enter(t, f"#{bid}-do", at + 0.2), _enter(t, f"#{bid}-no", at + 1.4)]

    return Box(bid, width, h, html, css, anim, "do_dont")


def contrast_block(t: Tokens, bid: str, spec: Dict[str, Any], width: float, link: Optional[str] = None,
                   dark: bool = False) -> Box:
    mpx = fit_px(spec["main"], width, 42, 32, 3)
    cpx = fit_px(spec["caution"], width - 150, 32, 26, 2)
    h = (48 if link else 0) + lines(spec["main"], mpx, width) * mpx * 1.25 + 22 + max(76, lines(spec["caution"], cpx, width - 150) * cpx * 1.3 + 30)
    warn = t.colors["status"]["warn"]
    html = f"""<div class="bx cb" id="{bid}">{_link_pill(t, link)}<div class="cb-main" style="font-size:{mpx}px">{esc(spec['main'])}</div>
  <div class="cb-turn" id="{bid}-turn"><span class="ic">{icon_svg('triangle-alert')}</span><em>{esc(spec['turn'])}</em>
  <b style="font-size:{cpx}px">{esc(spec['caution'])}</b></div></div>"""
    css = f"""
#{bid} {{ width:{width:.0f}px; }}
#{bid} .cb-main {{ font-weight:600; line-height:1.25; color:{'#fff' if dark else t.navy}; }}
#{bid} .cb-turn {{ margin-top:22px; display:flex; gap:16px; align-items:center; padding:14px 24px; border-radius:18px;
  background:{'rgba(255,255,255,.07)' if dark else '#FFF4E0'}; border-left:6px solid {warn}; }}
#{bid} .cb-turn .ic {{ width:42px; height:42px; color:{warn}; }}
#{bid} .cb-turn em {{ font-style:normal; font-size:26px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:{warn}; }}
#{bid} .cb-turn b {{ font-weight:600; color:{'#fff' if dark else t.text}; line-height:1.3; }}"""

    def anim(at: float, _t: Sequence[float]) -> List[str]:
        return ([_enter(t, f"#{bid} .link-pill", at, 10)] if link else []) + [
            _enter(t, f"#{bid} .cb-main", at), _enter(t, f"#{bid}-turn", at + 1.6, 16)]

    return Box(bid, width, h, html, css, anim, "contrast")


def time_strip_html(t: Tokens, bid: str, spec: Dict[str, Any], width: float) -> (str, str, float):
    pts = spec["points"]
    col = (width - 40) / len(pts)
    px = min(fit_px(p["text"], col - 10, 30, 26, 3, bold=False) for p in pts)
    h = 30 + 50 + max(lines(p["text"], px, col - 10, False) for p in pts) * px * 1.3 + 10
    cells = []
    for k, p in enumerate(pts):
        good = not re.search(r"\bnot\b|\bno\b", p["text"])
        c = t.colors["status"]["ok"] if good else t.muted
        cells.append(f'<div class="ts-c" id="{bid}-t{k}"><span class="ts-dot" style="background:{c}"></span>'
                     f'<b style="color:{c}">{esc(p["at"])}</b><p style="font-size:{px}px">{esc(p["text"])}</p></div>')
    html = f'<div class="ts" id="{bid}-ts"><i class="ts-line" id="{bid}-tsl"></i>{"".join(cells)}</div>'
    css = f"""
#{bid}-ts {{ position:relative; display:grid; grid-template-columns:repeat({len(pts)}, 1fr); gap:40px; margin-top:22px; }}
#{bid}-ts .ts-line {{ position:absolute; left:10px; right:10px; top:14px; height:4px; background:{t.rule}; transform-origin:left center; }}
#{bid}-ts .ts-dot {{ position:relative; display:block; width:28px; height:28px; border-radius:50%; border:5px solid #fff;
  box-shadow:0 0 0 2px {t.rule}; }}
#{bid}-ts b {{ display:block; margin-top:12px; font-size:34px; }}
#{bid}-ts p {{ margin:6px 0 0; color:{t.text}; line-height:1.3; }}"""
    return html, css, h


def study_focus(t: Tokens, bid: str, study: Dict[str, Any], width: float, max_h: float = 10_000,
                _shrink: int = 0) -> Box:
    pad = 40 - min(_shrink, 3) * 4
    inner = width - 2 * pad
    title = study.get("title") or ""
    finding = study.get("finding") or ""
    spec = study.get("spec") or {}
    tpx = fit_px(title, inner, 44 - 2 * _shrink, 30, 2)
    fpx = fit_px(finding, inner, 36 - 2 * _shrink, 28, 4)
    h = pad + 40 + 16 + (lines(title, tpx, inner) * tpx * 1.2 + 12 if title else 0)
    if finding:
        h += lines(finding, fpx, inner) * fpx * 1.3 + 8
    extra_html, extra_css = "", ""
    if spec.get("kind") == "time_points":
        extra_html, extra_css, eh = time_strip_html(t, bid, spec, inner)
        h += eh + 22
    elif spec.get("kind") == "enumeration":
        chips = "".join(f'<span class="sf-chip" id="{bid}-k{k}"><span class="ic">{icon_svg(i["icon"])}</span>{esc(i["label"])}</span>'
                        for k, i in enumerate(spec["items"]))
        extra_html = f'<div class="sf-chips">{chips}</div>'
        h += 90
    elif spec.get("kind") == "contrast":
        cpx = fit_px(spec["caution"], inner - 150, 30, 26, 2)
        extra_html = (f'<div class="sf-turn" id="{bid}-turn"><span class="ic">{icon_svg("triangle-alert")}</span>'
                      f'<em>{esc(spec["turn"])}</em><b style="font-size:{cpx}px">{esc(spec["caution"])}</b></div>')
        h += max(72, lines(spec["caution"], cpx, inner - 150) * cpx * 1.3 + 28) + 18
    elif spec.get("kind") == "wavelengths":
        chips = "".join(f'<span class="sf-chip" id="{bid}-k{k}"><span class="ic">{icon_svg("waves")}</span>{v} nm</span>'
                        for k, v in enumerate(v for m in spec["marks"] for v in m["values"]))
        extra_html = f'<div class="sf-chips">{chips}</div>'
        h += 90
    cite = " · ".join(x for x in (study.get("short_citation"), study.get("year"), study.get("journal")) if x)
    cpx = fit_px(cite, inner, 26, 26, 2, bold=False)
    h += 24 + lines(cite, cpx, inner, False) * cpx * 1.3 + pad
    color = t.colors["evidence"]["systematic_review"] if study["kind_label"] == "REVIEW" else t.colors["evidence"]["rct"]
    outcome_icon = "equal" if study.get("null_result") else ("shield-check" if "adverse" in (study.get("outcome") or "") else "trending-up")
    markers = " ".join("[%d]" % m for m in study.get("markers", []))
    html = f"""<div class="bx sf" id="{bid}">
  <div class="sf-top"><span class="sf-kind" style="background:{color}"><span class="ic">{icon_svg('microscope')}</span>{esc(study['kind_label'])}</span>
  <span class="sf-badge ic" id="{bid}-badge">{icon_svg(outcome_icon)}</span><span class="sf-mark">{esc(markers)}</span></div>
  {'<div class="sf-title" style="font-size:%dpx">%s</div>' % (tpx, esc(title)) if title else ''}
  {'<div class="sf-find" style="font-size:%dpx">%s</div>' % (fpx, esc(finding)) if finding else ''}
  {extra_html}
  <div class="sf-cite" style="font-size:{cpx}px">{esc(cite)}</div></div>"""
    css = f"""
#{bid} {{ width:{width:.0f}px; box-sizing:border-box; padding:{pad}px; border-radius:30px; background:{t.card};
  box-shadow:0 30px 80px rgba(11,31,51,.20); border-top:10px solid {color}; }}
#{bid} .sf-top {{ display:flex; align-items:center; gap:16px; height:40px; }}
#{bid} .sf-kind {{ display:inline-flex; align-items:center; gap:10px; color:#fff; font-size:24px; font-weight:700;
  letter-spacing:.1em; padding:6px 16px; border-radius:10px; }}
#{bid} .sf-kind .ic {{ width:26px; height:26px; }}
#{bid} .sf-badge {{ width:40px; height:40px; color:{t.colors['status']['warn'] if study.get('null_result') else t.colors['status']['ok']}; }}
#{bid} .sf-mark {{ margin-left:auto; font-size:26px; font-weight:700; color:{t.muted}; }}
#{bid} .sf-title {{ margin-top:16px; font-weight:700; color:{t.navy}; line-height:1.2; }}
#{bid} .sf-title::first-letter {{ text-transform:uppercase; }}
#{bid} .sf-find {{ margin-top:10px; color:{t.text}; font-weight:500; line-height:1.3; }}
#{bid} .sf-chips {{ display:flex; flex-wrap:wrap; gap:14px; margin-top:22px; }}
#{bid} .sf-chip {{ display:inline-flex; align-items:center; gap:10px; font-size:28px; font-weight:600; color:{t.navy};
  background:{t.page}; border-radius:999px; padding:10px 20px; }}
#{bid} .sf-chip .ic {{ width:30px; height:30px; color:{t.accent}; }}
#{bid} .sf-turn {{ margin-top:18px; display:flex; gap:14px; align-items:center; padding:12px 22px; border-radius:16px;
  background:#FFF4E0; border-left:6px solid {t.colors['status']['warn']}; }}
#{bid} .sf-turn .ic {{ width:38px; height:38px; color:{t.colors['status']['warn']}; }}
#{bid} .sf-turn em {{ font-style:normal; font-size:24px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:{t.colors['status']['warn']}; }}
#{bid} .sf-turn b {{ font-weight:600; color:{t.text}; line-height:1.3; }}
#{bid} .sf-cite {{ margin-top:24px; padding-top:18px; border-top:2px solid {t.rule}; color:{t.muted}; line-height:1.3; }}{extra_css}"""

    def anim(at: float, times: Sequence[float]) -> List[str]:
        out = [from_to(f"#{bid}", {"opacity": 0, "scale": 0.92, "y": 30},
                       {"opacity": 1, "scale": 1, "y": 0, "duration": t.duration("sceneIn"), "ease": t.ease("entrance")}, at),
               _pop(t, f"#{bid}-badge", at + 0.8)]
        if spec.get("kind") == "time_points":
            out.append(from_to(f"#{bid}-tsl", {"scaleX": 0}, {"scaleX": 1, "duration": 1.2, "ease": "none"}, at + 0.6))
            for k in range(len(spec["points"])):
                tk = times[k] if k < len(times) else at + 0.8 + k
                out.append(_enter(t, f"#{bid}-t{k}", tk, 12))
        elif spec.get("kind") in ("enumeration", "wavelengths"):
            n = len(spec["items"]) if spec["kind"] == "enumeration" else sum(len(m["values"]) for m in spec["marks"])
            for k in range(n):
                tk = times[k] if k < len(times) else at + 0.9 + 0.3 * k
                out.append(_pop(t, f"#{bid}-k{k}", tk))
        elif spec.get("kind") == "contrast":
            out.append(_enter(t, f"#{bid}-turn", at + 2.2, 12))
        return out

    if h > max_h and _shrink < 4:
        return study_focus(t, bid, study, width, max_h, _shrink + 1)
    return Box(bid, width, h, html, css, anim, "study_focus")


def study_mini(t: Tokens, bid: str, study: Dict[str, Any], width: float, height: float) -> Box:
    inner = width - 40
    title = study.get("title") or study.get("short_citation") or ""
    tpx = fit_px(title, inner, 30, 26, 2)
    outcome = study.get("outcome") or ""
    opx = 26
    cite = " · ".join(x for x in (study.get("short_citation"), study.get("year")) if x)
    cite_h = lines(cite, 26, inner, False) * 26 * 1.25
    room = height - 36 - 30 - lines(title, tpx, inner) * tpx * 1.2 - cite_h - 3 * 8
    show_outcome = bool(outcome) and lines(outcome, opx, inner - 44, False) * opx * 1.25 <= room
    color = t.colors["evidence"]["systematic_review"] if study["kind_label"] == "REVIEW" else t.colors["evidence"]["rct"]
    tone = t.colors["status"]["warn"] if study.get("null_result") else t.colors["status"]["ok"]
    icon = "equal" if study.get("null_result") else ("shield-check" if "adverse" in outcome else "trending-up")
    markers = " ".join("[%d]" % m for m in study.get("markers", []))
    html = f"""<div class="bx sm" id="{bid}">
  <div class="sm-top"><span class="sm-kind" style="color:{color}">{esc(study['kind_label'])}</span><span class="sm-mark">{esc(markers)}</span></div>
  <div class="sm-title" style="font-size:{tpx}px">{esc(title)}</div>
  {'<div class="sm-out"><span class="ic" style="color:%s">%s</span><span>%s</span></div>' % (tone, icon_svg(icon), esc(outcome)) if show_outcome else ''}
  <div class="sm-cite">{esc(cite)}</div></div>"""
    css = f"""
#{bid} {{ width:{width:.0f}px; height:{height:.0f}px; box-sizing:border-box; padding:18px 20px; border-radius:22px;
  background:{t.card}; box-shadow:0 12px 30px rgba(11,31,51,.12); border-left:8px solid {color};
  display:flex; flex-direction:column; gap:8px; overflow:hidden; }}
#{bid} .sm-top {{ display:flex; justify-content:space-between; font-size:22px; font-weight:700; letter-spacing:.1em; }}
#{bid} .sm-mark {{ color:{t.muted}; letter-spacing:0; }}
#{bid} .sm-title {{ font-weight:700; color:{t.navy}; line-height:1.2; }}
#{bid} .sm-title::first-letter {{ text-transform:uppercase; }}
#{bid} .sm-out {{ display:flex; gap:10px; align-items:flex-start; font-size:{opx}px; line-height:1.25; color:{t.text}; }}
#{bid} .sm-out .ic {{ width:32px; height:32px; margin-top:2px; }}
#{bid} .sm-cite {{ margin-top:auto; font-size:26px; line-height:1.25; color:{t.muted}; }}"""
    return Box(bid, width, height, html, css, lambda a, b: [], "study_mini")


def subtitle(t: Tokens, bid: str, text: str, icon: str, width: float) -> Box:
    px = fit_px(text, width - 70, 34, 28, 1)
    html = f"""<div class="bx sb" id="{bid}"><span class="ic">{icon_svg(icon)}</span><span>{esc(text)}</span></div>"""
    css = f"""
#{bid} {{ display:flex; gap:14px; align-items:center; font-size:{px}px; font-weight:600; color:{t.colors['status']['warn']}; }}
#{bid} .ic {{ width:40px; height:40px; }}"""

    def anim(at: float, _t: Sequence[float]) -> List[str]:
        return [_enter(t, f"#{bid}", at, 10)]

    return Box(bid, width, 48, html, css, anim, "subtitle")
