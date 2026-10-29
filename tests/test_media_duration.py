from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import wave

import pytest

from mlx_ui.media_duration import probe_audio_duration


def write_wav(path: Path, seconds: float = 1.25) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * int(16000 * seconds))


@pytest.mark.parametrize("extension", ["wav", "mp3", "m4a", "webm"])
def test_probe_real_media(tmp_path: Path, extension: str) -> None:
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg tools unavailable")
    source = tmp_path / "source.wav"
    write_wav(source)
    target = tmp_path / f"recording.{extension}"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(source), str(target)], check=True
    )
    assert probe_audio_duration(target) == pytest.approx(1.25, abs=0.1)


def test_probe_packet_fallback_for_webm_without_duration(
    tmp_path: Path, monkeypatch
) -> None:
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "-show_packets" in command:
            kwargs["stdout"].write(
                "pts_time=-0.007000|duration_time=0.020000\n"
                "pts_time=1.233000|duration_time=0.020000|side_data_type=Skip Samples\n"
            )
            return subprocess.CompletedProcess(command, 0)
        data = {"streams": [{"codec_type": "audio"}], "format": {}}
        if "v:0" in command:
            data = {"streams": []}
        return subprocess.CompletedProcess(command, 0, json.dumps(data))

    monkeypatch.setattr(subprocess, "run", run)
    assert probe_audio_duration(tmp_path / "recording.webm") == pytest.approx(1.26)
    assert len(calls) == 3


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError(),
        subprocess.TimeoutExpired("ffprobe", 15),
        subprocess.CalledProcessError(1, "ffprobe"),
    ],
)
def test_probe_failure_is_nonfatal(tmp_path: Path, monkeypatch, error) -> None:
    def run(*args, **kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", run)
    assert probe_audio_duration(tmp_path / "recording.wav") is None


@pytest.mark.parametrize("value", [None, "N/A", "nan", "inf", "-1", "0"])
def test_unknown_or_invalid_duration_is_not_exposed(
    tmp_path: Path, monkeypatch, value
) -> None:
    def run(command, **kwargs):
        if "-show_packets" in command:
            kwargs["stdout"].write("pts_time=N/A|duration_time=N/A\n")
            return subprocess.CompletedProcess(command, 0)
        data = {"streams": [{"duration": value}], "format": {"duration": value}}
        if "v:0" in command:
            data = {"streams": []}
        return subprocess.CompletedProcess(command, 0, json.dumps(data))

    monkeypatch.setattr(subprocess, "run", run)
    assert probe_audio_duration(tmp_path / "recording.webm") is None


def test_video_duration_uses_audio_packets_not_longer_container(
    tmp_path: Path, monkeypatch
) -> None:
    def run(command, **kwargs):
        if "-show_packets" in command:
            kwargs["stdout"].write("pts_time=0|duration_time=1.25\n")
            return subprocess.CompletedProcess(command, 0)
        return subprocess.CompletedProcess(
            command, 0, json.dumps({"streams": [{}], "format": {"duration": "20"}})
        )

    monkeypatch.setattr(subprocess, "run", run)
    assert probe_audio_duration(tmp_path / "video.mp4") == 1.25
