"""
GymRamp course-media worker.

A sidecar the n8n workflow calls over HTTP, because the n8n container has no
python, ffmpeg or package manager (see the repo CLAUDE.md). It turns a
reviewed course package (JSON) into the production assets:

    course.pptx        branded slides + speaker notes on every slide
    course.mp4         one segment per slide: slide image + its narration
    worksheet.docx     student worksheet
    quiz.docx          knowledge-check quiz
    exam.docx          certification exam
    answer-key.docx    answers + rationale + source for quiz and exam
    sources.md         the computed reference list
    package.json       the exact input, kept for traceability

One layout spec (inches on a 13.333 x 7.5 canvas) drives BOTH the PPTX shapes
and the Pillow-drawn PNG frames, so the video shows the same slide the PPTX
contains. There is no LibreOffice in the image, so converting the PPTX to
images is not an option -- drawing from the same data is.

Endpoints
    GET    /health
    GET    /tts/quota
    POST   /courses/render          -> {job_id, status}
    GET    /jobs/{job_id}           -> status, stage, files[]
    GET    /jobs/{job_id}/files/{f} -> download
    DELETE /jobs/{job_id}
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import edge_tts
import httpx
from docx import Document
from docx.shared import Pt, RGBColor
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor as PptxRGB
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu, Inches, Pt as PptxPt
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

JOBS_ROOT = Path(os.environ.get("JOBS_ROOT", "/data/course-jobs"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8100").rstrip("/")

TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "elevenlabs").strip().lower()
TTS_VOICE = os.environ.get("TTS_VOICE", "en-US-AriaNeural")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb").strip()
ELEVENLABS_MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

# BLOCKING spend guard for the WHOLE course, checked before any synthesis. The
# ElevenLabs free tier is 10,000 characters a month and is shared with the YT
# autopilot, so a runaway script must cost nothing rather than most of a month.
MAX_TTS_CHARS = int(os.environ.get("MAX_TTS_CHARS", "3000"))
MAX_SLIDES = int(os.environ.get("MAX_SLIDES", "16"))

# Brand. Placeholder palette until GymRamp supplies its template; everything
# visual reads from here so the swap is one place.
BRAND_NAME = os.environ.get("BRAND_NAME", "GymRamp")
C_NAVY = os.environ.get("BRAND_PRIMARY", "#0B1F33")
C_ACCENT = os.environ.get("BRAND_ACCENT", "#FF6B2C")
C_LIGHT = os.environ.get("BRAND_LIGHT", "#F5F7FA")
C_TEXT = os.environ.get("BRAND_TEXT", "#1B2733")
C_MUTED = os.environ.get("BRAND_MUTED", "#6B7785")

FONT_DIR = "/usr/share/fonts/truetype/montserrat"
FONT_BOLD = FONT_DIR + "/Montserrat-Bold.ttf"
FONT_SEMI = FONT_DIR + "/Montserrat-SemiBold.ttf"
FONT_REG = FONT_DIR + "/Montserrat-Regular.ttf"
if not Path(FONT_BOLD).exists():  # degrade, never fail a render on a font
    FONT_BOLD = FONT_SEMI = FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Canvas: 16:9 at 144 px per inch -> 1920 x 1080.
# Exact, not 13.333: 13.333 * 144 truncates to 1919 px, and libx264 refuses odd
# widths ("width not divisible by 2") -- the PPTX never notices, the video dies.
CANVAS_PX = (1920, 1080)
PX = 144
W_IN, H_IN = CANVAS_PX[0] / PX, CANVAS_PX[1] / PX
SEGMENT_PAD_SECONDS = 0.7
REFS_PER_SLIDE = 4

ALLOWED_FILES = {
    "course.pptx", "course.mp4", "worksheet.docx", "quiz.docx", "exam.docx",
    "answer-key.docx", "sources.md", "package.json",
}
FILE_KIND = {
    "course.pptx": "pptx", "course.mp4": "mp4", "worksheet.docx": "worksheet",
    "quiz.docx": "quiz", "exam.docx": "exam", "answer-key.docx": "answer_key",
    "sources.md": "sources",
}

app = FastAPI(title="GymRamp course worker")
_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


# --------------------------------------------------------------------------
# request model
# --------------------------------------------------------------------------

class Slide(BaseModel):
    title: str
    bullets: List[str] = Field(default_factory=list)
    notes: str = ""                      # narration; may contain [n] markers
    refs: List[int] = Field(default_factory=list)


class Reference(BaseModel):
    n: int
    citation: str
    url: Optional[str] = None


class Question(BaseModel):
    question: str
    options: List[str]
    answer_index: int
    rationale: str = ""
    refs: List[int] = Field(default_factory=list)


class Assessment(BaseModel):
    title: str = ""
    instructions: str = ""
    pass_mark_percent: Optional[int] = None
    questions: List[Question] = Field(default_factory=list)


class WorksheetSection(BaseModel):
    heading: str
    prompts: List[str] = Field(default_factory=list)


class Worksheet(BaseModel):
    title: str = ""
    instructions: str = ""
    sections: List[WorksheetSection] = Field(default_factory=list)


class CoursePackage(BaseModel):
    course_slug: str
    version: int = 1
    title: str
    subtitle: str = ""
    audience: str = ""
    intro_notes: str = ""
    slides: List[Slide]
    takeaways: List[str] = Field(default_factory=list)
    takeaways_notes: str = ""
    references: List[Reference] = Field(default_factory=list)
    worksheet: Worksheet = Field(default_factory=Worksheet)
    quiz: Assessment = Field(default_factory=Assessment)
    exam: Assessment = Field(default_factory=Assessment)
    disclaimer: str = "Educational content for fitness and wellness professionals. Not medical advice."
    tts_provider: Optional[str] = None   # override: "elevenlabs" | "edge"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def run(cmd: List[str], timeout: int = 900) -> str:
    """argv list, never a shell, so slide text can never inject anything."""
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-1200:]
        raise RuntimeError("command failed: " + " ".join(cmd[:3]) + " ... -> " + tail)
    return proc.stdout


def probe_duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "quiet", "-of", "csv=p=0", "-show_entries",
               "format=duration", str(path)], timeout=60)
    return float(out.strip())


def set_job(job_id: str, **fields: Any) -> None:
    with _lock:
        _jobs.setdefault(job_id, {"job_id": job_id}).update(fields)
        snapshot = dict(_jobs[job_id])
    # Persist so a worker restart does not orphan a finished job.
    job_dir = JOBS_ROOT / job_id
    if job_dir.exists():
        (job_dir / "job.json").write_text(json.dumps(snapshot, indent=2))


def get_job(job_id: str) -> Dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job_id: " + job_id)
    return dict(job)


MARKER_RE = re.compile(r"\s*\[(?:\d+(?:\s*[,–-]\s*\d+)*)\]")


def spoken(text: str) -> str:
    """Narration without the [n] citation markers -- a voice reading out
    'bracket three' is the kind of defect nobody notices until it ships."""
    return re.sub(r"\s{2,}", " ", MARKER_RE.sub("", text or "")).strip()


def hex_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def narration_plan(pkg: CoursePackage) -> List[Dict[str, Any]]:
    """The ordered slide deck, shared by PPTX, PNG and TTS so they cannot drift."""
    deck: List[Dict[str, Any]] = [{
        "kind": "title", "title": pkg.title, "subtitle": pkg.subtitle,
        "notes": pkg.intro_notes or ("Welcome to %s. %s" % (pkg.title, pkg.subtitle)),
    }]
    for i, s in enumerate(pkg.slides, 1):
        deck.append({"kind": "content", "title": s.title, "bullets": s.bullets,
                     "notes": s.notes, "refs": s.refs, "index": i})
    if pkg.takeaways:
        deck.append({"kind": "takeaways", "title": "Key Takeaways", "bullets": pkg.takeaways,
                     "notes": pkg.takeaways_notes or "Let's recap the key takeaways. " + " ".join(pkg.takeaways)})
    # Paginated: ten full APA citations on one slide overflowed the canvas on the first
    # real course, running under the page number and off the bottom edge.
    pages = [pkg.references[i:i + REFS_PER_SLIDE] for i in range(0, len(pkg.references), REFS_PER_SLIDE)]
    for p, chunk in enumerate(pages):
        deck.append({
            "kind": "references",
            "title": "References" if len(pages) == 1 else "References (%d of %d)" % (p + 1, len(pages)),
            "references": chunk,
            "notes": ("Every claim in this course is linked to the sources listed here. "
                      "Review them in the course materials before your certification exam.")
                     if p == 0 else "References, continued.",
        })
    return deck


# --------------------------------------------------------------------------
# layout: one spec, two renderers
# --------------------------------------------------------------------------
# Every box is (left, top, width, height) in inches.

LAYOUT = {
    "band": (0, 0, W_IN, 1.25),
    "title": (0.7, 0.22, 11.2, 0.85),
    "brand": (11.0, 0.4, 1.9, 0.5),
    "body": (0.9, 1.75, 11.5, 4.9),
    "footer": (0.7, 6.9, 10.6, 0.4),
    "page": (11.6, 6.9, 1.2, 0.4),
    "accent": (0.7, 1.25, 1.6, 0.08),
}


class PngCanvas:
    def __init__(self) -> None:
        self.img = Image.new("RGB", CANVAS_PX, hex_rgb(C_LIGHT))
        self.d = ImageDraw.Draw(self.img)

    @staticmethod
    def px(v: float) -> int:
        return int(round(v * PX))

    def rect(self, box, color) -> None:
        l, t, w, h = box
        self.d.rectangle([self.px(l), self.px(t), self.px(l + w), self.px(t + h)], fill=hex_rgb(color))

    def text(self, box, text, font_path, size_pt, color, align="left", valign="top", spacing=1.25):
        """Word-wrap inside the box; shrink the font until it fits."""
        l, t, w, h = box
        size = size_pt
        while True:
            font = ImageFont.truetype(font_path, int(size * PX / 72))
            lines = self._wrap(text, font, self.px(w))
            line_h = int(font.size * spacing)
            if line_h * len(lines) <= self.px(h) or size <= 12:
                break
            size -= 2
        total = line_h * len(lines)
        y = self.px(t) + (max(0, self.px(h) - total) // 2 if valign == "middle" else 0)
        for line in lines:
            lw = self.d.textlength(line, font=font)
            x = self.px(l) + (self.px(w) - lw) / 2 if align == "center" else self.px(l)
            self.d.text((x, y), line, font=font, fill=hex_rgb(color))
            y += line_h
        return size

    def _wrap(self, text, font, max_w) -> List[str]:
        out: List[str] = []
        for para in (text or "").split("\n"):
            words, cur = para.split(), ""
            for word in words:
                trial = (cur + " " + word).strip()
                if self.d.textlength(trial, font=font) <= max_w:
                    cur = trial
                else:
                    if cur:
                        out.append(cur)
                    cur = word
            out.append(cur)
        return out

    def bullets(self, box, items: List[str], size_pt=30):
        """Bullets with a hanging indent; shrinks uniformly until all fit."""
        l, t, w, h = box
        size = size_pt
        while True:
            font = ImageFont.truetype(FONT_REG, int(size * PX / 72))
            line_h = int(font.size * 1.3)
            gap = int(font.size * 0.55)
            blocks = [self._wrap(it, font, self.px(w - 0.45)) for it in items]
            total = sum(len(b) * line_h + gap for b in blocks)
            if total <= self.px(h) or size <= 14:
                break
            size -= 2
        y = self.px(t)
        for b in blocks:
            r = int(font.size * 0.2)
            cy = y + line_h // 2
            self.d.ellipse([self.px(l) + 4, cy - r, self.px(l) + 4 + 2 * r, cy + r], fill=hex_rgb(C_ACCENT))
            for line in b:
                self.d.text((self.px(l + 0.45), y), line, font=font, fill=hex_rgb(C_TEXT))
                y += line_h
            y += gap
        return size

    def save(self, path: Path) -> None:
        self.img.save(path, "PNG")


def _pptx_box(slide, box, fill=None):
    l, t, w, h = box
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(l), Inches(t), Inches(w), Inches(h))
    shape.line.fill.background()
    if fill:
        shape.fill.solid()
        shape.fill.fore_color.rgb = PptxRGB(*hex_rgb(fill))
    else:
        shape.fill.background()
    return shape


def _pptx_text(slide, box, text, size, color, bold=False, align=None, font="Montserrat"):
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    l, t, w, h = box
    tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = PptxPt(size)
    p.font.bold = bold
    p.font.name = font
    p.font.color.rgb = PptxRGB(*hex_rgb(color))
    if align == "center":
        p.alignment = PP_ALIGN.CENTER
    return tf


def render_slide(entry: Dict[str, Any], prs: Presentation, png_path: Path, pkg: CoursePackage, total: int, pos: int) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    canvas = PngCanvas()
    kind = entry["kind"]

    if kind == "title":
        _pptx_box(slide, (0, 0, W_IN, H_IN), C_NAVY)
        canvas.rect((0, 0, W_IN, H_IN), C_NAVY)
        _pptx_box(slide, (0.9, 2.2, 2.2, 0.1), C_ACCENT)
        canvas.rect((0.9, 2.2, 2.2, 0.1), C_ACCENT)
        size = canvas.text((0.9, 2.5, 11.5, 2.0), entry["title"], FONT_BOLD, 50, "#FFFFFF")
        _pptx_text(slide, (0.9, 2.5, 11.5, 2.0), entry["title"], size, "#FFFFFF", bold=True)
        canvas.text((0.9, 4.6, 11.5, 1.0), entry.get("subtitle", ""), FONT_REG, 26, "#C9D3DD")
        _pptx_text(slide, (0.9, 4.6, 11.5, 1.0), entry.get("subtitle", ""), 26, "#C9D3DD")
        tag = "%s  |  %s" % (BRAND_NAME.upper(), pkg.audience) if pkg.audience else BRAND_NAME.upper()
        canvas.text((0.9, 0.7, 11.5, 0.6), tag, FONT_SEMI, 20, C_ACCENT)
        _pptx_text(slide, (0.9, 0.7, 11.5, 0.6), tag, 20, C_ACCENT, bold=True)
        canvas.text((0.9, 6.6, 11.5, 0.5), pkg.disclaimer, FONT_REG, 14, "#9FB0C0")
        _pptx_text(slide, (0.9, 6.6, 11.5, 0.5), pkg.disclaimer, 14, "#9FB0C0")
    else:
        _pptx_box(slide, (0, 0, W_IN, H_IN), C_LIGHT)
        for box, color in ((LAYOUT["band"], C_NAVY), (LAYOUT["accent"], C_ACCENT)):
            _pptx_box(slide, box, color)
            canvas.rect(box, color)
        size = canvas.text(LAYOUT["title"], entry["title"], FONT_BOLD, 34, "#FFFFFF", valign="middle")
        _pptx_text(slide, LAYOUT["title"], entry["title"], size, "#FFFFFF", bold=True)
        canvas.text(LAYOUT["brand"], BRAND_NAME.upper(), FONT_SEMI, 16, C_ACCENT)
        _pptx_text(slide, LAYOUT["brand"], BRAND_NAME.upper(), 16, C_ACCENT, bold=True)

        if kind == "references":
            lines = ["[%d] %s" % (r.n, r.citation) for r in entry["references"]]
            size = canvas.text(LAYOUT["body"], "\n".join(lines), FONT_REG, 16, C_TEXT, spacing=1.3)
            _pptx_text(slide, LAYOUT["body"], "\n".join(lines), size, C_TEXT)
        else:
            items = entry.get("bullets") or []
            size = canvas.bullets(LAYOUT["body"], items)
            tf = _pptx_text(slide, LAYOUT["body"], "", size, C_TEXT)
            for i, item in enumerate(items):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = "•  " + item
                p.font.size = PptxPt(size)
                p.font.name = "Montserrat"
                p.font.color.rgb = PptxRGB(*hex_rgb(C_TEXT))
                p.space_after = PptxPt(size * 0.5)

        refs = entry.get("refs") or []
        footer = ("Sources: " + ", ".join("[%d]" % r for r in refs)) if refs else ""
        if footer:
            canvas.text(LAYOUT["footer"], footer, FONT_REG, 13, C_MUTED)
            _pptx_text(slide, LAYOUT["footer"], footer, 13, C_MUTED)
        page = "%d / %d" % (pos, total)
        canvas.text(LAYOUT["page"], page, FONT_REG, 13, C_MUTED, align="center")
        _pptx_text(slide, LAYOUT["page"], page, 13, C_MUTED, align="center")

    # Speaker notes keep the [n] markers so a reviewer can trace every sentence.
    slide.notes_slide.notes_text_frame.text = entry.get("notes", "")
    canvas.save(png_path)


# --------------------------------------------------------------------------
# text to speech
# --------------------------------------------------------------------------

class TTSFallback(Exception):
    pass


def elevenlabs_remaining() -> Optional[int]:
    try:
        r = httpx.get(ELEVENLABS_BASE + "/user/subscription",
                      headers={"xi-api-key": ELEVENLABS_API_KEY}, timeout=15.0)
        r.raise_for_status()
        d = r.json()
        return int(d["character_limit"]) - int(d["character_count"])
    except Exception as exc:  # noqa: BLE001 - advisory only
        print("[tts] balance unknown: %s" % exc, flush=True)
        return None


def tts_elevenlabs(text: str, out: Path) -> None:
    try:
        r = httpx.post(
            "%s/text-to-speech/%s?output_format=mp3_44100_128" % (ELEVENLABS_BASE, ELEVENLABS_VOICE_ID),
            headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
            json={"text": text, "model_id": ELEVENLABS_MODEL_ID},
            timeout=180.0,
        )
    except Exception as exc:  # noqa: BLE001
        raise TTSFallback("network_error:%s" % type(exc).__name__) from exc
    if r.status_code in (401, 403):
        raise TTSFallback("auth_failed:%d" % r.status_code)
    if r.status_code == 402:
        raise TTSFallback("quota_exceeded")
    if r.status_code >= 400:
        raise TTSFallback("http_%d:%s" % (r.status_code, r.text[:200]))
    tmp = out.with_suffix(".part")
    tmp.write_bytes(r.content)
    os.replace(tmp, out)


def tts_edge(text: str, out: Path) -> None:
    asyncio.run(edge_tts.Communicate(text, TTS_VOICE).save(str(out)))


def synthesize_all(texts: List[str], job_dir: Path, provider: str, job_id: str) -> Dict[str, Any]:
    """All slides use ONE provider. A mid-course switch would change the voice
    halfway through the video, so an ElevenLabs failure on any slide re-voices
    the whole course with edge-tts and records why."""
    total_chars = sum(len(t) for t in texts)
    if total_chars > MAX_TTS_CHARS:
        raise RuntimeError(
            "narration is %d characters, over MAX_TTS_CHARS=%d -- refusing to synthesize. "
            "No TTS characters were spent. Shorten the speaker notes upstream." % (total_chars, MAX_TTS_CHARS))

    reason: Optional[str] = None
    charged = 0
    if provider == "elevenlabs":
        if not ELEVENLABS_API_KEY:
            reason = "no_api_key"
        else:
            left = elevenlabs_remaining()
            if left is not None and left < total_chars:
                reason = "insufficient_quota:%d_left_%d_needed" % (left, total_chars)
        if reason is None:
            try:
                for i, text in enumerate(texts):
                    set_job(job_id, stage="narration", detail="elevenlabs slide %d/%d" % (i + 1, len(texts)))
                    tts_elevenlabs(text, job_dir / ("audio_%02d.mp3" % i))
                    charged += len(text)
                return {"provider": "elevenlabs", "fallback_reason": None, "characters_charged": charged}
            except TTSFallback as exc:
                reason = str(exc)
    for i, text in enumerate(texts):
        set_job(job_id, stage="narration", detail="edge-tts slide %d/%d" % (i + 1, len(texts)))
        tts_edge(text, job_dir / ("audio_%02d.mp3" % i))
    return {"provider": "edge", "fallback_reason": reason, "characters_charged": charged}


# --------------------------------------------------------------------------
# documents
# --------------------------------------------------------------------------

def _doc(title: str, subtitle: str) -> Document:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    h = doc.add_heading(title, level=0)
    for run_ in h.runs:
        run_.font.color.rgb = RGBColor(*hex_rgb(C_NAVY))
    if subtitle:
        p = doc.add_paragraph(subtitle)
        p.runs[0].font.color.rgb = RGBColor(*hex_rgb(C_MUTED))
    return doc


def write_worksheet(pkg: CoursePackage, path: Path) -> None:
    ws = pkg.worksheet
    doc = _doc(ws.title or (pkg.title + " - Worksheet"), "%s  |  %s" % (BRAND_NAME, pkg.audience))
    doc.add_paragraph("Name: ______________________    Date: ____________")
    if ws.instructions:
        doc.add_paragraph(ws.instructions)
    for sec in ws.sections:
        doc.add_heading(sec.heading, level=2)
        for i, prompt in enumerate(sec.prompts, 1):
            doc.add_paragraph("%d. %s" % (i, prompt))
            for _ in range(3):
                doc.add_paragraph("_" * 90)
    doc.add_paragraph(pkg.disclaimer).runs[0].font.size = Pt(8)
    doc.save(path)


def write_assessment(pkg: CoursePackage, a: Assessment, default_title: str, path: Path) -> None:
    doc = _doc(a.title or default_title, "%s  |  %s" % (BRAND_NAME, pkg.title))
    doc.add_paragraph("Name: ______________________    Date: ____________")
    if a.instructions:
        doc.add_paragraph(a.instructions)
    if a.pass_mark_percent:
        doc.add_paragraph("Pass mark: %d%%  (%d questions)" % (a.pass_mark_percent, len(a.questions)))
    for i, q in enumerate(a.questions, 1):
        doc.add_paragraph("%d. %s" % (i, q.question)).runs[0].bold = True
        for j, opt in enumerate(q.options):
            doc.add_paragraph("    %s) %s" % ("ABCDEFGH"[j], opt))
    doc.save(path)


def write_answer_key(pkg: CoursePackage, path: Path) -> None:
    doc = _doc(pkg.title + " - Answer Key", "For instructors and administrators only")
    for label, a in (("Quiz", pkg.quiz), ("Certification Exam", pkg.exam)):
        if not a.questions:
            continue
        doc.add_heading(label, level=1)
        for i, q in enumerate(a.questions, 1):
            ans = "ABCDEFGH"[q.answer_index] if 0 <= q.answer_index < len(q.options) else "?"
            p = doc.add_paragraph()
            p.add_run("%d. %s  " % (i, ans)).bold = True
            p.add_run(q.options[q.answer_index] if ans != "?" else "INVALID ANSWER INDEX")
            if q.rationale:
                doc.add_paragraph("    Why: " + q.rationale)
            if q.refs:
                doc.add_paragraph("    Source: " + ", ".join("[%d]" % r for r in q.refs))
    doc.add_heading("References", level=1)
    for r in pkg.references:
        doc.add_paragraph("[%d] %s" % (r.n, r.citation))
    doc.save(path)


def write_sources(pkg: CoursePackage, path: Path) -> None:
    lines = ["# References - %s" % pkg.title, ""]
    for r in pkg.references:
        lines.append("%d. %s%s" % (r.n, r.citation, ("  <%s>" % r.url) if r.url else ""))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# the job
# --------------------------------------------------------------------------

def _render(job_id: str, job_dir: Path, pkg: CoursePackage) -> None:
    try:
        deck = narration_plan(pkg)
        texts = [spoken(e["notes"]) or e["title"] for e in deck]

        set_job(job_id, status="running", stage="slides")
        prs = Presentation()
        prs.slide_width, prs.slide_height = Emu(int(Inches(W_IN))), Emu(int(Inches(H_IN)))
        for i, entry in enumerate(deck):
            render_slide(entry, prs, job_dir / ("slide_%02d.png" % i), pkg, len(deck), i + 1)
        prs.save(job_dir / "course.pptx")

        set_job(job_id, stage="documents")
        write_worksheet(pkg, job_dir / "worksheet.docx")
        write_assessment(pkg, pkg.quiz, pkg.title + " - Knowledge Check Quiz", job_dir / "quiz.docx")
        write_assessment(pkg, pkg.exam, pkg.title + " - Certification Exam", job_dir / "exam.docx")
        write_answer_key(pkg, job_dir / "answer-key.docx")
        write_sources(pkg, job_dir / "sources.md")

        # Narration last among cheap steps: a document bug should fail before
        # any paid characters are spent.
        provider = (pkg.tts_provider or TTS_PROVIDER).lower()
        tts = synthesize_all(texts, job_dir, provider, job_id)
        set_job(job_id, tts_provider=tts["provider"], tts_fallback_reason=tts["fallback_reason"],
                tts_characters_charged=tts["characters_charged"])

        set_job(job_id, stage="video")
        concat = job_dir / "concat.txt"
        seg_lines = []
        for i in range(len(deck)):
            audio = job_dir / ("audio_%02d.mp3" % i)
            seg = job_dir / ("seg_%02d.mp4" % i)
            dur = probe_duration(audio) + SEGMENT_PAD_SECONDS
            set_job(job_id, detail="segment %d/%d" % (i + 1, len(deck)))
            # Identical encode parameters on every segment is what lets the
            # concat below stream-copy instead of re-encoding the whole course.
            run(["ffmpeg", "-y", "-loop", "1", "-framerate", "30", "-i", str(job_dir / ("slide_%02d.png" % i)),
                 "-i", str(audio), "-af", "apad", "-t", "%.3f" % dur,
                 "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-pix_fmt", "yuv420p",
                 "-r", "30", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", str(seg)],
                timeout=max(300, int(dur * 30)))
            seg_lines.append("file '%s'" % seg.name)
        concat.write_text("\n".join(seg_lines) + "\n")
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy",
             "-movflags", "+faststart", str(job_dir / "course.mp4")], timeout=600)

        files = []
        for name, kind in FILE_KIND.items():
            p = job_dir / name
            entry = {"kind": kind, "filename": name, "bytes": p.stat().st_size,
                     "path": "/jobs/%s/files/%s" % (job_id, name),
                     "url": "%s/jobs/%s/files/%s" % (PUBLIC_BASE_URL, job_id, name)}
            if kind == "mp4":
                entry["duration_seconds"] = round(probe_duration(p), 2)
            files.append(entry)

        for p in list(job_dir.glob("seg_*.mp4")) + [concat]:
            p.unlink(missing_ok=True)

        set_job(job_id, status="done", stage="complete", detail=None, files=files,
                slide_count=len(deck), narration_characters=sum(len(t) for t in texts),
                video_seconds=next(f["duration_seconds"] for f in files if f["kind"] == "mp4"))
    except Exception as exc:  # noqa: BLE001 - reported to n8n via the poll
        traceback.print_exc()
        set_job(job_id, status="failed", error=str(exc)[:2000])


@app.post("/courses/render")
def render(pkg: CoursePackage) -> Dict[str, Any]:
    if not pkg.slides:
        raise HTTPException(status_code=422, detail="course package has no slides")
    if len(pkg.slides) > MAX_SLIDES:
        raise HTTPException(status_code=422, detail="%d slides exceeds MAX_SLIDES=%d" % (len(pkg.slides), MAX_SLIDES))
    slug = re.sub(r"[^a-z0-9-]+", "-", pkg.course_slug.lower()).strip("-")[:60] or "course"

    # Idempotent per (slug, version): an n8n retry of this call must not pay
    # for narration twice. A finished or running job is returned as-is.
    with _lock:
        for job in _jobs.values():
            if job.get("course_slug") == slug and job.get("version") == pkg.version \
                    and job.get("status") in ("queued", "running", "done"):
                return {"job_id": job["job_id"], "status": job["status"], "reused": True}

    job_id = "%s-v%d-%s" % (slug, pkg.version, uuid.uuid4().hex[:6])
    job_dir = JOBS_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "package.json").write_text(pkg.model_dump_json(indent=2))
    set_job(job_id, status="queued", stage="queued", course_slug=slug, version=pkg.version)
    threading.Thread(target=_render, args=(job_id, job_dir, pkg), daemon=True).start()
    return {"job_id": job_id, "status": "queued", "reused": False}


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> Dict[str, Any]:
    return get_job(job_id)


@app.get("/jobs/{job_id}/files/{filename}")
def job_file(job_id: str, filename: str) -> FileResponse:
    if filename not in ALLOWED_FILES:  # whitelist: no path traversal possible
        raise HTTPException(status_code=404, detail="unknown file")
    path = JOBS_ROOT / job_id / filename
    if "/" in job_id or ".." in job_id or not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, filename=filename)


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> Dict[str, Any]:
    if "/" in job_id or ".." in job_id:
        raise HTTPException(status_code=400, detail="bad job id")
    job_dir = JOBS_ROOT / job_id
    existed = job_dir.exists()
    shutil.rmtree(job_dir, ignore_errors=True)
    with _lock:
        _jobs.pop(job_id, None)
    return {"deleted": existed, "job_id": job_id}


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "tts_provider": TTS_PROVIDER,
        "elevenlabs_key_present": bool(ELEVENLABS_API_KEY),
        "max_tts_chars": MAX_TTS_CHARS,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "font": FONT_BOLD,
        "jobs": len(_jobs),
    }


@app.get("/tts/quota")
def tts_quota() -> Dict[str, Any]:
    if not ELEVENLABS_API_KEY:
        return {"provider": TTS_PROVIDER, "elevenlabs_remaining": None, "reason": "no_api_key"}
    return {"provider": TTS_PROVIDER, "elevenlabs_remaining": elevenlabs_remaining(),
            "max_tts_chars": MAX_TTS_CHARS}


def _rehydrate() -> None:
    """Restore job state from job.json so a restart does not 404 a poll mid-run.
    Anything not finished was interrupted and is marked failed, which routes
    the workflow to its error branch instead of polling forever."""
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    for d in JOBS_ROOT.iterdir():
        f = d / "job.json"
        if d.is_dir() and f.exists():
            job = json.loads(f.read_text())
            if job.get("status") not in ("done", "failed"):
                job.update(status="failed", error="worker restarted before this job finished")
            _jobs[d.name] = job


_rehydrate()
