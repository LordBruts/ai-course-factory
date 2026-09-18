"""Where presenter footage comes from.

The face template never cares whether the presenter is a person who filmed the
approved script or an avatar generated from it. Both arrive as a `PresenterClip`:
a video, its audio, word timings and provenance. Swapping the source is a change
of adapter, not of template.

    HumanRecording   a file the presenter recorded from samples/face/RECORDING_SCRIPT.md
    HeyGenSource     avatar video from HeyGen: interface only until an account and a
                     credential exist. It makes no network calls.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Protocol


class NotConfigured(RuntimeError):
    pass


@dataclass
class PresenterClip:
    video: str                      # H.264 CFR proxy the renderer can seek
    audio: str                      # loudness-normalised programme audio (same timeline as video)
    transcript: Optional[str]       # word-level transcript JSON (Scribe shape), or None until transcribed
    duration: float
    subject_center_x: float         # 0..1 across the frame, from ingest.json
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PresenterVideoSource(Protocol):
    kind: str

    def prepare(self, job_dir: str) -> PresenterClip:
        """Produce a clip inside job_dir. Paid work is the caller's decision, never implicit."""
        ...


class HumanRecording:
    """A file the presenter filmed. `presenter/ingest.py` must have run on it first."""

    kind = "human_recording"

    def __init__(self, path: str):
        self.path = path

    def prepare(self, job_dir: str) -> PresenterClip:
        meta_path = os.path.join(job_dir, "presenter", "ingest.json")
        if not os.path.exists(meta_path):
            raise FileNotFoundError("run presenter/ingest.py first: %s missing" % meta_path)
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        transcript = os.path.join(job_dir, "presenter", "transcript.json")
        return PresenterClip(
            video=meta["proxy"], audio=meta["proxy"],
            transcript=transcript if os.path.exists(transcript) else None,
            duration=meta["proxy_duration"],
            subject_center_x=meta["framing"]["subject_center_x"],
            provenance={"kind": self.kind, "source": os.path.basename(self.path),
                        "source_sha256": meta.get("source_sha256")},
        )


class HeyGenSource:
    """Avatar presenter. Deliberately inert until the account and credential exist."""

    kind = "heygen_avatar"

    def __init__(self, avatar_id: Optional[str] = None, voice_id: Optional[str] = None):
        self.avatar_id, self.voice_id = avatar_id, voice_id

    def prepare(self, job_dir: str) -> PresenterClip:
        raise NotConfigured("HeyGen is not configured: no avatar, voice or credential. "
                            "Use HumanRecording, or configure HeyGen in Phase 5.")


def source_for(kind: str, **kw: Any) -> PresenterVideoSource:
    if kind == HumanRecording.kind:
        return HumanRecording(kw["path"])
    if kind == HeyGenSource.kind:
        return HeyGenSource(kw.get("avatar_id"), kw.get("voice_id"))
    raise ValueError("unknown presenter source: %s" % kind)
