"""Prepare a presenter recording for editing and rendering.

    python3 video-production/presenter/ingest.py --job /data/video-jobs/<id> \
        --source /data/video-jobs/<id>/source/recording.mp4

Writes into <job>/presenter/:

    proxy.mp4          H.264, CFR 30, a keyframe every second, yuv420p, loudness-normalised
                       AAC. Headless Chrome cannot decode HEVC (phones record it), and a
                       sparse GOP freezes when the renderer seeks frame by frame.
    room_tone.wav      the silent lead-in, kept for patching gaps
    scribe.wav         16 kHz mono speech with the silent lead-in trimmed: Scribe bills per
                       second, and the lead-in holds no words
    ingest.json        probe, loudness, trim offset, framing (subject centre, bright zones)

Nothing here calls a paid service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

import numpy as np

LUFS, TP, LRA = -16.0, -1.5, 11.0


def run(cmd, timeout: int, capture: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError("%s failed (%d): %s" % (cmd[0], proc.returncode, (proc.stderr or "")[-1500:]))
    return proc


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(path: str) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path], 120).stdout
    d = json.loads(out)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    num, den = (int(x) for x in v["avg_frame_rate"].split("/"))
    return {"duration": float(d["format"]["duration"]), "width": v["width"], "height": v["height"],
            "video_codec": v["codec_name"], "fps": round(num / den, 3) if den else None,
            "vfr": v["avg_frame_rate"] != v["r_frame_rate"], "pix_fmt": v.get("pix_fmt"),
            "color_transfer": v.get("color_transfer"),
            "audio_codec": a and a["codec_name"], "sample_rate": a and int(a["sample_rate"]),
            "channels": a and a["channels"]}


def leading_silence(path: str, timeout: int) -> float:
    """Where speech starts: the end of a silence that begins at the top of the file."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-t", "60", "-i", path, "-vn",
                          "-af", "silencedetect=noise=-38dB:d=0.7", "-f", "null", "-"],
                         capture_output=True, text=True, timeout=timeout).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    if starts and ends and starts[0] < 1.0:
        return ends[0]
    return 0.0


def loudness_pass1(path: str, timeout: int) -> dict:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn", "-af",
                          "loudnorm=I=%s:TP=%s:LRA=%s:print_format=json" % (LUFS, TP, LRA), "-f", "null", "-"],
                         capture_output=True, text=True, timeout=timeout).stderr
    return json.loads(err[err.rindex("{"): err.rindex("}") + 1])


def framing(path: str, duration: float, timeout: int, strips: int = 32) -> dict:
    """Subject centre from motion energy.

    A talking head moves; the room does not. Frame differences summed per column
    peak where the presenter is. Brightness per column flags windows and lamps that
    make overlaid text hard to read.
    """
    w, h = 320, 180
    start = min(15.0, duration * 0.1)
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", str(start), "-t", str(max(10.0, duration - start - 2)),
                           "-i", path, "-an", "-vf", "fps=2,scale=%d:%d,format=gray" % (w, h),
                           "-f", "rawvideo", "-"], capture_output=True, timeout=timeout, check=True)
    frames = np.frombuffer(proc.stdout, dtype=np.uint8)
    frames = frames[: (len(frames) // (w * h)) * w * h].reshape(-1, h, w).astype(np.float32)
    diff = np.abs(np.diff(frames, axis=0)).mean(axis=0)            # h x w
    col_motion = diff.mean(axis=0)
    col_luma = frames.mean(axis=(0, 1))
    per = w // strips
    motion = [float(col_motion[i * per:(i + 1) * per].mean()) for i in range(strips)]
    luma = [float(col_luma[i * per:(i + 1) * per].mean()) for i in range(strips)]
    # Weighted centroid of the motion above the room's noise floor.
    m = np.array(motion)
    floor = np.percentile(m, 30)
    weights = np.clip(m - floor, 0, None)
    centers = (np.arange(strips) + 0.5) / strips
    cx = float((weights * centers).sum() / weights.sum()) if weights.sum() > 0 else 0.5
    # Horizontal extent: the strips moving at least a third as much as the busiest one,
    # widened by a strip each side. A share-of-total rule reads a handheld phone's
    # shake (small motion everywhere) as a presenter as wide as the frame.
    if weights.max() > 0:
        busy = np.nonzero(weights >= weights.max() * 0.35)[0]
        lo = max(0.0, (busy.min() - 1) / strips)
        hi = min(1.0, (busy.max() + 2) / strips)
    else:
        lo, hi = 0.3, 0.7
    # Vertical: rows with motion, for the head position.
    row_motion = diff[:, int(lo * w):int(hi * w) + 1].mean(axis=1)
    rfloor = np.percentile(row_motion, 30)
    rw = np.clip(row_motion - rfloor, 0, None)
    rows = np.nonzero(rw > rw.max() * 0.25)[0] if rw.max() > 0 else np.array([0])
    # Where the face is vertically: the centroid of that motion (mouth and eyes move most).
    cy = float((rw * (np.arange(h) + 0.5)).sum() / rw.sum() / h) if rw.sum() > 0 else 0.45
    bright = [round(i / strips, 3) for i, v in enumerate(luma) if v > 170]
    return {"method": "motion energy, %d strips, 2 fps, %dx%d" % (strips, w, h),
            "subject_center_x": round(cx, 4), "subject_extent_x": [round(lo, 3), round(hi, 3)],
            "subject_top_y": round(float(rows.min()) / h, 3),
            "subject_center_y": round(cy, 4),
            "motion_by_strip": [round(v, 2) for v in motion],
            "luma_by_strip": [round(v, 1) for v in luma],
            "bright_strips_x": bright}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--preset", default="veryfast")
    ap.add_argument("--framing-only", action="store_true", help="re-measure framing on the existing proxy")
    args = ap.parse_args()
    out = os.path.join(args.job, "presenter")
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    if args.framing_only:
        path = os.path.join(out, "ingest.json")
        with open(path, encoding="utf-8") as fh:
            meta = json.load(fh)
        meta["framing"] = framing(meta["proxy"], meta["proxy_duration"], 1800)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
        print(json.dumps({k: v for k, v in meta["framing"].items() if "strip" not in k}))
        return 0

    info = probe(args.source)
    budget = int(max(900, info["duration"] * 20))
    lead = leading_silence(args.source, 300)
    meas = loudness_pass1(args.source, budget)
    loud = ("loudnorm=I={I}:TP={TP}:LRA={LRA}:measured_I={mi}:measured_TP={mtp}:measured_LRA={mlra}:"
            "measured_thresh={mth}:offset={off}:linear=true").format(
        I=LUFS, TP=TP, LRA=LRA, mi=meas["input_i"], mtp=meas["input_tp"], mlra=meas["input_lra"],
        mth=meas["input_thresh"], off=meas["target_offset"])

    proxy = os.path.join(out, "proxy.mp4")
    run(["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", args.source,
         "-map", "0:v:0", "-map", "0:a:0",
         "-vf", "fps=30,scale=1920:1080:flags=lanczos,format=yuv420p",
         "-c:v", "libx264", "-preset", args.preset, "-crf", "18", "-g", "30", "-keyint_min", "30",
         "-sc_threshold", "0", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
         "-af", loud + ",aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", proxy], budget)

    tone_end = max(0.0, lead - 0.3)
    if tone_end >= 1.0:
        run(["ffmpeg", "-y", "-hide_banner", "-nostats", "-ss", "0.5", "-t", str(min(10.0, tone_end - 0.5)),
             "-i", proxy, "-vn", "-ac", "1", "-ar", "48000", os.path.join(out, "room_tone.wav")], 120)

    trim = max(0.0, lead - 0.5)
    scribe = os.path.join(out, "scribe.wav")
    run(["ffmpeg", "-y", "-hide_banner", "-nostats", "-ss", "%.3f" % trim, "-i", args.source, "-vn",
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", scribe], 300)

    pinfo = probe(proxy)
    meta = {
        "source": args.source, "source_sha256": sha256(args.source), "source_probe": info,
        "proxy": proxy, "proxy_duration": pinfo["duration"], "proxy_probe": pinfo,
        "loudness_measured": meas, "loudness_target": {"I": LUFS, "TP": TP, "LRA": LRA},
        "speech_starts_at": round(lead, 3),
        "scribe_wav": scribe, "scribe_trim_offset": round(trim, 3),
        "scribe_seconds": round(info["duration"] - trim, 2), "scribe_sha256": sha256(scribe),
        "framing": framing(proxy, pinfo["duration"], budget),
        "seconds": round(time.time() - t0, 1),
    }
    with open(os.path.join(out, "ingest.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    print(json.dumps({k: meta[k] for k in ("proxy_duration", "speech_starts_at", "scribe_seconds", "seconds")}))
    print(json.dumps({k: v for k, v in meta["framing"].items() if "strip" not in k}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
