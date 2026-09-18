"""Drive the HyperFrames CLI: lint -> render -> verify.

Upstream's loop is plan → compose → preview → lint → render → inspect → iterate. This
module owns the machine half of that (lint, render, verify) so the rest of the
pipeline never shells out to a video tool directly and every invocation is recorded.

Two habits enforced here rather than left to the caller:

* **Lint before render.** A render costs minutes; a lint costs no browser at all and
  catches the mistakes that produce a blank or frozen frame (missing GSAP, bad
  attributes). Refusing to render an unlintable composition is cheaper than
  discovering it in QA.
* **Verify the file that came out.** A CLI exit code of 0 is not proof of a playable
  MP4: this project has already seen a `docker compose build` exit 0 on a failed
  build. The driver probes the output and fails when duration, streams or size
  disagree with what was asked for.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class RenderError(RuntimeError):
    """A composition could not be linted, rendered, or verified."""


@dataclass
class RenderResult:
    output: str
    seconds: float
    duration: Optional[float]
    width: Optional[int]
    height: Optional[int]
    fps: Optional[float]
    has_audio: bool
    bytes: int
    lint: Dict[str, Any] = field(default_factory=dict)
    command: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "output": self.output, "render_seconds": round(self.seconds, 1),
            "duration": self.duration, "width": self.width, "height": self.height,
            "fps": self.fps, "has_audio": self.has_audio, "bytes": self.bytes,
            "lint": self.lint, "command": " ".join(self.command),
        }


def _which(name: str, env_var: str) -> str:
    return os.environ.get(env_var) or shutil.which(name) or name


def _run(cmd: List[str], *, cwd: Optional[str] = None, timeout: int = 1800) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RenderError("timed out after %ss: %s" % (timeout, " ".join(cmd))) from exc
    except FileNotFoundError as exc:
        raise RenderError("not installed: %s" % cmd[0]) from exc


def hyperframes_cmd() -> List[str]:
    """The CLI, however it is installed: a binary on PATH, else npx."""
    exe = os.environ.get("HYPERFRAMES_BIN") or shutil.which("hyperframes")
    if exe:
        return [exe]
    return ["npx", "--yes", "hyperframes@" + os.environ.get("HYPERFRAMES_VERSION", "0.8.42")]


def doctor() -> Dict[str, Any]:
    """Environment report, for start-up checks and the operations doc."""
    proc = _run(hyperframes_cmd() + ["doctor", "--json"], timeout=300)
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": proc.returncode == 0, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}


def lint(project_dir: str, *, strict: bool = True) -> Dict[str, Any]:
    """Run the linter. With strict, any error raises before a browser is started."""
    proc = _run(hyperframes_cmd() + ["lint", project_dir, "--json"], timeout=300)
    report: Dict[str, Any]
    try:
        report = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        report = {"parsed": False, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:],
                  "errorCount": 0 if proc.returncode == 0 else 1}
    errors = int(report.get("errorCount") or 0)
    if strict and errors:
        findings = report.get("findings") or []
        detail = "; ".join(
            "%s: %s" % (f.get("rule") or f.get("code") or "error", f.get("message"))
            for f in findings if (f.get("severity") or f.get("level")) in (None, "error"))
        raise RenderError("composition has %d lint error(s): %s" % (errors, detail or report.get("stderr", "")))
    return report


def probe(path: str) -> Dict[str, Any]:
    """ffprobe the rendered file. The render is not trusted until this agrees."""
    ffprobe = _which("ffprobe", "FFPROBE_BIN")
    proc = _run([ffprobe, "-v", "error", "-print_format", "json",
                 "-show_format", "-show_streams", path], timeout=180)
    if proc.returncode != 0:
        raise RenderError("ffprobe could not read %s: %s" % (path, proc.stderr.strip()[:400]))
    data = json.loads(proc.stdout or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fps = None
    if video and video.get("avg_frame_rate") and "/" in video["avg_frame_rate"]:
        num, den = video["avg_frame_rate"].split("/")
        fps = round(float(num) / float(den), 3) if float(den) else None
    return {
        "duration": float(data.get("format", {}).get("duration") or 0) or None,
        "width": video.get("width") if video else None,
        "height": video.get("height") if video else None,
        "fps": fps,
        "video_codec": video.get("codec_name") if video else None,
        "audio_codec": audio.get("codec_name") if audio else None,
        "has_audio": audio is not None,
        "bytes": int(data.get("format", {}).get("size") or 0),
    }


def render(project_dir: str,
           output: str,
           *,
           quality: str = "looks",
           fps: Optional[int] = None,
           resolution_scale: Optional[str] = None,
           expect_duration: Optional[float] = None,
           expect_size: Optional[tuple] = None,
           workers: Optional[int] = None,
           low_memory: Optional[bool] = None,
           timeout: Optional[int] = None,
           strict_lint: bool = True) -> RenderResult:
    """Lint, render, and verify one composition."""
    if not os.path.exists(os.path.join(project_dir, "index.html")):
        raise RenderError("no index.html in %s" % project_dir)

    lint_report = lint(project_dir, strict=strict_lint)

    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    cmd = hyperframes_cmd() + ["render", project_dir, "--output", os.path.abspath(output),
                               "--quality", quality]
    if fps:
        cmd += ["--fps", str(fps)]
    if resolution_scale:
        cmd += ["--resolution", resolution_scale]
    if workers:
        cmd += ["--workers", str(workers)]

    env_note = {}
    if low_memory is not None:
        # Low-memory detection reads HOST RAM, not the container limit, so a
        # containerised render must say which profile it wants.
        os.environ["PRODUCER_LOW_MEMORY_MODE"] = "1" if low_memory else "0"
        env_note["PRODUCER_LOW_MEMORY_MODE"] = os.environ["PRODUCER_LOW_MEMORY_MODE"]

    # Scale the timeout to the material: a flat cap reads a busy machine as a hang.
    budget = timeout or max(900, int((expect_duration or 60) * 40))
    started = time.time()
    proc = _run(cmd, timeout=budget)
    elapsed = time.time() - started

    if proc.returncode != 0 or not os.path.exists(output):
        raise RenderError("render failed (exit %s): %s" % (
            proc.returncode, (proc.stderr or proc.stdout or "").strip()[-1500:]))

    info = probe(output)
    if not info["duration"]:
        raise RenderError("rendered file has no readable duration: %s" % output)
    if expect_duration and abs(info["duration"] - expect_duration) > max(1.5, expect_duration * 0.02):
        raise RenderError("rendered duration %.2fs does not match the expected %.2fs"
                          % (info["duration"], expect_duration))
    if expect_size and (info["width"], info["height"]) != tuple(expect_size):
        raise RenderError("rendered %sx%s, expected %sx%s"
                          % (info["width"], info["height"], expect_size[0], expect_size[1]))

    return RenderResult(output=output, seconds=elapsed, duration=info["duration"],
                        width=info["width"], height=info["height"], fps=info["fps"],
                        has_audio=info["has_audio"], bytes=info["bytes"],
                        lint=lint_report, command=cmd)


def snapshot(project_dir: str, out_dir: str, times: List[float]) -> List[str]:
    """Still frames at given times, for inspection without a full render."""
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []
    for t in times:
        target = os.path.join(out_dir, "frame_%07.2f.png" % t)
        proc = _run(hyperframes_cmd() + ["snapshot", project_dir, "--time", str(t), "--output", target],
                    timeout=600)
        if proc.returncode == 0 and os.path.exists(target):
            written.append(target)
    return written
