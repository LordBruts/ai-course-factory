"""Audio duration without shelling out.

Timing decides where every visual lands, so it is worth having a dependency-free
way to measure it. This walks MP3 frame headers and sums their durations, which
is correct for CBR and VBR alike (a bitrate-based estimate is wrong for VBR, and
ElevenLabs output is not guaranteed CBR).

`ffprobe` stays the authority in QA, where the container is available anyway. This
exists so storyboard timing never blocks on Docker, and so the same numbers can be
computed on a developer machine with nothing installed.
"""

from __future__ import annotations

import os
import struct
from typing import Dict, Optional

_BITRATES_V1_L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
_BITRATES_V2_L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
_RATES = {
    3: [44100, 48000, 32000, 0],   # MPEG-1
    2: [22050, 24000, 16000, 0],   # MPEG-2
    0: [11025, 12000, 8000, 0],    # MPEG-2.5
}
_SAMPLES = {3: 1152, 2: 576, 0: 576}


def _id3_size(data: bytes) -> int:
    if len(data) < 10 or data[:3] != b"ID3":
        return 0
    # Syncsafe integer: 7 bits per byte.
    b = data[6:10]
    return 10 + ((b[0] & 0x7F) << 21 | (b[1] & 0x7F) << 14 | (b[2] & 0x7F) << 7 | (b[3] & 0x7F))


def mp3_duration(path: str) -> Optional[float]:
    """Seconds of audio, or None when the file is not parseable as MP3."""
    with open(path, "rb") as fh:
        data = fh.read()
    if not data:
        return None

    i = _id3_size(data)
    total = 0.0
    frames = 0
    n = len(data)

    while i + 4 <= n:
        if data[i] != 0xFF or (data[i + 1] & 0xE0) != 0xE0:
            i += 1
            continue
        header = struct.unpack(">I", data[i:i + 4])[0]
        version = (header >> 19) & 0x3          # 3 = MPEG-1, 2 = MPEG-2, 0 = MPEG-2.5
        layer = (header >> 17) & 0x3            # 1 = Layer III
        bitrate_idx = (header >> 12) & 0xF
        rate_idx = (header >> 10) & 0x3
        padding = (header >> 9) & 0x1

        if layer != 1 or version == 1 or bitrate_idx in (0, 15) or rate_idx == 3:
            i += 1
            continue
        table = _BITRATES_V1_L3 if version == 3 else _BITRATES_V2_L3
        bitrate = table[bitrate_idx] * 1000
        sample_rate = _RATES[version][rate_idx]
        if not bitrate or not sample_rate:
            i += 1
            continue

        samples = _SAMPLES[version]
        frame_len = int((samples / 8) * bitrate / sample_rate) + padding
        if frame_len <= 4:
            i += 1
            continue

        total += samples / sample_rate
        frames += 1
        i += frame_len

    return round(total, 3) if frames else None


def durations_for(directory: str, prefix: str = "audio_", ext: str = ".mp3") -> Dict[int, float]:
    """{index: seconds} for a directory of numbered narration files."""
    out: Dict[int, float] = {}
    for name in sorted(os.listdir(directory)):
        if not (name.startswith(prefix) and name.endswith(ext)):
            continue
        stem = name[len(prefix):-len(ext)]
        if not stem.isdigit():
            continue
        seconds = mp3_duration(os.path.join(directory, name))
        if seconds:
            out[int(stem)] = seconds
    return out


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Measure narration durations without ffprobe.")
    ap.add_argument("directory")
    ap.add_argument("--out")
    args = ap.parse_args()
    result = durations_for(args.directory)
    text = json.dumps({str(k): v for k, v in sorted(result.items())}, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    print("total %.1fs across %d files" % (sum(result.values()), len(result)))
