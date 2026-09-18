"""Run one faceless video job end to end inside the worker.

    python3 video-production/rendering/run_job.py --job /data/video-jobs/<id> \
        --title "Course title" [--attempt N] [--corrections file.json]

Steps, each logged to <job>/render/<step>.log with its duration in run.json:

    build     storyboard -> HyperFrames project        (rendering/build_project.py)
    lint      hyperframes lint, errors stop the job
    render    hyperframes render -> render/base.mp4
    timeline  EDL, captions burned in last, preview      (editing/timeline.py)
    qa        video_qa.json + VIDEO_QA_REPORT.md         (qa/checks.py)

A step is retried only for failures known to be transient on this host, and only by
their exact message: HyperFrames' FFmpeg preflight gives `ffmpeg -version` five
seconds and intermittently loses that race, and page loads occasionally exceed the
navigation budget. Any other failure stops the job with its log.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_VP = os.path.dirname(_HERE)

TRANSIENT = ("FFmpeg cannot start", "Navigation timeout of", "Parallel capture timed out",
             "capture stalled: no frame progress", "Chrome cannot start")


def warm_browser(log_dir: str) -> None:
    """Read the browser binary into the page cache before HyperFrames times it.

    `render` gives `chrome-headless-shell --version` a few seconds before giving up. The
    binary is ~150 MB and this host's disk is an Optane-cached HDD that serves a cold read
    at a few MB/s, so the first launch after a restart takes ~30 s and the preflight fails
    with "Chrome cannot start" — nothing to do with the browser itself. One warm read
    costs little and makes the check pass.
    """
    chrome = os.environ.get("HYPERFRAMES_BROWSER_PATH")
    if not chrome or not os.path.exists(chrome):
        return
    with open(os.path.join(log_dir, "browser_warm.log"), "w", encoding="utf-8") as log:
        for attempt in range(3):
            started = time.time()
            try:
                proc = subprocess.run([chrome, "--version"], stdout=log, stderr=subprocess.STDOUT,
                                      timeout=180)
            except subprocess.TimeoutExpired:
                log.write("attempt %d: timed out after 180s\n" % (attempt + 1))
                continue
            log.write("attempt %d: exit %d in %.1fs\n" % (attempt + 1, proc.returncode, time.time() - started))
            if proc.returncode == 0:
                return

# HyperFrames streams frames straight into ffmpeg only with ONE worker (its
# shouldUseStreamingEncode also wants the composition under
# streamingEncodeMaxDurationSeconds, 240 s by default). With more workers it writes every
# frame to disk and encodes afterwards: the face render wrote 82 GB, halved its own
# capture rate on this host's virtual disk, and then lost the single long encode to the
# 10-minute ffmpeg budget after three hours of capture. One worker is barely slower at
# capture here (0.43 vs 0.50 frames/s) because the cost is Chrome decoding an injected
# presenter frame, not parallelism, and it removes the encode cliff entirely.
RENDER_ENV = {
    "PRODUCER_ENABLE_STREAMING_ENCODE": "true",
    "FFMPEG_ENCODE_TIMEOUT_MS": "3600000",
    "FFMPEG_STREAMING_TIMEOUT_MS": "3600000",
    # Survives the job, so a re-render skips re-extracting the presenter (216 s).
    "HYPERFRAMES_EXTRACT_CACHE_DIR": "/data/cache/hf-extract",
    # The capture watchdog aborts the whole render after 60 s without a frame. A face
    # frame takes ~1.2 s here and one hiccup at frame 2464 of 5654 threw away 47 minutes
    # of capture, so give a stuck frame five minutes before calling it a stall.
    "HF_DE_STALL_MS": "300000",
    # Chrome holds injected presenter frames; this container only has 3.8 GB to share
    # with the streaming ffmpeg, so keep that cache small.
    "PRODUCER_FRAME_DATA_URI_CACHE_LIMIT": "8",
    "PRODUCER_FRAME_DATA_URI_CACHE_BYTES_MB": "64",
}


def step(job: str, name: str, cmd, timeout: int, retries: int = 0, env: dict | None = None) -> dict:
    log_path = os.path.join(job, "render", name + ".log")
    started = time.time()
    attempts = 0
    run_env = dict(os.environ, **env) if env else None
    while True:
        attempts += 1
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, env=run_env)
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        transient = proc.returncode != 0 and any(m in text for m in TRANSIENT)
        if proc.returncode == 0 or not transient or attempts > retries:
            break
        time.sleep(5)
    return {"step": name, "exit": proc.returncode, "attempts": attempts,
            "seconds": round(time.time() - started, 1), "transient_failure": transient if proc.returncode else False}


def probe_seconds(path: str) -> float:
    """The container's duration, or 0 if it cannot be read."""
    try:
        out = subprocess.run([os.environ.get("HYPERFRAMES_FFPROBE_PATH", "ffprobe"), "-v", "error",
                              "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=300)
        return float(out.stdout.strip() or 0)
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0.0


def rescue_artifact(render_dir: str, name: str, stop: "threading.Event") -> None:
    """Copy the render's artifact out of its staging directory as soon as it is written.

    HyperFrames writes into `.<name>.hf-transaction-*/`, validates the result, then commits
    — and deletes the staging directory if anything goes wrong. On this host the final
    ffprobe validation lost its deadline and threw away a render whose 5654 frames had all
    been captured and encoded (37 minutes). The artifact itself was fine, so keep a copy
    the moment it stops growing; `main` falls back to it when the step fails.
    """
    target = os.path.join(render_dir, name)
    last = -1
    while not stop.wait(10):
        staged = glob.glob(os.path.join(render_dir, ".%s.hf-transaction-*" % os.path.splitext(name)[0], name))
        if not staged:
            continue
        try:
            size = os.path.getsize(staged[0])
        except OSError:
            continue
        if size > 1_000_000 and size == last:
            try:
                shutil.copy2(staged[0], target + ".part")
                os.replace(target + ".part", target)
                return
            except OSError:
                return
        last = size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--attempt", type=int, default=1)
    ap.add_argument("--corrections")
    ap.add_argument("--workers", help="render workers (default 2, or 1 for face: see RENDER_ENV)")
    ap.add_argument("--template", default="faceless", choices=["faceless", "face"])
    ap.add_argument("--recording", help="face: the presenter recording (default <job>/source/recording.mp4)")
    ap.add_argument("--allow-paid", action="store_true",
                    help="face: allow the one Scribe call when no cached transcript exists")
    ap.add_argument("--cache-dir", default="/data/cache/transcripts")
    ap.add_argument("--from-step", help="skip the steps before this one (their outputs must exist)")
    args = ap.parse_args()
    job = os.path.abspath(args.job)
    os.makedirs(os.path.join(job, "render"), exist_ok=True)
    py = sys.executable
    record = {"job": job, "attempt": args.attempt, "started": time.time(), "steps": []}

    pkg_path = os.path.join(job, "source", "package.json")
    face = args.template == "face"
    # face keeps a single worker so the render streams into ffmpeg (see RENDER_ENV).
    workers = args.workers or ("1" if face else "2")
    pre = []
    if args.template == "face":
        recording = args.recording or os.path.join(job, "source", "recording.mp4")
        pre = [
            ("ingest", [py, os.path.join(_VP, "presenter", "ingest.py"), "--job", job, "--source", recording], 3600, 0),
            ("transcribe", [py, os.path.join(_VP, "presenter", "transcribe.py"), "--job", job,
                            "--cache-dir", args.cache_dir] + (["--allow-paid"] if args.allow_paid else []), 1800, 0),
            ("takes", [py, os.path.join(_VP, "presenter", "takes.py"), "--job", job, "--package", pkg_path], 300, 0),
            ("edit", [py, os.path.join(_VP, "presenter", "edit.py"), "--job", job], 3600, 0),
            ("storyboard", [py, os.path.join(_VP, "storyboard", "build.py"), "--package", pkg_path,
                            "--words", os.path.join(job, "presenter", "slides.json"), "--template", "face",
                            "--out", os.path.join(job, "storyboard.json")], 300, 0),
        ]
    plan = pre + [
        ("build", [py, os.path.join(_HERE, "build_project.py"), "--storyboard", os.path.join(job, "storyboard.json"),
                   "--audio-dir", os.path.join(job, "source"), "--presenter-dir", os.path.join(job, "presenter"),
                   "--out", os.path.join(job, "project"), "--title", args.title], 600, 0),
        ("lint", ["hyperframes", "lint", os.path.join(job, "project")], 600, 1),
        ("render", ["hyperframes", "render", os.path.join(job, "project"), "--output",
                    os.path.join(job, "render", "pages.webm" if face else "base.mp4"),
                    "--quality", "looks", "--fps", "30", "--workers", workers, "--quiet"]
                   # WebM/VP9 keeps the alpha intermediate around 300 MB. The MOV
                   # alternative is ProRes 4444: ~8 GB, which this host's HDD writes at a
                   # few MB/s. cpu-used 8 trades size for speed; the final encode is x264.
                   + (["--format", "webm", "--vp9-cpu-used", "8"] if face else []), 25200, 2, RENDER_ENV),
    ] + ([("composite", [py, os.path.join(_HERE, "composite.py"), "--job", job], 3600, 0)] if face else []) + [
        ("timeline", [py, os.path.join(_VP, "editing", "timeline.py"), "--job", job], 3600, 0),
        ("qa", [py, os.path.join(_VP, "qa", "checks.py"), "--job", job, "--package", pkg_path,
                "--attempt", str(args.attempt)]
               + (["--corrections", args.corrections] if args.corrections else []), 3600, 0),
    ]
    status = "ok"
    if args.from_step:
        names = [n for n, *_ in plan]
        if args.from_step not in names:
            raise SystemExit("unknown step %s (steps: %s)" % (args.from_step, ", ".join(names)))
        plan = plan[names.index(args.from_step):]
    if any(n in ("render", "lint") for n, *_ in plan):
        warm_browser(os.path.join(job, "render"))
    for name, cmd, timeout, retries, *rest in plan:
        rescue, stop = None, threading.Event()
        if name == "render" and face:
            rescue = threading.Thread(target=rescue_artifact,
                                      args=(os.path.join(job, "render"), "pages.webm", stop), daemon=True)
            rescue.start()
        result = step(job, name, cmd, timeout, retries, rest[0] if rest else None)
        stop.set()
        if rescue:
            rescue.join(timeout=120)
        if result["exit"] != 0 and name == "render" and face:
            # The pages are only an intermediate: if the file is there and long enough,
            # a failed commit or validation costs nothing (see rescue_artifact).
            pages = os.path.join(job, "render", "pages.webm")
            want = float(json.load(open(os.path.join(job, "project", "composition.manifest.json"),
                                       encoding="utf-8"))["duration"])
            if os.path.exists(pages) and probe_seconds(pages) >= want - 0.5:
                result["exit"] = 0
                result["rescued"] = True
        record["steps"].append(result)
        if result["exit"] != 0:
            # QA exits 1 when the render fails its checks: that is a result, not a crash.
            status = ("qa_failed" if name == "qa" else
                      "needs_paid_approval" if name == "transcribe" and result["exit"] == 3 else "failed:" + name)
            break
    record.update({"status": status, "finished": time.time(),
                   "seconds": round(time.time() - record["started"], 1)})
    with open(os.path.join(job, "render", "run.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)
    print(json.dumps(record, indent=2))
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
