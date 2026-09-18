"""The GymRamp motion component library.

Each component returns HTML for one timed clip plus the GSAP timeline lines that
animate it. They are the only things allowed to draw on a frame, which is what
keeps every course looking like the same product instead of fifteen one-off
designs.

Three rules the whole library obeys:

* **No brand value is written here.** Colour, type, spacing and motion all come
  from video-production/brand/*.json via `Tokens`. Changing the accent colour is
  one edit in one file, not a search across components.
* **Entry animation only, and only where it means something.** A card appears; it
  does not then drift, pulse or loop. Continuous motion behind text is the
  cheapest way to look generated.
* **Text is content, not decoration.** Every string a component renders comes
  from approved course text or the computed reference list. Components escape
  everything: a source title containing "<" must not be able to break the frame.

HyperFrames contract (docs/reference/html-schema.mdx): a clip is an element with
`class="clip"`, `data-start`, `data-duration`; paint order is CSS `z-index`;
animations must be seekable, so everything is registered on one paused GSAP
timeline that the renderer scrubs frame by frame.
"""

from __future__ import annotations

import html
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

BRAND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "brand")


class Tokens:
    """Brand tokens, loaded once and shared by every component."""

    def __init__(self, brand_dir: str = BRAND_DIR):
        def load(name: str) -> Dict[str, Any]:
            with open(os.path.join(brand_dir, name), encoding="utf-8") as fh:
                return json.load(fh)

        self.colors = load("colors.json")
        self.type = load("typography.json")
        self.space = load("spacing.json")
        self.motion = load("motion.json")

    # -- colour -----------------------------------------------------------
    @property
    def navy(self) -> str: return self.colors["ink"]["navy"]
    @property
    def text(self) -> str: return self.colors["ink"]["text"]
    @property
    def muted(self) -> str: return self.colors["ink"]["muted"]
    @property
    def accent(self) -> str: return self.colors["accent"]["primary"]
    @property
    def accent_soft(self) -> str: return self.colors["accent"]["primarySoft"]
    @property
    def page(self) -> str: return self.colors["surface"]["page"]
    @property
    def card(self) -> str: return self.colors["surface"]["card"]
    @property
    def rule(self) -> str: return self.colors["surface"]["rule"]

    def evidence_color(self, design: str) -> str:
        return self.colors["evidence"].get((design or "").lower(), self.colors["evidence"]["unassessed"])

    # -- type -------------------------------------------------------------
    def font(self, role: str = "display") -> str:
        return self.type["family"][role]

    def size(self, name: str) -> Dict[str, Any]:
        return self.type["scale"][name]

    def css_type(self, name: str) -> str:
        s = self.size(name)
        bits = ["font-size:%dpx" % s["size"], "font-weight:%d" % s["weight"],
                "line-height:%s" % s.get("lineHeight", 1.3)]
        if s.get("tracking"):
            bits.append("letter-spacing:%s" % s["tracking"])
        if s.get("transform"):
            bits.append("text-transform:%s" % s["transform"])
        return ";".join(bits)

    # -- motion -----------------------------------------------------------
    def ease(self, name: str) -> str:
        """GSAP understands CSS cubic-bezier through its own string form."""
        raw = self.motion["easing"].get(name, self.motion["easing"]["standard"])
        inner = raw[raw.find("(") + 1:raw.rfind(")")]
        return "cubic-bezier(%s)" % inner.replace(" ", "")

    def duration(self, name: str) -> float:
        return float(self.motion["duration"].get(name, self.motion["duration"]["base"]))


def esc(value: Any) -> str:
    """Escape anything bound for the frame. Source titles are not trusted markup."""
    return html.escape("" if value is None else str(value), quote=True)


@dataclass
class Clip:
    """One rendered component: its markup, its CSS, and its timeline lines."""

    html: str
    css: str
    timeline: List[str]


def _clip_open(clip_id: str, start: float, duration: float, z: int, extra_class: str = "") -> str:
    return ('<section id="%s" class="clip %s" data-start="%.3f" data-duration="%.3f" '
            'data-track-index="1" style="z-index:%d">') % (clip_id, extra_class, start, duration, z)


# ---------------------------------------------------------------- components ---

def title_reveal(t: Tokens, clip_id: str, start: float, duration: float, *,
                 title: str, subtitle: str = "", eyebrow: str = "GYMRAMP", z: int = 10) -> Clip:
    """Opening identity: who made this and what it is. One entrance, then it holds."""
    body = f"""
  <div class="tr-wrap">
    <div class="tr-eyebrow" id="{clip_id}-eyebrow">{esc(eyebrow)}</div>
    <h1 class="tr-title" id="{clip_id}-title">{esc(title)}</h1>
    {'<p class="tr-sub" id="%s-sub">%s</p>' % (clip_id, esc(subtitle)) if subtitle else ''}
    <div class="tr-rule" id="{clip_id}-rule"></div>
  </div>"""
    css = f"""
#{clip_id} {{ background:{t.navy}; display:grid; place-items:center; }}
#{clip_id} .tr-wrap {{ width:1400px; text-align:left; }}
#{clip_id} .tr-eyebrow {{ {t.css_type('label')}; color:{t.accent}; margin-bottom:24px; }}
#{clip_id} .tr-title {{ {t.css_type('courseTitle')}; color:#fff; margin:0; }}
#{clip_id} .tr-sub {{ {t.css_type('lead')}; color:rgba(255,255,255,.72); margin:24px 0 0; }}
#{clip_id} .tr-rule {{ height:6px; width:220px; background:{t.accent}; margin-top:40px; border-radius:3px; }}"""
    tl = [
        f"tl.from('#{clip_id}-eyebrow', {{opacity:0, y:16, duration:{t.duration('quick')}, ease:'{t.ease('entrance')}'}}, {start:.3f});",
        f"tl.from('#{clip_id}-title', {{opacity:0, y:36, duration:{t.duration('sceneIn')}, ease:'{t.ease('entrance')}'}}, {start + 0.12:.3f});",
        f"tl.from('#{clip_id}-rule', {{scaleX:0, transformOrigin:'left center', duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start + 0.35:.3f});",
    ]
    if subtitle:
        tl.append(f"tl.from('#{clip_id}-sub', {{opacity:0, y:20, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start + 0.28:.3f});")
    return Clip(_clip_open(clip_id, start, duration, z) + body + "</section>", css, tl)


def section_intro(t: Tokens, clip_id: str, start: float, duration: float, *,
                  title: str, eyebrow: str = "", index: Optional[int] = None, z: int = 10) -> Clip:
    """Marks a turn in the lesson. Used at section boundaries only."""
    num = f'<span class="si-num">{index:02d}</span>' if index else ""
    body = f"""
  <div class="si-wrap">
    {num}
    <div>
      {'<div class="si-eyebrow">%s</div>' % esc(eyebrow) if eyebrow else ''}
      <h2 class="si-title" id="{clip_id}-title">{esc(title)}</h2>
    </div>
  </div>"""
    css = f"""
#{clip_id} {{ background:{t.page}; display:grid; place-items:center; }}
#{clip_id} .si-wrap {{ display:flex; gap:40px; align-items:center; width:1400px; }}
#{clip_id} .si-num {{ {t.css_type('sectionTitle')}; color:{t.accent}; opacity:.35; }}
#{clip_id} .si-eyebrow {{ {t.css_type('label')}; color:{t.muted}; margin-bottom:12px; }}
#{clip_id} .si-title {{ {t.css_type('sectionTitle')}; color:{t.navy}; margin:0; }}"""
    tl = [
        f"tl.from('#{clip_id} .si-wrap', {{opacity:0, y:28, duration:{t.duration('sceneIn')}, ease:'{t.ease('entrance')}'}}, {start:.3f});",
    ]
    return Clip(_clip_open(clip_id, start, duration, z) + body + "</section>", css, tl)


def keyword_highlight(t: Tokens, clip_id: str, start: float, duration: float, *,
                      term: str, definition: str = "", z: int = 10) -> Clip:
    """The term being taught, with its definition underneath. Never the whole sentence."""
    body = f"""
  <div class="kh-wrap">
    <div class="kh-term" id="{clip_id}-term"><span class="kh-mark"></span><span>{esc(term)}</span></div>
    {'<p class="kh-def" id="%s-def">%s</p>' % (clip_id, esc(definition)) if definition else ''}
  </div>"""
    css = f"""
#{clip_id} {{ background:{t.page}; display:grid; place-items:center; }}
#{clip_id} .kh-wrap {{ width:1300px; }}
#{clip_id} .kh-term {{ position:relative; display:inline-block; {t.css_type('sectionTitle')}; color:{t.navy}; }}
#{clip_id} .kh-mark {{ position:absolute; left:-12px; right:-12px; bottom:6px; height:26px;
  background:{t.accent_soft}; transform-origin:left center; z-index:-1; border-radius:4px; }}
#{clip_id} .kh-def {{ {t.css_type('lead')}; color:{t.muted}; margin:32px 0 0; max-width:1100px; }}"""
    tl = [
        f"tl.from('#{clip_id}-term', {{opacity:0, y:20, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start:.3f});",
        f"tl.from('#{clip_id} .kh-mark', {{scaleX:0, duration:{t.duration('quick')}, ease:'{t.ease('emphasis')}'}}, {start + 0.3:.3f});",
    ]
    if definition:
        tl.append(f"tl.from('#{clip_id}-def', {{opacity:0, y:16, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start + 0.35:.3f});")
    return Clip(_clip_open(clip_id, start, duration, z) + body + "</section>", css, tl)


def evidence_card(t: Tokens, clip_id: str, start: float, duration: float, *,
                  finding: str, citation: str, design: str = "", year: Optional[int] = None,
                  journal: str = "", population: str = "", outcome: str = "",
                  statistic: Optional[str] = None, marker: Optional[int] = None, z: int = 10) -> Clip:
    """A cited finding.

    The finding is the headline; the source sits under it in small type. That order
    is deliberate — a viewer should understand *what was found* before reading who
    found it, and a wall of bibliography teaches nobody.
    """
    design_label = (design or "study").replace("_", " ")
    meta_bits = [b for b in (journal, str(year) if year else "", population) if b]
    stat_html = f'<div class="ec-stat" id="{clip_id}-stat">{esc(statistic)}</div>' if statistic else ""
    body = f"""
  <div class="ec-card" id="{clip_id}-card">
    <div class="ec-head">
      <span class="ec-badge">{esc(design_label)}</span>
      {'<span class="ec-marker">[%d]</span>' % marker if marker else ''}
    </div>
    {stat_html}
    <p class="ec-finding" id="{clip_id}-finding">{esc(finding)}</p>
    {'<p class="ec-outcome">%s</p>' % esc(outcome) if outcome else ''}
    <div class="ec-source">
      <div class="ec-meta">{esc(' · '.join(meta_bits))}</div>
      <div class="ec-citation">{esc(citation)}</div>
    </div>
  </div>"""
    css = f"""
#{clip_id} {{ background:{t.page}; display:grid; place-items:center; }}
#{clip_id} .ec-card {{ width:1280px; background:{t.card}; border-radius:{t.space['card']['radius']}px;
  padding:{t.space['card']['padding']}px; box-shadow:{t.space['card']['shadow']};
  border-left:10px solid {t.evidence_color(design)}; }}
#{clip_id} .ec-head {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:28px; }}
#{clip_id} .ec-badge {{ {t.css_type('label')}; color:{t.evidence_color(design)}; }}
#{clip_id} .ec-marker {{ {t.css_type('label')}; color:{t.muted}; }}
#{clip_id} .ec-stat {{ {t.css_type('statistic')}; color:{t.navy}; margin-bottom:8px; }}
#{clip_id} .ec-finding {{ {t.css_type('cardTitle')}; color:{t.text}; margin:0; }}
#{clip_id} .ec-outcome {{ {t.css_type('body')}; color:{t.muted}; margin:20px 0 0; }}
#{clip_id} .ec-source {{ margin-top:36px; padding-top:24px; border-top:2px solid {t.rule}; }}
#{clip_id} .ec-meta {{ {t.css_type('label')}; color:{t.muted}; margin-bottom:8px; }}
#{clip_id} .ec-citation {{ {t.css_type('citation')}; color:{t.muted}; }}"""
    tl = [
        f"tl.from('#{clip_id}-card', {{opacity:0, y:32, duration:{t.duration('sceneIn')}, ease:'{t.ease('entrance')}'}}, {start:.3f});",
        f"tl.from('#{clip_id} .ec-source', {{opacity:0, duration:{t.duration('base')}, ease:'{t.ease('standard')}'}}, {start + 0.45:.3f});",
    ]
    if statistic:
        tl.append(f"tl.from('#{clip_id}-stat', {{opacity:0, scale:.92, transformOrigin:'left center', duration:{t.duration('base')}, ease:'{t.ease('emphasis')}'}}, {start + 0.25:.3f});")
    return Clip(_clip_open(clip_id, start, duration, z) + body + "</section>", css, tl)


def statistic_card(t: Tokens, clip_id: str, start: float, duration: float, *,
                   value: str, label: str = "", context: str = "", z: int = 10) -> Clip:
    """A number the viewer should be able to read, with what it measures."""
    body = f"""
  <div class="sc-wrap">
    <div class="sc-value" id="{clip_id}-value">{esc(value)}</div>
    {'<div class="sc-label" id="%s-label">%s</div>' % (clip_id, esc(label)) if label else ''}
    {'<div class="sc-context">%s</div>' % esc(context) if context else ''}
  </div>"""
    css = f"""
#{clip_id} {{ background:{t.navy}; display:grid; place-items:center; }}
#{clip_id} .sc-wrap {{ width:1300px; text-align:center; }}
#{clip_id} .sc-value {{ {t.css_type('statistic')}; color:{t.accent}; }}
#{clip_id} .sc-label {{ {t.css_type('lead')}; color:#fff; margin-top:16px; }}
#{clip_id} .sc-context {{ {t.css_type('label')}; color:rgba(255,255,255,.55); margin-top:28px; }}"""
    tl = [
        f"tl.from('#{clip_id}-value', {{opacity:0, y:24, scale:.94, duration:{t.duration('base')}, ease:'{t.ease('emphasis')}'}}, {start:.3f});",
    ]
    if label:
        tl.append(f"tl.from('#{clip_id}-label', {{opacity:0, y:14, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start + 0.22:.3f});")
    return Clip(_clip_open(clip_id, start, duration, z) + body + "</section>", css, tl)


def comparison_card(t: Tokens, clip_id: str, start: float, duration: float, *,
                    left: str, right: str, left_label: str = "", right_label: str = "", z: int = 10) -> Clip:
    """Two things side by side, because that is what the sentence is doing."""
    body = f"""
  <div class="cc-wrap">
    <div class="cc-side" id="{clip_id}-left">
      {'<div class="cc-label">%s</div>' % esc(left_label) if left_label else ''}
      <p>{esc(left)}</p>
    </div>
    <div class="cc-vs" id="{clip_id}-vs">vs</div>
    <div class="cc-side cc-right" id="{clip_id}-right">
      {'<div class="cc-label">%s</div>' % esc(right_label) if right_label else ''}
      <p>{esc(right)}</p>
    </div>
  </div>"""
    css = f"""
#{clip_id} {{ background:{t.page}; display:grid; place-items:center; }}
#{clip_id} .cc-wrap {{ display:flex; align-items:center; gap:32px; width:1500px; }}
#{clip_id} .cc-side {{ flex:1; background:{t.card}; border-radius:{t.space['card']['radius']}px;
  padding:44px; box-shadow:{t.space['card']['shadow']}; border-top:8px solid {t.navy}; }}
#{clip_id} .cc-right {{ border-top-color:{t.accent}; }}
#{clip_id} .cc-side p {{ {t.css_type('cardTitle')}; color:{t.text}; margin:0; }}
#{clip_id} .cc-label {{ {t.css_type('label')}; color:{t.muted}; margin-bottom:16px; }}
#{clip_id} .cc-vs {{ {t.css_type('label')}; color:{t.muted}; }}"""
    tl = [
        f"tl.from('#{clip_id}-left', {{opacity:0, x:-28, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start:.3f});",
        f"tl.from('#{clip_id}-vs', {{opacity:0, duration:{t.duration('quick')}}}, {start + 0.24:.3f});",
        f"tl.from('#{clip_id}-right', {{opacity:0, x:28, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start + 0.3:.3f});",
    ]
    return Clip(_clip_open(clip_id, start, duration, z) + body + "</section>", css, tl)


def process_flow(t: Tokens, clip_id: str, start: float, duration: float, *,
                 steps: Sequence[str], title: str = "", z: int = 10) -> Clip:
    """A sequence, drawn in order, at the pace the narration describes it."""
    items = "".join(
        f'<div class="pf-step" id="{clip_id}-step{i}"><span class="pf-num">{i + 1}</span>'
        f'<span class="pf-text">{esc(s)}</span></div>'
        + (f'<div class="pf-arrow" id="{clip_id}-arrow{i}"></div>' if i < len(steps) - 1 else "")
        for i, s in enumerate(steps))
    body = f"""
  <div class="pf-wrap">
    {'<div class="pf-title">%s</div>' % esc(title) if title else ''}
    <div class="pf-row">{items}</div>
  </div>"""
    css = f"""
#{clip_id} {{ background:{t.page}; display:grid; place-items:center; }}
#{clip_id} .pf-wrap {{ width:1600px; }}
#{clip_id} .pf-title {{ {t.css_type('label')}; color:{t.muted}; margin-bottom:36px; text-align:center; }}
#{clip_id} .pf-row {{ display:flex; align-items:stretch; justify-content:center; gap:20px; }}
#{clip_id} .pf-step {{ flex:1; max-width:360px; background:{t.card}; border-radius:{t.space['card']['radius']}px;
  padding:36px; box-shadow:{t.space['card']['shadow']}; display:flex; flex-direction:column; gap:20px; }}
#{clip_id} .pf-num {{ width:56px; height:56px; border-radius:50%; background:{t.accent}; color:#fff;
  {t.css_type('label')}; display:grid; place-items:center; }}
#{clip_id} .pf-text {{ {t.css_type('body')}; color:{t.text}; }}
#{clip_id} .pf-arrow {{ align-self:center; width:44px; height:4px; background:{t.rule}; border-radius:2px;
  transform-origin:left center; }}"""
    tl = []
    for i in range(len(steps)):
        at = start + 0.18 * i
        tl.append(f"tl.from('#{clip_id}-step{i}', {{opacity:0, y:22, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {at:.3f});")
        if i < len(steps) - 1:
            tl.append(f"tl.from('#{clip_id}-arrow{i}', {{scaleX:0, duration:{t.duration('quick')}, ease:'{t.ease('standard')}'}}, {at + 0.12:.3f});")
    return Clip(_clip_open(clip_id, start, duration, z) + body + "</section>", css, tl)


def recap(t: Tokens, clip_id: str, start: float, duration: float, *,
          items: Sequence[str], title: str = "Key takeaways", z: int = 10) -> Clip:
    """The summary, all visible at once so it can be read as a whole."""
    lis = "".join(f'<li id="{clip_id}-item{i}"><span class="rc-tick"></span>{esc(s)}</li>'
                  for i, s in enumerate(items))
    body = f"""
  <div class="rc-wrap">
    <h2 class="rc-title" id="{clip_id}-title">{esc(title)}</h2>
    <ul class="rc-list">{lis}</ul>
  </div>"""
    css = f"""
#{clip_id} {{ background:{t.navy}; display:grid; place-items:center; }}
#{clip_id} .rc-wrap {{ width:1400px; }}
#{clip_id} .rc-title {{ {t.css_type('sectionTitle')}; color:#fff; margin:0 0 48px; }}
#{clip_id} .rc-list {{ list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:28px; }}
#{clip_id} .rc-list li {{ {t.css_type('lead')}; color:rgba(255,255,255,.92); display:flex; gap:24px; align-items:flex-start; }}
#{clip_id} .rc-tick {{ flex:none; width:18px; height:18px; margin-top:16px; border-radius:4px; background:{t.accent}; }}"""
    tl = [f"tl.from('#{clip_id}-title', {{opacity:0, y:24, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start:.3f});"]
    for i in range(len(items)):
        tl.append(f"tl.from('#{clip_id}-item{i}', {{opacity:0, x:-20, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start + 0.25 + 0.14 * i:.3f});")
    return Clip(_clip_open(clip_id, start, duration, z) + body + "</section>", css, tl)


def outro(t: Tokens, clip_id: str, start: float, duration: float, *,
          title: str, message: str = "", course_code: str = "", z: int = 10) -> Clip:
    """Course identity and the next step. No sell, no music sting."""
    body = f"""
  <div class="ou-wrap">
    <div class="ou-brand">GYMRAMP</div>
    <h2 class="ou-title" id="{clip_id}-title">{esc(title)}</h2>
    {'<p class="ou-msg">%s</p>' % esc(message) if message else ''}
    {'<div class="ou-code">%s</div>' % esc(course_code) if course_code else ''}
  </div>"""
    css = f"""
#{clip_id} {{ background:{t.navy}; display:grid; place-items:center; }}
#{clip_id} .ou-wrap {{ width:1300px; text-align:center; }}
#{clip_id} .ou-brand {{ {t.css_type('label')}; color:{t.accent}; margin-bottom:28px; }}
#{clip_id} .ou-title {{ {t.css_type('sectionTitle')}; color:#fff; margin:0; }}
#{clip_id} .ou-msg {{ {t.css_type('lead')}; color:rgba(255,255,255,.7); margin:28px 0 0; }}
#{clip_id} .ou-code {{ {t.css_type('label')}; color:rgba(255,255,255,.45); margin-top:40px; }}"""
    tl = [f"tl.from('#{clip_id} .ou-wrap', {{opacity:0, y:24, duration:{t.duration('sceneIn')}, ease:'{t.ease('entrance')}'}}, {start:.3f});"]
    return Clip(_clip_open(clip_id, start, duration, z) + body + "</section>", css, tl)


def quote_card(t: Tokens, clip_id: str, start: float, duration: float, *,
               quote: str, attribution: str = "", z: int = 10) -> Clip:
    body = f"""
  <div class="qc-wrap">
    <div class="qc-mark">&ldquo;</div>
    <blockquote id="{clip_id}-quote">{esc(quote)}</blockquote>
    {'<div class="qc-attr">%s</div>' % esc(attribution) if attribution else ''}
  </div>"""
    css = f"""
#{clip_id} {{ background:{t.page}; display:grid; place-items:center; }}
#{clip_id} .qc-wrap {{ width:1300px; }}
#{clip_id} .qc-mark {{ font-size:140px; line-height:.6; color:{t.accent}; }}
#{clip_id} blockquote {{ {t.css_type('cardTitle')}; color:{t.navy}; margin:24px 0 0; }}
#{clip_id} .qc-attr {{ {t.css_type('citation')}; color:{t.muted}; margin-top:28px; }}"""
    tl = [f"tl.from('#{clip_id} .qc-wrap', {{opacity:0, y:22, duration:{t.duration('sceneIn')}, ease:'{t.ease('entrance')}'}}, {start:.3f});"]
    return Clip(_clip_open(clip_id, start, duration, z) + body + "</section>", css, tl)


def lower_third(t: Tokens, clip_id: str, start: float, duration: float, *,
                primary: str, secondary: str = "", z: int = 30) -> Clip:
    """Face template: a name or term strip, placed clear of the face and the captions."""
    s = t.space["lowerThird"]
    body = f"""
  <div class="lt-card" id="{clip_id}-card">
    <div class="lt-bar"></div>
    <div>
      <div class="lt-primary">{esc(primary)}</div>
      {'<div class="lt-secondary">%s</div>' % esc(secondary) if secondary else ''}
    </div>
  </div>"""
    css = f"""
#{clip_id} {{ background:transparent; }}
#{clip_id} .lt-card {{ position:absolute; left:{s['x']}px; top:{s['y']}px; max-width:{s['maxWidth']}px;
  display:flex; gap:20px; align-items:center; background:rgba(11,31,51,.92); color:#fff;
  padding:{s['padding']}px; border-radius:{s['radius']}px; backdrop-filter:blur(6px); }}
#{clip_id} .lt-bar {{ width:6px; align-self:stretch; background:{t.accent}; border-radius:3px; }}
#{clip_id} .lt-primary {{ {t.css_type('cardTitle')}; }}
#{clip_id} .lt-secondary {{ {t.css_type('citation')}; color:rgba(255,255,255,.7); margin-top:6px; }}"""
    tl = [
        f"tl.from('#{clip_id}-card', {{opacity:0, x:-32, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start:.3f});",
        f"tl.to('#{clip_id}-card', {{opacity:0, duration:{t.duration('quick')}, ease:'{t.ease('exit')}'}}, {start + duration - 0.35:.3f});",
    ]
    return Clip(_clip_open(clip_id, start, duration, z, "overlay") + body + "</section>", css, tl)


def side_panel_evidence(t: Tokens, clip_id: str, start: float, duration: float, *,
                        finding: str, citation: str, design: str = "", side: str = "right", z: int = 30) -> Clip:
    """Face template: evidence beside the presenter, never over them."""
    s = t.space["sidePanel"]
    pos = "right:120px" if side == "right" else "left:120px"
    body = f"""
  <aside class="sp-card" id="{clip_id}-card">
    <div class="sp-badge">{esc((design or 'evidence').replace('_', ' '))}</div>
    <p class="sp-finding">{esc(finding)}</p>
    <div class="sp-citation">{esc(citation)}</div>
  </aside>"""
    css = f"""
#{clip_id} {{ background:transparent; }}
#{clip_id} .sp-card {{ position:absolute; {pos}; top:180px; width:{s['width']}px; padding:{s['padding']}px;
  background:{t.card}; border-radius:{s['radius']}px; box-shadow:{t.space['card']['shadow']};
  border-top:8px solid {t.evidence_color(design)}; }}
#{clip_id} .sp-badge {{ {t.css_type('label')}; color:{t.evidence_color(design)}; margin-bottom:20px; }}
#{clip_id} .sp-finding {{ {t.css_type('body')}; color:{t.text}; margin:0; }}
#{clip_id} .sp-citation {{ {t.css_type('citation')}; color:{t.muted}; margin-top:24px;
  padding-top:18px; border-top:2px solid {t.rule}; }}"""
    tl = [
        f"tl.from('#{clip_id}-card', {{opacity:0, x:{28 if side == 'right' else -28}, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start:.3f});",
        f"tl.to('#{clip_id}-card', {{opacity:0, duration:{t.duration('quick')}, ease:'{t.ease('exit')}'}}, {start + duration - 0.35:.3f});",
    ]
    return Clip(_clip_open(clip_id, start, duration, z, "overlay") + body + "</section>", css, tl)


def source_citation(t: Tokens, clip_id: str, start: float, duration: float, *,
                    citation: str, marker: Optional[int] = None, z: int = 30) -> Clip:
    """A compact source line, for when the finding is already on screen."""
    body = f"""<div class="sr-line" id="{clip_id}-line">{'[%d] ' % marker if marker else ''}{esc(citation)}</div>"""
    css = f"""
#{clip_id} {{ background:transparent; }}
#{clip_id} .sr-line {{ position:absolute; left:120px; bottom:300px; max-width:1200px;
  {t.css_type('citation')}; color:{t.muted}; background:rgba(255,255,255,.92);
  padding:14px 22px; border-radius:12px; border-left:4px solid {t.accent}; }}"""
    tl = [
        f"tl.from('#{clip_id}-line', {{opacity:0, y:10, duration:{t.duration('quick')}, ease:'{t.ease('entrance')}'}}, {start:.3f});",
        f"tl.to('#{clip_id}-line', {{opacity:0, duration:{t.duration('quick')}}}, {start + duration - 0.3:.3f});",
    ]
    return Clip(_clip_open(clip_id, start, duration, z, "overlay") + body + "</section>", css, tl)


def key_takeaway(t: Tokens, clip_id: str, start: float, duration: float, *,
                 text: str, variant: str = "banner", z: int = 30) -> Clip:
    """One line worth remembering.

    Three layouts, same words. `banner` is an overlay for the presenter template, where
    the frame is already full. On the faceless page a banner leaves most of the screen
    empty, so there the line is either a `statement` (centred, large) or a `panel`
    (left-weighted card); consecutive cards alternate so they never look like a loop.
    """
    if variant not in ("banner", "statement", "panel"):
        raise ValueError("unknown key_takeaway variant %r" % variant)
    safe = t.space["safeArea"]
    cz = t.space["captionZone"]
    if variant == "banner":
        body = f"""<div class="kt-card" id="{clip_id}-card"><span class="kt-bar"></span>{esc(text)}</div>"""
        css = f"""
#{clip_id} {{ background:transparent; }}
#{clip_id} .kt-card {{ position:absolute; left:50%; transform:translateX(-50%); top:120px; max-width:1400px;
  display:flex; gap:20px; align-items:center; {t.css_type('cardTitle')}; color:{t.navy};
  background:rgba(255,255,255,.95); padding:28px 40px; border-radius:20px; box-shadow:{t.space['card']['shadow']}; }}
#{clip_id} .kt-bar {{ width:6px; align-self:stretch; background:{t.accent}; border-radius:3px; }}"""
        enter = f"tl.from('#{clip_id}-card', {{opacity:0, y:-18, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start:.3f});"
    elif variant == "statement":
        body = f"""
  <div class="kt-stage" id="{clip_id}-card">
    <div class="kt-text">{esc(text)}</div>
    <div class="kt-rule" id="{clip_id}-rule"></div>
  </div>"""
        css = f"""
#{clip_id} {{ background:{t.page}; }}
#{clip_id} .kt-stage {{ position:absolute; left:{safe['left']}px; right:{safe['right']}px; top:{safe['top']}px;
  bottom:{cz['bottom'] + cz['height']}px; display:flex; flex-direction:column; justify-content:center;
  align-items:center; text-align:center; }}
#{clip_id} .kt-text {{ {t.css_type('sectionTitle')}; color:{t.navy}; max-width:1440px; text-wrap:balance; }}
#{clip_id} .kt-rule {{ width:120px; height:6px; margin-top:40px; background:{t.accent}; border-radius:3px;
  transform-origin:center; }}"""
        enter = (f"tl.from('#{clip_id}-card', {{opacity:0, y:24, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start:.3f});"
                 f" tl.from('#{clip_id}-rule', {{scaleX:0, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start + 0.2:.3f});")
    else:  # panel
        body = f"""
  <div class="kt-panel" id="{clip_id}-card">
    <span class="kt-bar" id="{clip_id}-bar"></span>
    <div class="kt-text">{esc(text)}</div>
  </div>"""
        css = f"""
#{clip_id} {{ background:{t.page}; }}
#{clip_id} .kt-panel {{ position:absolute; left:{safe['left']}px; width:1180px;
  top:{safe['top']}px; bottom:{cz['bottom'] + cz['height']}px; display:flex; gap:40px; align-items:center; }}
#{clip_id} .kt-bar {{ width:10px; align-self:stretch; margin:120px 0; background:{t.accent}; border-radius:5px;
  transform-origin:top center; }}
#{clip_id} .kt-text {{ {t.css_type('sectionTitle')}; color:{t.navy}; text-wrap:balance; }}"""
        enter = (f"tl.from('#{clip_id}-bar', {{scaleY:0, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start:.3f});"
                 f" tl.from('#{clip_id} .kt-text', {{opacity:0, x:-24, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start + 0.12:.3f});")
    layer = "overlay" if variant == "banner" else "scene"
    tl = [
        enter,
        f"tl.to('#{clip_id}-card', {{opacity:0, duration:{t.duration('quick')}}}, {start + duration - 0.35:.3f});",
    ]
    return Clip(_clip_open(clip_id, start, duration, z, layer) + body + "</section>", css, tl)


def chart_card(t: Tokens, clip_id: str, start: float, duration: float, *,
               bars: Sequence[Tuple[str, float]], title: str = "", unit: str = "", z: int = 10) -> Clip:
    """A small bar chart from real numbers in the course. No chart without data."""
    if not bars:
        raise ValueError("chart_card needs at least one bar; a chart with no data is decoration")
    top = max(v for _, v in bars) or 1.0
    series = t.colors["chart"]["series"]
    cols = "".join(
        f'<div class="ch-col"><div class="ch-val">{esc(("%g" % v) + unit)}</div>'
        f'<div class="ch-bar" id="{clip_id}-bar{i}" style="height:{max(6, (v / top) * 420):.0f}px;'
        f'background:{series[i % len(series)]}"></div>'
        f'<div class="ch-label">{esc(label)}</div></div>'
        for i, (label, v) in enumerate(bars))
    body = f"""
  <div class="ch-wrap">
    {'<div class="ch-title">%s</div>' % esc(title) if title else ''}
    <div class="ch-row">{cols}</div>
  </div>"""
    css = f"""
#{clip_id} {{ background:{t.page}; display:grid; place-items:center; }}
#{clip_id} .ch-wrap {{ width:1300px; }}
#{clip_id} .ch-title {{ {t.css_type('label')}; color:{t.muted}; margin-bottom:40px; text-align:center; }}
#{clip_id} .ch-row {{ display:flex; gap:56px; align-items:flex-end; justify-content:center; }}
#{clip_id} .ch-col {{ display:flex; flex-direction:column; align-items:center; gap:14px; }}
#{clip_id} .ch-val {{ {t.css_type('cardTitle')}; color:{t.navy}; }}
#{clip_id} .ch-bar {{ width:150px; border-radius:12px 12px 0 0; transform-origin:bottom center; }}
#{clip_id} .ch-label {{ {t.css_type('label')}; color:{t.muted}; }}"""
    tl = [f"tl.from('#{clip_id}-bar{i}', {{scaleY:0, duration:{t.duration('slow')}, ease:'{t.ease('entrance')}'}}, {start + 0.12 * i:.3f});"
          for i in range(len(bars))]
    return Clip(_clip_open(clip_id, start, duration, z) + body + "</section>", css, tl)


def timeline_card(t: Tokens, clip_id: str, start: float, duration: float, *,
                  points: Sequence[Tuple[str, str]], title: str = "", z: int = 10) -> Clip:
    """Events in order along a line: when the sentence is about change over time."""
    items = "".join(
        f'<div class="tc-point" id="{clip_id}-pt{i}"><div class="tc-dot"></div>'
        f'<div class="tc-when">{esc(when)}</div><div class="tc-what">{esc(what)}</div></div>'
        for i, (when, what) in enumerate(points))
    body = f"""
  <div class="tc-wrap">
    {'<div class="tc-title">%s</div>' % esc(title) if title else ''}
    <div class="tc-line" id="{clip_id}-line"></div>
    <div class="tc-row">{items}</div>
  </div>"""
    css = f"""
#{clip_id} {{ background:{t.page}; display:grid; place-items:center; }}
#{clip_id} .tc-wrap {{ width:1500px; position:relative; }}
#{clip_id} .tc-title {{ {t.css_type('label')}; color:{t.muted}; margin-bottom:56px; text-align:center; }}
#{clip_id} .tc-line {{ position:absolute; left:0; right:0; top:50%; height:4px; background:{t.rule};
  transform-origin:left center; }}
#{clip_id} .tc-row {{ display:flex; justify-content:space-between; position:relative; }}
#{clip_id} .tc-point {{ width:280px; text-align:center; }}
#{clip_id} .tc-dot {{ width:22px; height:22px; border-radius:50%; background:{t.accent}; margin:0 auto 20px; }}
#{clip_id} .tc-when {{ {t.css_type('label')}; color:{t.navy}; }}
#{clip_id} .tc-what {{ {t.css_type('body')}; color:{t.muted}; margin-top:10px; }}"""
    tl = [f"tl.from('#{clip_id}-line', {{scaleX:0, duration:{t.duration('slow')}, ease:'{t.ease('standard')}'}}, {start:.3f});"]
    for i in range(len(points)):
        tl.append(f"tl.from('#{clip_id}-pt{i}', {{opacity:0, y:18, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start + 0.2 + 0.14 * i:.3f});")
    return Clip(_clip_open(clip_id, start, duration, z) + body + "</section>", css, tl)


def icon_sequence(t: Tokens, clip_id: str, start: float, duration: float, *,
                  items: Sequence[str], title: str = "", z: int = 10) -> Clip:
    """Short parallel items — the one place a simple glyph row beats a sentence."""
    glyphs = "".join(
        f'<div class="is-item" id="{clip_id}-it{i}"><div class="is-dot">{i + 1}</div>'
        f'<div class="is-text">{esc(s)}</div></div>' for i, s in enumerate(items))
    body = f"""
  <div class="is-wrap">
    {'<div class="is-title">%s</div>' % esc(title) if title else ''}
    <div class="is-row">{glyphs}</div>
  </div>"""
    css = f"""
#{clip_id} {{ background:{t.page}; display:grid; place-items:center; }}
#{clip_id} .is-wrap {{ width:1500px; }}
#{clip_id} .is-title {{ {t.css_type('label')}; color:{t.muted}; margin-bottom:48px; text-align:center; }}
#{clip_id} .is-row {{ display:flex; gap:40px; justify-content:center; }}
#{clip_id} .is-item {{ flex:1; max-width:340px; text-align:center; }}
#{clip_id} .is-dot {{ width:96px; height:96px; border-radius:28px; background:{t.card};
  box-shadow:{t.space['card']['shadow']}; color:{t.accent}; {t.css_type('cardTitle')};
  display:grid; place-items:center; margin:0 auto 24px; }}
#{clip_id} .is-text {{ {t.css_type('body')}; color:{t.text}; }}"""
    tl = [f"tl.from('#{clip_id}-it{i}', {{opacity:0, y:20, duration:{t.duration('base')}, ease:'{t.ease('entrance')}'}}, {start + 0.12 * i:.3f});"
          for i in range(len(items))]
    return Clip(_clip_open(clip_id, start, duration, z) + body + "</section>", css, tl)


# Storyboard component name -> builder. The renderer looks components up here, so an
# unknown component fails loudly at build time rather than rendering an empty frame.
REGISTRY = {
    "TitleReveal": title_reveal,
    "SectionIntro": section_intro,
    "KeywordHighlight": keyword_highlight,
    "EvidenceCard": evidence_card,
    "StatisticCard": statistic_card,
    "ComparisonCard": comparison_card,
    "ProcessFlow": process_flow,
    "Timeline": timeline_card,
    "QuoteCard": quote_card,
    "ChartCard": chart_card,
    "LowerThird": lower_third,
    "SourceCitation": source_citation,
    "KeyTakeaway": key_takeaway,
    "Recap": recap,
    "Outro": outro,
    "IconSequence": icon_sequence,
}
