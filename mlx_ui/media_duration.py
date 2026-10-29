from __future__ import annotations

import json
import logging
import math
from pathlib import Path
import subprocess
import tempfile

logger = logging.getLogger(__name__)
PROBE_TIMEOUT_SECONDS = 15


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def probe_audio_duration(path: Path) -> float | None:
    """Read source audio length without depending on a transcription engine."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=duration,codec_type:format=duration",
                "-of",
                "json",
                str(path.resolve()),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        metadata = json.loads(result.stdout)
        streams = metadata.get("streams", [])
        if not streams:
            return None
        duration = _number(streams[0].get("duration"))
        if duration is not None and duration > 0:
            return duration
        # A video's container duration may exceed its audio track. Read packets
        # for video containers and for MediaRecorder files without duration tags.
        video = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "json",
                str(path.resolve()),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        if not json.loads(video.stdout).get("streams"):
            duration = _number(metadata.get("format", {}).get("duration"))
            if duration is not None and duration > 0:
                return duration
        return _packet_duration(path)
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    ):
        logger.warning("Could not determine audio duration for %s", path.name)
        return None


def _packet_duration(path: Path) -> float | None:
    # Keep packet lists on disk: long recordings must not grow worker memory.
    with tempfile.TemporaryFile(mode="w+t") as output:
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_packets",
                "-show_entries",
                "packet=pts_time,duration_time",
                "-of",
                "compact=p=0:nk=0",
                str(path.resolve()),
            ],
            stdout=output,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        output.seek(0)
        start = None
        end = None
        for line in output:
            fields = dict(
                part.split("=", 1) for part in line.strip().split("|") if "=" in part
            )
            timestamp = _number(fields.get("pts_time"))
            length = _number(fields.get("duration_time"))
            if timestamp is None or length is None or length < 0:
                continue
            start = timestamp if start is None else min(start, timestamp)
            packet_end = timestamp + length
            end = packet_end if end is None else max(end, packet_end)
        duration = end - start if end is not None and start is not None else 0
        return duration if math.isfinite(duration) and duration > 0 else None
