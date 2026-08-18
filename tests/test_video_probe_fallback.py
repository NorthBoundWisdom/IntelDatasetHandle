from __future__ import annotations

import json
import subprocess
from pathlib import Path

import weld_data_workbench.io.probe as probe_module
from weld_data_workbench.domain.models import ProbeMode


class _ClosedCapture:
    def isOpened(self) -> bool:
        return False

    def release(self) -> None:
        pass


def test_ffprobe_fallback_recovers_when_opencv_cannot_open(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "fallback.avi"
    video.write_bytes(b"placeholder")
    monkeypatch.setattr(probe_module.cv2, "VideoCapture", lambda _path: _ClosedCapture())
    monkeypatch.setattr(probe_module.shutil, "which", lambda name: "/usr/bin/ffprobe")

    payload = {
        "streams": [
            {
                "codec_name": "mpeg4",
                "codec_tag_string": "XVID",
                "width": 640,
                "height": 480,
                "avg_frame_rate": "30000/1001",
                "r_frame_rate": "30/1",
                "nb_frames": "120",
                "duration": "4.004",
            }
        ],
        "format": {"duration": "4.004"},
    }

    def fake_run(command, **kwargs):
        assert command[-1] == str(video)
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(probe_module.subprocess, "run", fake_run)

    metadata, ok = probe_module._probe_video(video, ProbeMode.FULL)

    assert ok
    assert metadata["probe_backend"] == "ffprobe"
    assert metadata["width"] == 640
    assert metadata["height"] == 480
    assert metadata["frame_count"] == 120
    assert metadata["fps"] == 30000 / 1001
    assert metadata["duration_s"] == 4.004
    assert metadata["fourcc"] == "XVID"
    assert metadata["codec_name"] == "mpeg4"
    assert metadata["decode_verified"] is False
    assert metadata["fallback_reason"] == "OpenCV could not open video"
    assert metadata["opencv_metadata"]["probe_backend"] == "opencv"


def test_ffprobe_fallback_reports_both_backends_when_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    video = tmp_path / "unreadable.avi"
    video.write_bytes(b"placeholder")
    monkeypatch.setattr(probe_module.cv2, "VideoCapture", lambda _path: _ClosedCapture())
    monkeypatch.setattr(probe_module.shutil, "which", lambda name: None)

    metadata, ok = probe_module._probe_video(video, ProbeMode.LIGHT)

    assert not ok
    assert metadata["probe_backend"] == "opencv+ffprobe"
    assert metadata["opencv_metadata"]["error"] == "OpenCV could not open video"
    assert metadata["ffprobe_metadata"]["error"] == "ffprobe executable is not available"
