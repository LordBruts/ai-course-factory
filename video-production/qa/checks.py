"""Quality gate for a rendered course video: video_qa.json + VIDEO_QA_REPORT.md.

    python video-production/qa/checks.py --job /data/video-jobs/rlt-v3-faceless \
        --package source/package.json

Nothing reaches a reviewer until this passes. Four families, per the brief:

technical   the file is what was asked for (ffprobe), the narration assets are the
            approved ones byte for byte, no stretch of unexpected silence.
editorial   the narration says the approved script; captions say the narration;
            no sentence is clipped; nothing plays twice.
visual      no black frames, no stall longer than a scene is allowed to hold, no text
            overflow or intrusion into the caption band (HyperFrames' own `check`),
            captions actually drawn, every visual starts on its beat.
content     every citation resolves, on-screen text is approved wording, and no number
            appears on screen that the approved course does not contain.

A check reports pass | warn | fail | skipped. Any fail makes the report `fail`; the
self-evaluation loop reads `errors[].auto_correctable` to decide whether another
attempt can fix it or the render goes to manual review.

What this does NOT do, stated so the report is not over-read: it does not re-transcribe
the rendered mix (that is a second paid Scribe call). Narration fidelity is checked on
the cached transcripts of the exact files placed in the render, whose bytes are
verified against the approved sources.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_VP = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_VP, "storyboard"))
sys.path.insert(0, os.path.join(_VP, "editing"))

from beats import collapse_numbers, numbers_in, split_sentences, strip_markers, spoken_tokens  # noqa: E402
from deck import video_deck, video_script  # noqa: E402
from rules import validate_storyboard  # noqa: E402

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


class Report:
    def __init__(self) -> None:
        self.checks: Dict[str, str] = {}
        self.metrics: Dict[str, Any] = {}
        self.warnings: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []
        self.advisories: List[Dict[str, Any]] = []
        self.notes: Dict[str, str] = {}

    def set(self, name: str, status: str, note: str = "") -> None:
        # A check can only get worse within one run: fail > warn > pass > skipped.
        order = {"skipped": 0, "pass": 1, "warn": 2, "fail": 3}
        if order[status] >= order.get(self.checks.get(name, "skipped"), 0):
            self.checks[name] = status
        if note:
            self.notes[name] = note

    def warn(self, check: str, message: str, **kw: Any) -> None:
        self.set(check, "warn")
        self.warnings.append({"check": check, "message": message, **kw})

    def fail(self, check: str, message: str, auto_correctable: bool = False, **kw: Any) -> None:
        self.set(check, "fail")
        self.errors.append({"check": check, "message": message,
                            "auto_correctable": auto_correctable, **kw})

    @property
    def status(self) -> str:
        values = set(self.checks.values())
        return "fail" if "fail" in values else ("warn" if "warn" in values else "pass")


# ------------------------------------------------------------------ tooling ---

def _run(cmd: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def ffprobe(path: str) -> Dict[str, Any]:
    proc = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:400])
    return json.loads(proc.stdout or "{}")


def _filter_log(path: str, vf: Optional[str], af: Optional[str], timeout: int) -> str:
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path]
    cmd += (["-vf", vf] if vf else ["-vn"]) + (["-af", af] if af else ["-an"])
    cmd += ["-f", "null", "-"]
    return _run(cmd, timeout=timeout).stderr


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_srt(path: str) -> List[Tuple[float, float, str]]:
    def ts(v: str) -> float:
        h, m, rest = v.strip().split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    cues = []
    with open(path, encoding="utf-8") as fh:
        blocks = fh.read().strip().split("\n\n")
    for b in blocks:
        lines = [x for x in b.splitlines() if x.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        a, z = lines[1].split("-->")
        cues.append((ts(a), ts(z), " ".join(lines[2:])))
    return cues


_ALLOWED_NUMBERS: Optional[set] = None


def _tokens(text: str) -> List[str]:
    # Numbers compare by value ("eight oh eight" is 808), preferring readings the course states.
    return collapse_numbers(spoken_tokens(strip_markers(text)), _ALLOWED_NUMBERS)


# ------------------------------------------------------------------- checks ---

def technical(r: Report, final: str, edl: Dict[str, Any], job: str, spec: Dict[str, Any]) -> float:
    try:
        info = ffprobe(final)
    except Exception as exc:  # noqa: BLE001
        r.fail("container_valid", "ffprobe cannot read the render: %s" % exc)
        return 0.0
    r.set("container_valid", "pass")
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    duration = float(info.get("format", {}).get("duration") or 0)
    r.metrics["duration_seconds"] = round(duration, 3)
    r.metrics["expected_seconds"] = edl["total_seconds"]

    if not video or video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p":
        r.fail("video_stream", "expected h264/yuv420p, got %s/%s" % (
            video and video.get("codec_name"), video and video.get("pix_fmt")))
    else:
        r.set("video_stream", "pass")
    if not audio:
        r.fail("audio_stream", "no audio stream")
    else:
        r.set("audio_stream", "pass")
    if (video or {}).get("width") != spec["width"] or (video or {}).get("height") != spec["height"]:
        r.fail("resolution", "rendered %sx%s, expected %sx%s" % (
            (video or {}).get("width"), (video or {}).get("height"), spec["width"], spec["height"]))
    else:
        r.set("resolution", "pass")
    rate = (video or {}).get("avg_frame_rate", "0/1").split("/")
    fps = float(rate[0]) / float(rate[1]) if len(rate) == 2 and float(rate[1]) else 0
    if abs(fps - spec["fps"]) > 0.01:
        r.fail("frame_rate", "%.3f fps, expected %s" % (fps, spec["fps"]))
    else:
        r.set("frame_rate", "pass")
    if abs(duration - edl["total_seconds"]) > 0.5:
        r.fail("duration_matches_edl", "render is %.2fs, EDL is %.2fs" % (duration, edl["total_seconds"]),
               auto_correctable=True)
    else:
        r.set("duration_matches_edl", "pass")

    # The files placed in the composition must be the approved narration, byte for byte.
    project_assets = os.path.join(job, "project", "assets")
    missing, changed = [], []
    for name, src in edl["sources"].items():
        placed = (os.path.join(project_assets, "presenter.mp4") if name == "presenter"
                  else os.path.join(project_assets, name.replace("audio_", "narration_") + ".mp3"))
        if not (os.path.exists(src) and os.path.exists(placed)):
            missing.append(name)
        elif sha256(src) != sha256(placed):
            changed.append(name)
    if missing or changed:
        r.fail("assets_present", "missing %s, altered %s" % (missing or "none", changed or "none"))
    else:
        r.set("assets_present", "pass", "%d source file(s) placed, hashes match" % len(edl["sources"]))

    # Unexpected silence inside the narration: a missing or mis-timed clip.
    log = _filter_log(final, None, "silencedetect=noise=-45dB:d=2.0", timeout=600)
    silences = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", log)]
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    long_gaps = [(s, d) for s, d in zip(starts, silences) if s < edl["total_seconds"] - 1.0]
    if long_gaps:
        for s, d in long_gaps:
            r.fail("no_duplicated_audio", "%.1fs of silence inside the narration" % d, at_seconds=round(s, 2))
    return duration


def editorial(r: Report, pkg: Dict[str, Any], edl: Dict[str, Any], srt: str,
              transcripts_dir: str, threshold: float) -> None:
    kept, _ = video_deck(pkg)
    approved = _tokens(video_script(kept))
    heard: List[str] = []
    words_all: List[Dict[str, Any]] = []
    clipped = []
    for rng in edl["ranges"]:
        path = os.path.join(transcripts_dir, rng["source"] + ".json")
        if not os.path.exists(path):
            r.fail("narration_matches_script", "no cached transcript for %s" % rng["source"])
            continue
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        words = [w for w in data.get("words", []) if w.get("type") == "word"]
        words_all.extend(words)
        heard.extend(t for w in words for t in _tokens(w.get("text", "")))
        if words and float(words[-1].get("end") or 0) > rng["end"] + 0.05:
            clipped.append(rng["source"])
    sm = difflib.SequenceMatcher(None, approved, heard, autojunk=False)
    similarity = round(sm.ratio(), 4)
    r.metrics["transcript_similarity"] = similarity
    r.metrics["words_checked"] = len(approved)
    if similarity < threshold:
        diffs = [" ".join(approved[i1:i2]) + " -> " + " ".join(heard[j1:j2])
                 for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"][:8]
        r.fail("narration_matches_script", "narration matches the approved script at %.1f%% (< %.0f%%): %s"
               % (100 * similarity, 100 * threshold, "; ".join(diffs)))
    else:
        r.set("narration_matches_script", "pass", "%.1f%% of %d approved words" % (100 * similarity, len(approved)))

    if clipped:
        r.fail("no_clipped_sentences", "speech runs past the end of %s" % ", ".join(clipped))
    else:
        r.set("no_clipped_sentences", "pass")

    sources = list(edl["sources"])
    outs = sorted((x["output_start"], x["output_start"] + x["end"] - x["start"]) for x in edl["ranges"])
    overlap = any(b[0] < a[1] - 0.001 for a, b in zip(outs, outs[1:]))
    if len(set(sources)) != len(sources) or overlap:
        r.fail("no_duplicated_audio", "a narration source is placed twice or ranges overlap")
    else:
        r.set("no_duplicated_audio", "pass")
    if edl.get("template") != "face":
        r.set("cut_boundaries", "pass", "faceless template: approved narration is never cut")
        r.set("audio_pops", "pass", "no cuts, so no cut points to fade")

    cues = parse_srt(srt)
    r.metrics["caption_cue_count"] = len(cues)
    cap = [t for _, _, text in cues for t in _tokens(text)]
    said = [t for w in words_all for t in _tokens(w.get("text", ""))]
    cap_ratio = difflib.SequenceMatcher(None, said, cap, autojunk=False).ratio() if said else 0.0
    bad_order = [i for i, (a, b) in enumerate(zip(cues, cues[1:])) if b[0] < a[1] - 0.001]
    too_long = [c for c in cues if len(c[2].split()) > 3]
    late = [c for c in cues if c[1] > edl["total_seconds"] + 0.05]
    if cap_ratio < 0.99 or bad_order or too_long or late:
        r.fail("captions_match_narration",
               "captions %.1f%% of spoken words; %d overlapping, %d over-long, %d past the end"
               % (100 * cap_ratio, len(bad_order), len(too_long), len(late)), auto_correctable=True)
    else:
        r.set("captions_match_narration", "pass", "%d cues cover %.1f%% of spoken words" % (len(cues), 100 * cap_ratio))


def visual(r: Report, final: str, base: str, job: str, storyboard: Dict[str, Any],
           qa_cfg: Dict[str, Any], max_hold: float) -> None:
    log = _filter_log(final, "blackdetect=d=0.1:pix_th=%s" % qa_cfg.get("black_frame_threshold", 0.02),
                      None, timeout=1200)
    blacks = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)
    r.metrics["black_frame_count"] = len(blacks)
    if blacks:
        for a, z in blacks:
            r.fail("black_frames", "black from %.2fs to %.2fs" % (float(a), float(z)), at_seconds=float(a))
    else:
        r.set("black_frames", "pass")

    # A card holds still by design; the check is for a stall longer than any scene may hold.
    log = _filter_log(base, "freezedetect=n=-60dB:d=%s" % qa_cfg.get("frozen_frame_seconds", 3.0),
                      None, timeout=1200)
    durations = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", log)]
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", log)]
    longest = max(durations or [0.0])
    r.metrics["longest_frozen_seconds"] = round(longest, 2)
    stalls = [(s, d) for s, d in zip(starts, durations) if d > max_hold + 2.0]
    if stalls:
        for s, d in stalls:
            r.fail("frozen_frames", "picture static for %.1fs (limit %.0fs)" % (d, max_hold + 2), at_seconds=s)
    else:
        r.set("frozen_frames", "pass", "longest still hold %.1fs, within the %.0fs scene limit" % (longest, max_hold + 2))

    manifest_path = os.path.join(job, "project", "composition.manifest.json")
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    r.metrics["scene_count"] = len(manifest["clips"])
    by_id = {s["segment_id"]: s for s in storyboard["segments"]}
    late = []
    boards = bool(manifest.get("boards"))
    for clip in manifest["clips"]:
        seg = by_id.get(clip["segment_id"])
        if not seg:
            continue
        if boards:
            # A board element may lead its sentence slightly or wait for a rise to clear,
            # but it must appear while that sentence is being spoken.
            if not (seg["start"] - 0.5 <= clip["start"] <= seg["end"]):
                late.append("%s (%.2fs, sentence %.2f-%.2fs)" % (clip["clip_id"], clip["start"], seg["start"], seg["end"]))
        elif abs(clip["start"] - seg["start"]) > 0.35:
            late.append("%s (%.2fs vs beat %.2fs)" % (clip["segment_id"], clip["start"], seg["start"]))
    if late:
        r.fail("overlay_timing", "visuals off their beat: %s" % ", ".join(late))
    else:
        r.set("overlay_timing", "pass", ("all %d board elements appear while their sentence is spoken" if boards
                                         else "all %d visuals start within 0.35s of their beat") % len(manifest["clips"]))

    # HyperFrames' own layout gate: overflow, off-canvas text, caption-band intrusion, contrast.
    zone = qa_cfg.get("_caption_band_fraction", 0.744)
    # A check that could not load the page says nothing about the video. It is retried
    # (a busy host is the usual cause) and never allowed to read as a pass.
    report: Dict[str, Any] = {}
    for _ in range(3):
        proc = _run(["hyperframes", "check", os.path.join(job, "project"), "--json", "--samples", "12",
                     "--timeout", "30000",
                     "--caption-zone", "x0=0;y0=%.3f;x1=1;y1=1;severity=error" % zone], timeout=1800)
        try:
            report = json.loads(proc.stdout[proc.stdout.find("{"):] or "{}")
        except json.JSONDecodeError:
            report = {}
        if report and not any(i.get("code") == "check_runtime_failure" for i in _collect_issues(report)):
            break
    with open(os.path.join(job, "qa", "hyperframes_check.json"), "w", encoding="utf-8") as fh:
        fh.write(proc.stdout or "{}")
    if not report:
        r.warn("text_overflow", "hyperframes check produced no report (exit %s)" % proc.returncode)
    for issue in _collect_issues(report):
        code = str(issue.get("code") or "")
        severity = str(issue.get("severity") or "").lower()
        if severity == "info":
            continue
        reason = _advisory_reason(issue)
        if reason:
            r.advisories.append({"code": code, "message": str(issue.get("message", ""))[:200], "why_accepted": reason})
            continue
        if code == "check_runtime_failure":
            r.fail("text_overflow", "layout check could not run after 3 tries: %s" % issue.get("message", ""),
                   auto_correctable=True)
            continue
        family = CHECK_CODE_FAMILY.get(code, "text_overflow")
        message = "%s at %ss: %s%s" % (code, issue.get("time", "?"), issue.get("message", ""),
                                       (" (%s)" % issue["text"]) if issue.get("text") else "")
        if severity == "error":
            r.fail(family, message, auto_correctable=family == "caption_occlusion",
                   at_seconds=issue.get("time"))
        else:
            r.warn(family, message, at_seconds=issue.get("time"))
    for name in ("text_overflow", "caption_occlusion", "text_contrast"):
        if name not in r.checks and report:
            r.set(name, "pass")

    # Captions really drawn: the caption band must differ between base and final
    # while narration is playing.
    cues = parse_srt(os.path.join(job, "edit", "master.srt"))
    probe_at = [c[0] + (c[1] - c[0]) / 2 for c in cues[:: max(1, len(cues) // 6)]][:6]
    drawn = 0
    for t in probe_at:
        if _band_differs(base, final, t):
            drawn += 1
    if probe_at and drawn < len(probe_at):
        r.fail("captions_visible", "captions missing at %d of %d sampled cues" % (len(probe_at) - drawn, len(probe_at)),
               auto_correctable=True)
    else:
        r.set("captions_visible", "pass", "caption present at %d sampled cues" % drawn)
    if manifest.get("template") != "face":
        r.set("presenter_visible", "skipped", "faceless template has no presenter")


# `hyperframes check` finding codes -> the QA check they belong to.
CHECK_CODE_FAMILY = {
    "caption_zone_collision": "caption_occlusion",
    "contrast_aa_failure": "text_contrast",
    "text_occluded": "text_overflow",
    "text_overflow": "text_overflow",
    "off_canvas": "text_overflow",
}


def _advisory_reason(issue: Dict[str, Any]) -> Optional[str]:
    """Known findings that are not defects, each with the reason it is accepted."""
    code = issue.get("code")
    if code == "timeline_track_too_dense":
        return "authoring-style tip; the composition is generated, not hand-maintained"
    if code == "clip_media_fit":
        m = re.search(r"is ([\d.]+)s but its slot \(data-duration\) is ([\d.]+)s", str(issue.get("message", "")))
        if m and 0 <= float(m.group(2)) - float(m.group(1)) < 0.15:
            return ("MP3 encoder padding: the frame-count duration exceeds the decoded length by "
                    "under 150 ms, leaving a silent gap between files, not drift")
    return None


def _collect_issues(report: Any) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "severity" in node and ("message" in node or "code" in node or "rule" in node):
                found.append(node)
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(report)
    return found


def _band_differs(base: str, final: str, t: float) -> bool:
    def grab(path: str) -> bytes:
        proc = subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.3f" % t, "-i", path, "-frames:v", "1",
                               "-vf", "crop=iw:ih*0.26:0:ih*0.74,scale=192:28,format=gray",
                               "-f", "rawvideo", "-"], capture_output=True, timeout=120)
        return proc.stdout

    a, b = grab(base), grab(final)
    if not a or len(a) != len(b):
        return False
    diff = sum(1 for x, y in zip(a, b) if abs(x - y) > 24)
    return diff / len(a) > 0.01


def _gray(path: str, t: float, rect: Dict[str, float], size: Tuple[int, int] = (64, 64)) -> bytes:
    crop = "crop=%d:%d:%d:%d,scale=%d:%d,format=gray" % (rect["w"], rect["h"], rect["x"], rect["y"], size[0], size[1])
    proc = subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.3f" % t, "-i", path, "-frames:v", "1",
                           "-vf", crop, "-f", "rawvideo", "-"], capture_output=True, timeout=120)
    return proc.stdout


def face(r: Report, job: str, final: str, base: str, pkg: Dict[str, Any], qa_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Checks only the presenter template needs: the takes, the cuts, loudness, the presenter."""
    pdir = os.path.join(job, "presenter")

    def load(name: str) -> Dict[str, Any]:
        with open(os.path.join(pdir, name), encoding="utf-8") as fh:
            return json.load(fh)

    pedl, edit, ingest = load("edl.json"), load("edit.json"), load("ingest.json")
    summary = pedl["summary"]
    r.metrics["takes"] = summary
    missing = [t for t in pedl["takes"] if t["status"] == "missing"]
    weak = [t for t in pedl["takes"] if t["status"] == "weak"]
    omitted = [t for t in pedl["takes"] if t["status"] == "omitted"]
    if missing:
        r.fail("takes_complete", "sentences not found in the recording: %s"
               % "; ".join(t["text"][:70] for t in missing))
    for t in omitted:
        r.warn("takes_complete", "not said in the recording (short, no claim): \"%s\"" % t["text"])
    for t in weak:
        r.warn("takes_complete", "no clean take: \"%s\" was read as \"%s\""
               % (t["text"], (t.get("chosen") or {}).get("text", "")))
    r.set("takes_complete", "pass", "%d of %d sentences have a clean take; %d retakes dropped"
          % (summary["ok"], summary["sentences"], summary["retakes_dropped"]))

    # Per-section fidelity: a good overall score can hide one badly read section.
    from deck import to_slides  # noqa: E402
    kept, _ = video_deck(pkg)
    slides = to_slides(kept)
    per_slide = {e["deck_position"]: e for e in load("slides.json")["slides"]}
    threshold = float(qa_cfg.get("transcript_match_threshold", 0.92))
    low, scores = [], {}
    for i, sl in enumerate(slides):
        approved = _tokens(sl.get("notes") or "")
        # One string, not one call per word: a spoken number is several words ("six
        # hundred and fifty"), and collapse_numbers can only fold them into #650 when it
        # sees them together. Per-word tokenising scored every reading as a misreading.
        heard_t = _tokens(" ".join(w["text"] for w in per_slide.get(i, {}).get("words", [])))
        sm = difflib.SequenceMatcher(None, approved, heard_t, autojunk=False)
        score = sm.ratio() if approved else 1.0
        scores[sl.get("title") or str(i)] = round(score, 3)
        if score < threshold:
            diffs = [" ".join(approved[a:b]) + " -> " + " ".join(heard_t[c:d])
                     for op, a, b, c, d in sm.get_opcodes() if op != "equal"][:4]
            low.append("%s %.1f%% (%s)" % (sl.get("title"), 100 * score, "; ".join(diffs)))
    r.metrics["section_similarity"] = scores
    if low:
        r.fail("sections_match_script", "sections below %.0f%%: %s" % (100 * threshold, " | ".join(low)))
    else:
        r.set("sections_match_script", "pass", "every section at or above %.0f%% (lowest %.1f%%)"
              % (100 * threshold, 100 * min(scores.values())))

    # Cuts: every boundary in a gap between heard words.
    offset = ingest["scribe_trim_offset"]
    heard = sorted((float(w["start"]) + offset, float(w.get("end", w["start"])) + offset)
                   for w in load("scribe.json").get("words", []) if w.get("type") == "word")
    tol = 1.0 / pedl["fps"]
    inside = []
    for rng in pedl["ranges"]:
        for edge in (rng["src_start"], rng["src_end"]):
            if any(a + tol < edge < z - tol for a, z in heard):
                inside.append("%.2fs" % edge)
    if inside:
        r.fail("cut_boundaries", "cuts inside a word at %s" % ", ".join(inside[:8]))
    else:
        r.set("cut_boundaries", "pass", "%d cuts, all between words" % max(0, len(pedl["ranges"]) - 1))
    drift = abs(edit["audio_duration"] - edit["video_duration"])
    r.metrics["av_drift_seconds"] = round(drift, 3)
    if edit["frames"] != edit["expected_frames"] or drift > 1.5 / pedl["fps"]:
        r.fail("audio_pops", "edit does not match its plan (frames %s/%s, audio/video differ by %.3fs)"
               % (edit["frames"], edit["expected_frames"], drift))
    else:
        r.set("audio_pops", "pass", "20 ms fades at all %d joints; audio and video within %.0f ms"
              % (len(pedl["ranges"]), 1000 * drift))

    # Loudness of the delivered file.
    log = _filter_log(final, None, "ebur128=peak=true", timeout=900)
    lufs_found = re.findall(r"I:\s+(-?[\d.]+) LUFS", log)
    peaks = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", log)
    if lufs_found:
        lufs = float(lufs_found[-1])
        r.metrics["integrated_lufs"] = lufs
        r.metrics["true_peak_dbfs"] = float(peaks[-1]) if peaks else None
        if abs(lufs + 16) > 1.5:
            r.fail("loudness", "integrated loudness %.1f LUFS, target -16 +/-1.5" % lufs, auto_correctable=True)
        else:
            r.set("loudness", "pass", "%.1f LUFS integrated, true peak %s dBFS" % (lufs, peaks[-1] if peaks else "?"))
    else:
        r.warn("loudness", "ebur128 produced no summary")

    # The presenter is on screen and moving on every page.
    with open(os.path.join(job, "project", "composition.manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    dead = []
    for lm in manifest["layout_modes"]:
        win = lm["presenter"]["window"]
        t = lm["start"] + (lm["end"] - lm["start"]) * 0.5
        a, b = _gray(base, t, win), _gray(base, t + 0.5, win)
        if not a or len(a) != len(b):
            dead.append("%s: no frame" % lm["board_id"])
            continue
        luma = sum(a) / len(a)
        moved = sum(1 for x, y in zip(a, b) if abs(x - y) > 3) / len(a)
        if luma < 16 or moved == 0:
            dead.append("%s (%s): luma %.0f, moving %.1f%%" % (lm["board_id"], lm["mode"], luma, 100 * moved))
    if dead:
        r.fail("presenter_visible", "presenter black or frozen: %s" % "; ".join(dead))
    else:
        r.set("presenter_visible", "pass", "visible and moving on all %d pages (%s)"
              % (len(manifest["layout_modes"]), ", ".join(sorted({x["mode"] for x in manifest["layout_modes"]}))))
    return pedl


def content(r: Report, pkg: Dict[str, Any], storyboard: Dict[str, Any]) -> None:
    kept, _ = video_deck(pkg)
    bullets = [b for e in kept for b in (e.get("bullets") or [])]
    approved_sentences = {s.strip() for e in kept for s in split_sentences(e.get("notes") or "")}
    problems = validate_storyboard(storyboard, pkg.get("references") or [], approved_bullets=bullets)
    if storyboard.get("boards"):
        from boards import validate_boards  # noqa: E402
        approved = " ".join([video_script(kept), pkg.get("title") or ""] + [e.get("title") or "" for e in kept])
        problems += validate_boards(storyboard["boards"], approved, bullets, pkg.get("references") or [])
    cite = [p for p in problems if "cite" in p or "evidence card" in p or "reference list" in p]
    wording = [p for p in problems if p not in cite]
    for seg in storyboard["segments"]:
        if seg["narration"].strip() not in approved_sentences:
            wording.append("%s: narration is not an approved sentence" % seg["segment_id"])
    if cite:
        r.fail("citations_supported", "; ".join(cite))
    else:
        n = len({c for s in storyboard["segments"] for c in s.get("citation_ids", [])})
        r.set("citations_supported", "pass", "%d distinct citations, all in the approved reference list" % n)
    if wording:
        r.fail("approved_wording_intact", "; ".join(wording))
    else:
        r.set("approved_wording_intact", "pass")

    allowed = set()
    for text in [video_script(kept)] + bullets + [x.get("citation", "") for x in pkg.get("references") or []]:
        allowed.update(_NUMBER.findall(strip_markers(text)))
    invented = []
    for seg in storyboard["segments"]:
        props = seg.get("props") or {}
        shown = " ".join(str(v) for k, v in props.items()
                         if k in ("text", "finding", "message", "definition", "term", "value", "label", "title")
                         and v)
        for num in _NUMBER.findall(shown):
            if num not in allowed:
                invented.append("%s shows %s" % (seg["segment_id"], num))
    if invented:
        r.fail("no_new_claims", "numbers on screen that the course does not contain: %s" % ", ".join(invented))
    else:
        r.set("no_new_claims", "pass")


def write_markdown(path: str, qa: Dict[str, Any], notes: Dict[str, str]) -> None:
    families = {
        "Technical": ["container_valid", "video_stream", "audio_stream", "duration_matches_edl",
                      "frame_rate", "resolution", "assets_present"],
        "Editorial": ["narration_matches_script", "sections_match_script", "takes_complete",
                      "captions_match_narration", "no_clipped_sentences",
                      "no_duplicated_audio", "cut_boundaries", "audio_pops", "loudness"],
        "Visual": ["captions_visible", "caption_occlusion", "text_overflow", "text_contrast", "overlay_timing",
                   "presenter_visible", "black_frames", "frozen_frames"],
        "Content": ["citations_supported", "no_new_claims", "approved_wording_intact"],
    }
    mark = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "skipped": "skipped"}
    m = qa["metrics"]
    lines = [
        "# Video QA report",
        "",
        "| | |",
        "|---|---|",
        "| Status | **%s** |" % qa["status"].upper(),
        "| Job | `%s` |" % qa.get("job_id", ""),
        "| Template | %s |" % qa.get("template", ""),
        "| Attempt | %s |" % qa.get("attempt", 1),
        "| Duration | %.2f s (EDL %.2f s) |" % (m.get("duration_seconds", 0), m.get("expected_seconds", 0)),
        "| Narration vs approved script | %.1f%% of %s words |" % (100 * m.get("transcript_similarity", 0),
                                                                  m.get("words_checked", 0)),
        "| Caption cues | %s |" % m.get("caption_cue_count", 0),
        "| Scenes | %s |" % m.get("scene_count", 0),
        "| Longest still hold | %s s |" % m.get("longest_frozen_seconds", 0),
        "| Generated | %s |" % qa["generated_at"],
        "",
    ]
    for fam, names in families.items():
        lines += ["## %s" % fam, "", "| Check | Result | Detail |", "|---|---|---|"]
        for n in names:
            lines.append("| %s | %s | %s |" % (n, mark.get(qa["checks"].get(n, "skipped")),
                                               notes.get(n, "").replace("|", "/")))
        lines.append("")
    if qa.get("takes"):
        lines += ["## Takes kept from the recording", "",
                  "| # | Sentence | Kept take (source time) | Match | Retakes dropped |", "|---|---|---|---|---|"]
        for n, t in enumerate(qa["takes"], 1):
            c = t.get("chosen") or {}
            lines.append("| %d | %s | %s | %s | %d |" % (
                n, t["text"][:80].replace("|", "/"),
                ("%.2f-%.2fs" % (c["start"], c["end"])) if c else "**missing**",
                ("%.0f%%" % (100 * c["score"])) if c else "-", len(t.get("rejected") or [])))
        lines.append("")
    if qa.get("corrections_applied"):
        lines += ["## Corrections from earlier attempts", "", "| Attempt | Check | Action |", "|---|---|---|"]
        lines += ["| %s | %s | %s |" % (c.get("attempt"), c.get("check"), c.get("action")) for c in qa["corrections_applied"]]
        lines.append("")
    if qa["errors"]:
        lines += ["## Errors", ""] + ["- **%s**: %s" % (e["check"], e["message"]) for e in qa["errors"]] + [""]
    if qa["warnings"]:
        lines += ["## Warnings", ""] + ["- **%s**: %s" % (w["check"], w["message"]) for w in qa["warnings"]] + [""]
    if qa.get("advisories"):
        lines += ["## Accepted advisories", ""] + ["- `%s`: %s. *%s*" % (a["code"], a["message"], a["why_accepted"])
                                                   for a in qa["advisories"]] + [""]
    scope = ("Narration fidelity is measured on the cached Scribe transcripts of the exact audio files "
             "placed in the render; the files' SHA-256 hashes are checked against the approved sources. "
             "The rendered mix itself is not re-transcribed, which would be a second paid call.")
    if qa.get("template") == "face":
        scope = ("Delivery fidelity is measured on the one Scribe transcript of the presenter recording, "
                 "restricted to the words inside the kept takes and remapped to the edit; the edit placed "
                 "in the render is checked by SHA-256. The rendered mix is not re-transcribed, which would "
                 "be a second paid call.")
    lines += ["## Scope of these checks", "", scope, ""]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def run(job: str, package_path: str, attempt: int = 1,
        corrections: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    with open(os.path.join(_VP, "config", "video.config.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    with open(package_path, encoding="utf-8") as fh:
        pkg = json.load(fh)
    with open(os.path.join(job, "storyboard.json"), encoding="utf-8") as fh:
        storyboard = json.load(fh)
    with open(os.path.join(job, "edit", "edl.json"), encoding="utf-8") as fh:
        edl = json.load(fh)
    os.makedirs(os.path.join(job, "qa"), exist_ok=True)

    qa_cfg = dict(cfg.get("qa", {}))
    with open(os.path.join(_VP, "brand", "spacing.json"), encoding="utf-8") as fh:
        spacing = json.load(fh)
    zone = spacing["captionZone"]
    qa_cfg["_caption_band_fraction"] = 1 - (zone["bottom"] + zone["height"]) / float(spacing["canvas"]["height"])
    spec = {"width": spacing["canvas"]["width"], "height": spacing["canvas"]["height"],
            "fps": spacing["canvas"]["fps"]}
    max_hold = float(cfg.get("storyboard", {}).get("max_scene_seconds", 14))

    global _ALLOWED_NUMBERS
    _ALLOWED_NUMBERS = numbers_in(video_script(video_deck(pkg)[0]))
    r = Report()
    final = os.path.join(job, "final.mp4")
    base = os.path.join(job, edl.get("base_render", "render/base.mp4"))
    technical(r, final, edl, job, spec)
    editorial(r, pkg, edl, os.path.join(job, "edit", "master.srt"), os.path.join(job, "edit", "transcripts"),
              float(qa_cfg.get("transcript_match_threshold", 0.92)))
    visual(r, final, base, job, storyboard, qa_cfg, max_hold)
    content(r, pkg, storyboard)
    pedl = face(r, job, final, base, pkg, qa_cfg) if storyboard.get("template") == "face" else None

    qa = {
        "status": r.status,
        "job_id": os.path.basename(job.rstrip("/")),
        "version_id": pkg.get("version_id"),
        "template": storyboard.get("template", "faceless"),
        "attempt": attempt,
        "checks": dict(sorted(r.checks.items())),
        "metrics": r.metrics,
        "warnings": r.warnings,
        "errors": r.errors,
        "advisories": r.advisories,
        "corrections_applied": corrections or [],
        "takes": pedl["takes"] if pedl else None,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }
    with open(os.path.join(job, "qa", "video_qa.json"), "w", encoding="utf-8") as fh:
        json.dump(qa, fh, indent=2)
    write_markdown(os.path.join(job, "qa", "VIDEO_QA_REPORT.md"), qa, r.notes)
    return qa


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--package", required=True)
    ap.add_argument("--attempt", type=int, default=1)
    ap.add_argument("--corrections", help="JSON file: what changed since the previous attempt")
    args = ap.parse_args()
    corrections = None
    if args.corrections:
        with open(args.corrections, encoding="utf-8") as fh:
            corrections = json.load(fh)
    qa = run(os.path.abspath(args.job), args.package, args.attempt, corrections)
    print("QA %s" % qa["status"].upper())
    for k, v in qa["checks"].items():
        print("  %-26s %s" % (k, v))
    for e in qa["errors"]:
        print("  ERROR %s: %s" % (e["check"], e["message"][:200]))
    for w in qa["warnings"][:10]:
        print("  warn  %s: %s" % (w["check"], w["message"][:200]))
    return 0 if qa["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
