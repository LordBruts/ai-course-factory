"""Cut the presenter proxy to the kept takes.

    python3 video-production/presenter/edit.py --job /data/video-jobs/<id>

Reads <job>/presenter/edl.json and writes <job>/presenter/edit.mp4.

Each range is encoded on its own (accurate seek: the proxy has a keyframe every
second) with PCM audio and 20 ms fades at both ends, so a joint never clicks.
The segments are joined with the concat demuxer, and only then is the audio
encoded to AAC, once. Encoding AAC per segment would add ~21 ms of encoder
priming at every joint, and over forty joints the picture would drift almost a
second ahead of the voice.

Segment lengths are whole frames (takes.py snaps them), so the output timeline is
exactly the EDL's out_start/out_end.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

FADE = 0.02


def run(cmd, timeout: int) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError("%s failed (%d): %s" % (cmd[0], proc.returncode, proc.stderr[-1500:]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--preset", default="veryfast")
    args = ap.parse_args()
    pdir = os.path.join(args.job, "presenter")
    with open(os.path.join(pdir, "edl.json"), encoding="utf-8") as fh:
        edl = json.load(fh)
    fps = edl["fps"]
    seg_dir = os.path.join(pdir, "segments")
    shutil.rmtree(seg_dir, ignore_errors=True)
    os.makedirs(seg_dir)
    t0 = time.time()

    listing = []
    for n, r in enumerate(edl["ranges"]):
        frames = r["frames"]
        dur = frames / fps
        out = os.path.join(seg_dir, "seg_%03d.mov" % n)
        fade = "afade=t=in:d=%s,afade=t=out:st=%.4f:d=%s,apad,atrim=0:%.4f" % (FADE, max(0.0, dur - FADE), FADE, dur)
        run(["ffmpeg", "-y", "-hide_banner", "-nostats", "-ss", "%.4f" % r["src_start"], "-i", edl["source"],
             # Length is set per stream: the frame count for video, atrim for audio. A
             # shared -t rounds some segments down a frame, and the joins then drift.
             "-frames:v", str(frames),
             "-map", "0:v:0", "-map", "0:a:0",
             "-c:v", "libx264", "-preset", args.preset, "-crf", "18", "-g", "30", "-keyint_min", "30",
             "-sc_threshold", "0", "-pix_fmt", "yuv420p", "-r", str(fps),
             "-af", fade, "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
             # QuickTime with a frame-exact timescale: Matroska stores milliseconds, and the
             # rounding left a one-frame hole at every other joint.
             "-video_track_timescale", str(fps * 1000), out],
            timeout=int(max(300, dur * 30)))
        got = int(subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
                                  "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", out],
                                 capture_output=True, text=True).stdout.strip() or 0)
        if got != frames:
            raise RuntimeError("segment %d has %d frames, expected %d" % (n, got, frames))
        listing.append("file '%s'" % out)

    concat_list = os.path.join(seg_dir, "list.txt")
    with open(concat_list, "w", encoding="utf-8") as fh:
        fh.write("\n".join(listing) + "\n")
    joined = os.path.join(seg_dir, "joined.mov")
    run(["ffmpeg", "-y", "-hide_banner", "-nostats", "-f", "concat", "-safe", "0", "-i", concat_list,
         "-c", "copy", joined], 600)
    final = os.path.join(pdir, "edit.mp4")
    run(["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", joined, "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", final], 900)

    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", final],
        capture_output=True, text=True, check=True).stdout)
    streams = {s["codec_type"]: s for s in probe["streams"]}
    pts = sorted(float(x) for x in subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time", "-of", "csv=p=0", final],
        capture_output=True, text=True, check=True).stdout.split())
    holes = [round(a, 3) for a, b in zip(pts, pts[1:]) if b - a > 1.5 / fps]
    report = {"output": final, "expected_duration": edl["output_duration"],
              "duration": float(probe["format"]["duration"]),
              "video_duration": float(streams["video"].get("duration") or 0),
              "audio_duration": float(streams["audio"].get("duration") or 0),
              "frames": int(streams["video"].get("nb_frames") or 0),
              "expected_frames": sum(r["frames"] for r in edl["ranges"]),
              "timestamp_holes": holes,
              "segments": len(edl["ranges"]), "seconds": round(time.time() - t0, 1)}
    with open(os.path.join(pdir, "edit.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    shutil.rmtree(seg_dir, ignore_errors=True)
    print(json.dumps(report, indent=1))
    drift = abs(report["audio_duration"] - report["video_duration"])
    if report["frames"] != report["expected_frames"] or drift > 1.5 / fps or holes:
        print("edit does not match the EDL (frames %d/%d, a/v drift %.3fs, holes at %s)"
              % (report["frames"], report["expected_frames"], drift, holes[:5]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
