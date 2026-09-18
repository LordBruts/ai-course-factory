"""Write <job>/render_metadata.json: what was rendered, with what, how long it took.

    python3 video-production/rendering/render_metadata.py --job /data/video-jobs/<id> --template faceless

Hashes every output and narration source so a published video can be traced back to
the exact approved audio and storyboard it was made from.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(path: str) -> dict:
    d = json.loads(sh("ffprobe -v error -print_format json -show_format -show_streams '%s'" % path) or "{}")
    v = next((s for s in d.get("streams", []) if s["codec_type"] == "video"), {})
    a = next((s for s in d.get("streams", []) if s["codec_type"] == "audio"), {})
    return {"duration": float(d.get("format", {}).get("duration") or 0), "bytes": int(d.get("format", {}).get("size") or 0),
            "video": "%s %sx%s %s" % (v.get("codec_name"), v.get("width"), v.get("height"), v.get("avg_frame_rate")),
            "audio": a.get("codec_name")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--template", default="faceless")
    ap.add_argument("--note", default="")
    args = ap.parse_args()
    job = args.job

    def load(rel: str) -> dict:
        p = os.path.join(job, rel)
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}

    run = load("render/run.json")
    qa = load("qa/video_qa.json")
    sb = load("storyboard.json")
    meta = {
        "job_id": os.path.basename(job.rstrip("/")),
        "template": args.template,
        "layout": "boards" if sb.get("boards") else "beats",
        "course_slug": sb.get("course_slug"),
        "attempt": qa.get("attempt"),
        "qa_status": qa.get("status"),
        "tools": {
            "hyperframes": "0.8.42",
            "chrome_headless_shell": "148.0.7778.167",
            "ffmpeg": sh("ffmpeg -version | head -1"),
            "gsap": "3.15.0 (vendored)",
            "icons": "lucide-static 1.47.0 (ISC, vendored subset)",
            "transcription": "ElevenLabs Scribe via video-use transcribe.py (cached)",
        },
        "run": run,
        "boards": [{"board_id": b["board_id"], "kind": b["kind"], "start": b["start"], "end": b["end"],
                    "elements": len(b["elements"])} for b in sb.get("boards", [])],
        "captions": {"style": "two-word uppercase (video-use build_master_srt), burned in last",
                     "cues": qa.get("metrics", {}).get("caption_cue_count")},
        "outputs": {n: {**probe(os.path.join(job, n)), "sha256": sha256(os.path.join(job, n))}
                    for n in ("final.mp4", "preview.mp4", "render/base.mp4") if os.path.exists(os.path.join(job, n))},
        "narration_sources": {n: sha256(os.path.join(job, "source", n))
                              for n in sorted(os.listdir(os.path.join(job, "source"))) if n.endswith(".mp3")},
        "storyboard_sha256": sha256(os.path.join(job, "storyboard.json")),
        "paid_calls": {"elevenlabs_tts": 0, "elevenlabs_scribe": "none in this run (transcripts cached)", "llm_calls": 0},
        "note": args.note,
    }
    if args.template == "face":
        pdir = os.path.join(job, "presenter")
        ingest = load("presenter/ingest.json")
        tr = load("presenter/transcribe.json")
        edl = load("presenter/edl.json")
        meta["presenter"] = {
            "source": {"kind": "human_recording", "file": os.path.basename(ingest.get("source", "")),
                       "sha256": ingest.get("source_sha256"), "probe": ingest.get("source_probe")},
            "proxy": {"sha256": sha256(os.path.join(pdir, "proxy.mp4")), "probe": ingest.get("proxy_probe")},
            "edit": {**load("presenter/edit.json"), "sha256": sha256(os.path.join(pdir, "edit.mp4"))},
            "loudness_measured": ingest.get("loudness_measured"),
            "framing": {k: v for k, v in (ingest.get("framing") or {}).items() if "strip" not in k},
            "takes": edl.get("summary"),
        }
        checks = tr.get("balance_checks") or []
        before = (tr.get("balance_before") or {}).get("character_count")
        after = checks[-1]["character_count"] if checks else None
        meta["narration_sources"] = {}
        meta["paid_calls"] = {
            "elevenlabs_tts": 0, "llm_calls": 0,
            "elevenlabs_scribe": {"audio_seconds": tr.get("audio_seconds"), "model": tr.get("model"),
                                  "estimated_credits": tr.get("estimated_credits"),
                                  "balance_before": before, "balance_after": after,
                                  "credits_debited": (after - before) if (before is not None and after is not None) else None,
                                  "balance_read_at": checks[-1]["at"] if checks else None,
                                  "cached_for_reuse": True},
        }
        meta["tools"]["transcription"] = "ElevenLabs Scribe v1 (one call, presenter recording)"
    with open(os.path.join(job, "render_metadata.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    print(json.dumps(meta["outputs"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
