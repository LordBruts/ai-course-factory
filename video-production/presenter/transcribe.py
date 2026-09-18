"""Word timings for the presenter recording: the one paid step of the face template.

    python3 video-production/presenter/transcribe.py --job /data/video-jobs/<id> \
        [--cache-dir /app/cache/transcripts] [--allow-paid]

Order of preference:
    1. <job>/presenter/scribe.json already present
    2. a cached transcript whose sha256 key matches scribe.wav (never bought twice)
    3. ElevenLabs Scribe via video-use's transcribe.py, ONLY with --allow-paid

Scribe draws from the same credit pool as TTS (about 1.1 credits per second of
audio) and the debit appears minutes late, so the balance is recorded before the
call and must be re-read later with --balance-only.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "vendor", "video-use", "helpers"))


def balance(key: str) -> dict:
    r = requests.get("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": key}, timeout=30)
    r.raise_for_status()
    d = r.json()
    return {"character_count": d.get("character_count"), "character_limit": d.get("character_limit"),
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--cache-dir")
    ap.add_argument("--allow-paid", action="store_true")
    ap.add_argument("--balance-only", action="store_true")
    args = ap.parse_args()
    from transcribe import call_scribe, load_api_key  # vendored video-use

    pdir = os.path.join(args.job, "presenter")
    log_path = os.path.join(pdir, "transcribe.json")
    log = json.load(open(log_path, encoding="utf-8")) if os.path.exists(log_path) else {}
    if args.balance_only:
        log.setdefault("balance_checks", []).append(balance(load_api_key()))
        json.dump(log, open(log_path, "w", encoding="utf-8"), indent=2)
        print(json.dumps(log, indent=1))
        return 0

    with open(os.path.join(pdir, "ingest.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    out = os.path.join(pdir, "scribe.json")
    if os.path.exists(out):
        print("present: %s" % out)
        return 0
    key_name = "presenter_%s.json" % meta["scribe_sha256"][:16]
    cached = os.path.join(args.cache_dir, key_name) if args.cache_dir else None
    if cached and os.path.exists(cached):
        shutil.copyfile(cached, out)
        log.update({"source": "cache", "cache_file": cached, "paid": False})
        json.dump(log, open(log_path, "w", encoding="utf-8"), indent=2)
        print("from cache: %s" % cached)
        return 0
    if not args.allow_paid:
        print("no transcript and no cache; Scribe costs ~%.0f credits for %.0fs. Re-run with --allow-paid "
              "once that is approved." % (meta["scribe_seconds"] * 1.1, meta["scribe_seconds"]), file=sys.stderr)
        return 3

    api_key = load_api_key()
    before = balance(api_key)
    t0 = time.time()
    payload = call_scribe(Path(meta["scribe_wav"]), api_key, language="en", num_speakers=1)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    if args.cache_dir:
        os.makedirs(args.cache_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=args.cache_dir, suffix=".tmp", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(fh.name, os.path.join(args.cache_dir, key_name))
    log.update({"source": "scribe", "paid": True, "model": "scribe_v1", "audio_seconds": meta["scribe_seconds"],
                "estimated_credits": round(meta["scribe_seconds"] * 1.1), "seconds": round(time.time() - t0, 1),
                "balance_before": before, "balance_checks": [balance(api_key)],
                "words": sum(1 for w in payload.get("words", []) if w.get("type") == "word")})
    json.dump(log, open(log_path, "w", encoding="utf-8"), indent=2)
    print(json.dumps(log, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
