"""Output timeline for a course video: EDL, captions, burn-in, preview.

    python video-production/editing/timeline.py \
        --job /data/video-jobs/rlt-v3-faceless \
        --storyboard storyboard.json --base render/base.mp4

Writes, inside the job directory, the same artifacts video-use produces:

    edit/edl.json        which narration plays where on the output timeline
    edit/master.srt      output-timeline captions (video-use's own builder)
    final.mp4            base render + captions burned in LAST
    preview.mp4          small review copy of final.mp4

video-use's rules that apply here, and where they are enforced:

* Subtitles are applied LAST, after every overlay: the HyperFrames render already
  contains every visual, and this module only ever adds captions on top of it.
* SRT times are on the OUTPUT timeline: each cue is `word.start - range.start +
  range.output_start`, computed by video-use's `build_master_srt` from this EDL.
* Transcripts are cached and never re-requested here.

The faceless template never cuts narration: every approved file plays whole, in deck
order. Its EDL is therefore a list of whole-file ranges, and `output_start` for each is
the same cumulative offset the composition used to place the audio. Both are read from
the storyboard's `narration_plan`, so the captions cannot drift from the picture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_VP = os.path.dirname(_HERE)


def _video_use_helpers() -> str:
    for base in (os.environ.get("VIDEO_USE_HOME"), os.path.join(_VP, "vendor", "video-use")):
        if base and os.path.isdir(os.path.join(base, "helpers")):
            return os.path.join(base, "helpers")
    raise RuntimeError("video-use helpers not found (set VIDEO_USE_HOME)")


def _brand() -> Dict[str, Any]:
    out = {}
    for name in ("colors", "typography", "spacing"):
        with open(os.path.join(_VP, "brand", name + ".json"), encoding="utf-8") as fh:
            out[name] = json.load(fh)
    return out


def _ass_colour(hex_rgb: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR, the byte order libass expects."""
    h = hex_rgb.lstrip("#")
    return "&H%02X%s%s%s" % (alpha, h[4:6], h[2:4], h[0:2])


def caption_style(height: int = 1080) -> str:
    """libass force_style from the brand tokens.

    video-use's default (Helvetica 18, MarginV=90) is tuned for vertical social video,
    where platform UI covers the bottom third. A course plays in an LMS player, so the
    caption sits in the band `brand/spacing.json` reserves for it — the band no visual
    is allowed to occupy. libass scales SRT styles against PlayResY=288, so pixel
    tokens are converted to that space.
    """
    b = _brand()
    scale = 288.0 / height
    zone = b["spacing"]["canvas"]["captionZone"] if "canvas" in b["spacing"] and \
        "captionZone" in b["spacing"]["canvas"] else b["spacing"]["captionZone"]
    size = b["typography"]["scale"]["caption"]["size"]
    navy = b["colors"]["ink"]["navy"]
    white = b["colors"]["caption"]["text"]
    return ",".join([
        "FontName=Montserrat",
        "FontSize=%d" % round(size * scale),
        "Bold=1",
        "PrimaryColour=%s" % _ass_colour(white),
        # BorderStyle=3 draws an opaque box in OutlineColour: legible on the light page
        # and on the dark title/recap scenes alike, where an outline alone is not.
        "BorderStyle=3",
        "OutlineColour=%s" % _ass_colour(navy, alpha=0x30),
        "BackColour=%s" % _ass_colour(navy, alpha=0x30),
        "Outline=%d" % max(2, round(14 * scale)),
        "Shadow=0",
        "Alignment=2",
        "MarginV=%d" % round((zone["bottom"] + 24) * scale),
    ])


def build_edl(storyboard: Dict[str, Any], source_dir: str, base_render: str) -> Dict[str, Any]:
    sources: Dict[str, str] = {}
    ranges: List[Dict[str, Any]] = []
    clock = 0.0
    for entry in storyboard.get("narration_plan", []):
        idx, seconds = entry.get("audio_index"), entry.get("seconds")
        if idx is None or not seconds:
            raise ValueError("narration_plan entry without audio or duration: %r" % entry)
        name = "audio_%02d" % int(idx)
        sources[name] = os.path.join(source_dir, name + ".mp3")
        beats = [s["segment_id"] for s in storyboard.get("segments", [])
                 if s.get("slide_index") == entry.get("deck_position")]
        ranges.append({
            "source": name,
            "start": 0.0,
            "end": round(float(seconds), 3),
            "output_start": round(clock, 3),
            "beat_ids": beats,
            "note": entry.get("title") or "",
            "reason": "Approved narration, played whole: the faceless template never cuts approved speech.",
        })
        clock += float(seconds)
    return {
        "version": 1,
        "template": storyboard.get("template", "faceless"),
        "sources": sources,
        "ranges": ranges,
        "overlays": [],
        "base_render": base_render,
        "subtitles": "master.srt",
        "total_seconds": round(clock, 3),
        "dropped_narration": storyboard.get("dropped_narration", []),
    }


def build_edl_face(storyboard: Dict[str, Any], job: str, base_render: str) -> Dict[str, Any]:
    """The face template: one source, the presenter edit, played whole.

    The cutting already happened in presenter/edit.py (its plan is presenter/edl.json,
    copied beside this one); on the output timeline the edit is a single range, and its
    transcript is the kept words remapped to that timeline.
    """
    pdir = os.path.join(job, "presenter")
    with open(os.path.join(pdir, "edit.json"), encoding="utf-8") as fh:
        edit = json.load(fh)
    total = round(min(edit["video_duration"], edit["audio_duration"]) or edit["duration"], 3)
    return {
        "version": 1,
        "template": "face",
        "sources": {"presenter": os.path.join(pdir, "edit.mp4")},
        "ranges": [{"source": "presenter", "start": 0.0, "end": total, "output_start": 0.0,
                    "beat_ids": [s["segment_id"] for s in storyboard.get("segments", [])],
                    "note": "presenter edit",
                    "reason": "Kept takes of the presenter recording, cut in presenter/edit.py "
                              "(plan: presenter_edl.json)."}],
        "overlays": [],
        "base_render": base_render,
        "subtitles": "master.srt",
        "total_seconds": total,
        "presenter_edl": "presenter_edl.json",
        "dropped_narration": storyboard.get("dropped_narration", []),
    }


def build_srt(edl: Dict[str, Any], edit_dir: str) -> str:
    sys.path.insert(0, _video_use_helpers())
    import render as video_use_render  # noqa: E402  (video-use/helpers/render.py)

    out = os.path.join(edit_dir, "master.srt")
    video_use_render.build_master_srt(edl, Path(edit_dir), Path(out))
    return out


def run_ffmpeg(args: List[str], timeout: int) -> None:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args,
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed: %s" % proc.stderr.strip()[-1500:])


def burn_captions(base: str, srt: str, out: str, duration: float,
                  fonts_dir: str = "/usr/share/fonts/truetype/montserrat") -> None:
    """Captions LAST. The `subtitles` filter forces a full re-encode; budget for it."""
    esc = srt.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    vf = "subtitles='%s':fontsdir='%s':force_style='%s'" % (esc, fonts_dir, caption_style())
    run_ffmpeg(["-i", base, "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out],
               timeout=max(900, int(duration * 20)))


def make_preview(final: str, out: str, duration: float) -> None:
    run_ffmpeg(["-i", final, "-vf", "scale=960:-2", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "28", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", out],
               timeout=max(600, int(duration * 10)))


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True, help="job directory")
    ap.add_argument("--storyboard", default="storyboard.json")
    ap.add_argument("--base", default="render/base.mp4")
    ap.add_argument("--skip-burn", action="store_true")
    args = ap.parse_args()

    job = os.path.abspath(args.job)
    edit_dir = os.path.join(job, "edit")
    with open(os.path.join(job, args.storyboard), encoding="utf-8") as fh:
        storyboard = json.load(fh)

    os.makedirs(os.path.join(edit_dir, "transcripts"), exist_ok=True)
    if storyboard.get("template") == "face":
        import shutil
        edl = build_edl_face(storyboard, job, args.base)
        shutil.copyfile(os.path.join(job, "presenter", "transcript.json"),
                        os.path.join(edit_dir, "transcripts", "presenter.json"))
        shutil.copyfile(os.path.join(job, "presenter", "edl.json"), os.path.join(edit_dir, "presenter_edl.json"))
    else:
        edl = build_edl(storyboard, os.path.join(job, "source"), args.base)
    with open(os.path.join(edit_dir, "edl.json"), "w", encoding="utf-8") as fh:
        json.dump(edl, fh, indent=2)
    srt = build_srt(edl, edit_dir)
    print("edl: %d ranges, %.1fs" % (len(edl["ranges"]), edl["total_seconds"]))

    if not args.skip_burn:
        base = os.path.join(job, args.base)
        final = os.path.join(job, "final.mp4")
        burn_captions(base, srt, final, edl["total_seconds"])
        make_preview(final, os.path.join(job, "preview.mp4"), edl["total_seconds"])
        print("final: %s" % final)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
