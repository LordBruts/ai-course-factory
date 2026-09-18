"""Storyboard + approved narration -> a renderable HyperFrames project.

    python video-production/rendering/build_project.py \
        --storyboard samples/faceless/storyboard.json \
        --audio-dir samples/source \
        --out .work/faceless-project

Narration placement is the load-bearing part: each approved audio file starts where
its deck entry starts, and those offsets are the same cumulative sums the storyboard
used for beat timing. If the two ever disagreed, every visual would drift against the
voice, so both read the one `narration_plan` written by the storyboard.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_VP = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_VP, "templates", "faceless"))
sys.path.insert(0, os.path.join(_VP, "editing"))

from composition import build_composition  # noqa: E402


def narration_items(storyboard: dict, audio_dir: str) -> list:
    """Approved narration files, in deck order, each with its start offset."""
    items = []
    clock = 0.0
    for entry in storyboard.get("narration_plan", []):
        seconds = entry.get("seconds")
        index = entry.get("audio_index")
        if index is None:
            continue
        path = os.path.join(audio_dir, "audio_%02d.mp3" % int(index))
        if not os.path.exists(path):
            raise SystemExit("missing approved narration file: %s" % path)
        if seconds is None:
            from audio_probe import mp3_duration  # local, no ffprobe needed
            seconds = mp3_duration(path) or 0.0
        items.append({"index": int(index), "path": path, "start": round(clock, 3),
                      "seconds": round(float(seconds), 3)})
        clock += float(seconds)
    return items


def build_face(storyboard: dict, args) -> int:
    sys.path.insert(0, os.path.join(_VP, "templates", "face"))
    from face_composition import build_face_composition  # noqa: E402
    if not args.presenter_dir:
        raise SystemExit("--presenter-dir is required for the face template")
    pdir = args.presenter_dir

    def load(name: str) -> dict:
        with open(os.path.join(pdir, name), encoding="utf-8") as fh:
            return json.load(fh)

    edit = load("edit.json")
    manifest = build_face_composition(
        storyboard, args.out, presenter_video=os.path.join(pdir, "edit.mp4"),
        edl=load("edl.json"), framing=load("ingest.json")["framing"],
        # The picture runs exactly as long as the edited presenter video.
        total_seconds=min(edit["video_duration"], edit["audio_duration"]) or edit["duration"],
        width=args.width, height=args.height, fps=args.fps,
        font_dir=args.fonts if os.path.isdir(args.fonts) else None,
        course_title=args.title or storyboard.get("course_slug", ""),
        # The presenter is composited in afterwards (rendering/composite.py); in the page
        # he costs ~8x the capture time and stalls the render on this host.
        presenter_layer=args.presenter_layer)
    print("project: %s (face)" % args.out)
    print("  %.1fs · %d board elements · %d presenter moves · %d punch-ins"
          % (manifest["duration"], len(manifest["clips"]), len(manifest["transitions"]), len(manifest["punch_ins"])))
    for m in manifest["layout_modes"]:
        print("    %s %-6s %6.1fs-%6.1fs" % (m["board_id"], m["mode"], m["start"], m["end"]))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--storyboard", required=True)
    ap.add_argument("--audio-dir", help="approved narration files (faceless)")
    ap.add_argument("--presenter-dir", help="<job>/presenter: edit.mp4, edl.json, ingest.json (face)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fonts", default="/usr/share/fonts/truetype/montserrat")
    ap.add_argument("--title", default="")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--presenter-layer", action="store_true",
                    help="face: put the presenter video in the page (slow; renders in Chrome) "
                         "instead of compositing it afterwards")
    args = ap.parse_args()

    with open(args.storyboard, encoding="utf-8") as fh:
        storyboard = json.load(fh)

    if storyboard.get("template") == "face":
        return build_face(storyboard, args)
    if not args.audio_dir:
        raise SystemExit("--audio-dir is required for the faceless template")

    audio = narration_items(storyboard, args.audio_dir)
    total_audio = sum(a["seconds"] for a in audio) if audio else None
    # The picture runs as long as the voice; the storyboard's own total is the
    # fallback for a silent build (a template preview, for instance).
    total = total_audio or storyboard.get("total_seconds")

    manifest = build_composition(
        storyboard, args.out,
        narration=audio,
        total_seconds=total,
        width=args.width, height=args.height, fps=args.fps,
        font_dir=args.fonts if os.path.isdir(args.fonts) else None,
        course_title=args.title or storyboard.get("course_slug", ""),
    )

    print("project: %s" % args.out)
    print("  %.1fs · %d clips · %d narration files · %d quiet beats"
          % (manifest["duration"], len(manifest["clips"]), len(manifest["audio"]),
             len(manifest["quiet_segments"])))
    if manifest.get("boards"):
        for b in manifest["boards"]:
            print("    %s %-8s %6.1fs-%6.1fs  %d elements" % (b["board_id"], b["kind"], b["start"], b["end"],
                                                         sum(1 for r in b["rects"] if r["kind"] != "title")))
        return 0
    for clip in manifest["clips"]:
        print("    %-5s %6.1fs +%5.1fs  %-16s %s"
              % (clip["segment_id"], clip["start"], clip["duration"], clip["component"],
                 (clip.get("reason") or "")[:64]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
