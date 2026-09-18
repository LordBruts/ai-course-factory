"""Lay a pages-only render over the presenter, in place of rendering the video in Chrome.

    python3 rendering/composite.py --job /data/video-jobs/<id>

A <video> inside the composition makes HyperFrames screenshot every frame with the
presenter decoded in the page: ~1.2 s per frame on this host against 0.15 s for the pages
alone, memory that grows until the capture stalls, and a render measured in hours. So the
pages render alone to an alpha format (`--format webm`, VP9 with alpha) and the presenter is
rebuilt here from the manifest's own schedules (templates/face/presenter_track.py).

Three processes, one pass, nothing on disk in between:

    ffmpeg -> raw presenter frames -> this script paints them -> ffmpeg overlays the pages

The pages carry their own alpha, so a glass panel dims the presenter exactly as it did in
the browser, and the window's rounded corners come from the mask this script paints.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_VP = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_VP, "templates", "face"))

from PIL import Image  # noqa: E402

from presenter_track import H, W, PresenterTrack  # noqa: E402

FRAME_BYTES = W * H * 3


def ffmpeg_bin() -> str:
    return os.environ.get("HYPERFRAMES_FFMPEG_PATH", "ffmpeg")


def run(job: str, pages: str, presenter: str, out: str, manifest_path: str, fps: int = 30,
        frames: int = 0) -> int:
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    if manifest.get("presenter_layer"):
        raise SystemExit("composite.py expects a pages-only render (presenter_layer: false)")
    for path in (pages, presenter):
        if not os.path.exists(path):
            raise SystemExit("missing input: %s" % path)
    track = PresenterTrack(manifest)
    total = frames or int(round(float(manifest["duration"]) * fps))

    decode = [ffmpeg_bin(), "-v", "error", "-i", presenter,
              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    encode = [
        ffmpeg_bin(), "-v", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H), "-r", str(fps), "-i", "pipe:0",
        # VP9 alpha rides in the container's BlockAdditions, and only libvpx-vp9 decodes
        # it. ffmpeg's default vp9 decoder drops it silently: ffprobe says yuv420p, the
        # overlay is fully opaque, and the presenter never shows.
        "-c:v", "libvpx-vp9", "-i", pages,
        "-i", presenter,                 # the edit's audio
        "-filter_complex", "[1:v]format=rgba[pg];[0:v][pg]overlay=0:0:format=auto,format=yuv420p[v]",
        "-map", "[v]", "-map", "2:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out,
    ]
    started = time.time()
    src = subprocess.Popen(decode, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=FRAME_BYTES)
    dst = subprocess.Popen(encode, stdin=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=FRAME_BYTES)
    written = 0
    try:
        while written < total:
            buf = src.stdout.read(FRAME_BYTES)
            if len(buf) < FRAME_BYTES:
                break
            frame = Image.frombuffer("RGB", (W, H), buf, "raw", "RGB", 0, 1)
            dst.stdin.write(track.frame(frame, written / fps).tobytes())
            written += 1
            if written % 300 == 0:
                rate = written / max(0.001, time.time() - started)
                print("  %d/%d frames (%.1f fps, %.0fs left)"
                      % (written, total, rate, (total - written) / max(rate, 0.01)), flush=True)
    finally:
        if src.stdout:
            src.stdout.close()
        if dst.stdin:
            dst.stdin.close()
        src.wait(timeout=60)
        code = dst.wait(timeout=1800)
    err = (dst.stderr.read() or b"").decode("utf-8", "replace").strip()
    if code != 0:
        raise SystemExit("ffmpeg encode failed (%s): %s" % (code, err[-2000:]))
    if written < total:
        raise SystemExit("presenter ran out at frame %d of %d" % (written, total))
    print("composite: %s · %d frames · %.1fs" % (out, written, time.time() - started))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--pages", help="default <job>/render/pages.webm")
    ap.add_argument("--presenter", help="default <job>/presenter/edit.mp4")
    ap.add_argument("--out", help="default <job>/render/base.mp4")
    ap.add_argument("--manifest", help="default <job>/project/composition.manifest.json")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--frames", type=int, default=0, help="stop after N frames (slice checks)")
    a = ap.parse_args()
    job = os.path.abspath(a.job)
    return run(job,
               a.pages or os.path.join(job, "render", "pages.webm"),
               a.presenter or os.path.join(job, "presenter", "edit.mp4"),
               a.out or os.path.join(job, "render", "base.mp4"),
               a.manifest or os.path.join(job, "project", "composition.manifest.json"),
               a.fps, a.frames)


if __name__ == "__main__":
    raise SystemExit(main())
