"""Tests for Media Utilities & Scene Cut Engine (`media.py`)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from reel_watcher.media import (
    detect_cuts,
    id_from_url,
    pick_frame_times,
    preflight,
    probe,
)


# ----------------------------------------------------------------------
# 1. Tests for id_from_url
# ----------------------------------------------------------------------


def test_id_from_url_instagram() -> None:
    """Verify parsing various Instagram Reel and Post URLs into 'ig_<code>'."""
    assert id_from_url("https://www.instagram.com/reel/C8xyz12345/") == "ig_C8xyz12345"
    assert (
        id_from_url("https://instagram.com/reels/D9abc67890?utm_source=ig_web")
        == "ig_D9abc67890"
    )
    assert id_from_url("https://www.instagram.com/p/E0def11122/") == "ig_E0def11122"
    assert (
        id_from_url("https://www.instagram.com/share/reel/F1ghi33344/")
        == "ig_F1ghi33344"
    )


def test_id_from_url_tiktok() -> None:
    """Verify parsing TikTok URLs into 'tt_<code>'."""
    assert (
        id_from_url("https://www.tiktok.com/@creator/video/7123456789012345678")
        == "tt_7123456789012345678"
    )
    assert (
        id_from_url("https://www.tiktok.com/v/7123456789012345678")
        == "tt_7123456789012345678"
    )
    assert id_from_url("https://vm.tiktok.com/ZM8abc123/") == "tt_ZM8abc123"
    assert id_from_url("https://www.tiktok.com/t/ZT8xyz/") == "tt_ZT8xyz"


def test_id_from_url_youtube_shorts() -> None:
    """Verify parsing YouTube Shorts and watch URLs into 'yt_<code>'."""
    assert (
        id_from_url("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        == "yt_dQw4w9WgXcQ"
    )
    assert id_from_url("https://youtu.be/dQw4w9WgXcQ") == "yt_dQw4w9WgXcQ"
    assert (
        id_from_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        == "yt_dQw4w9WgXcQ"
    )


def test_id_from_url_already_normalized_and_invalid() -> None:
    """Verify idempotency for normalized IDs and None for unsupported URLs."""
    # Normalized inputs preserved
    assert id_from_url("ig_C8xyz12345") == "ig_C8xyz12345"
    assert id_from_url("tt_7123456789012345678") == "tt_7123456789012345678"
    assert id_from_url("yt_dQw4w9WgXcQ") == "yt_dQw4w9WgXcQ"

    # Invalid / empty
    assert id_from_url("https://twitter.com/user/status/123456") is None
    assert id_from_url("https://example.com/random_video.mp4") is None
    assert id_from_url("") is None
    assert id_from_url("   ") is None


# ----------------------------------------------------------------------
# 2. Tests for preflight
# ----------------------------------------------------------------------


def test_preflight_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify preflight returns empty string when ffmpeg and ffprobe are found."""
    monkeypatch.setattr("shutil.which", lambda cmd: f"/usr/bin/{cmd}")
    msg = preflight()
    assert msg == ""


def test_preflight_missing_binaries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify preflight returns installation instructions if binaries are missing."""
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    msg = preflight()
    assert "Missing required media dependencies" in msg
    assert "ffmpeg" in msg
    assert "ffprobe" in msg


# ----------------------------------------------------------------------
# 3. Tests for probe
# ----------------------------------------------------------------------


def test_probe_nonexistent_file(tmp_path: Path) -> None:
    """Verify probe raises FileNotFoundError when target does not exist."""
    missing_file = tmp_path / "missing.mp4"
    with pytest.raises(FileNotFoundError):
        probe(missing_file)


def test_probe_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify probe parses ffprobe JSON output into standardized dictionary."""
    dummy_file = tmp_path / "video.mp4"
    dummy_file.write_bytes(b"dummy")

    fake_ffprobe_data = {
        "streams": [
            {
                "codec_type": "video",
                "width": 1080,
                "height": 1920,
                "r_frame_rate": "30/1",
                "avg_frame_rate": "30/1",
                "duration": "12.500",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
            },
        ],
        "format": {
            "duration": "12.500",
            "size": "5432100",
        },
    }

    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = json.dumps(fake_ffprobe_data)
    mock_run.stderr = ""

    monkeypatch.setattr("shutil.which", lambda cmd: f"/fake/{cmd}")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_run)

    result = probe(dummy_file)
    assert result == {
        "duration": 12.5,
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "has_audio": True,
    }


def test_probe_failure_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify probe raises RuntimeError when ffprobe returns non-zero code."""
    dummy_file = tmp_path / "corrupt.mp4"
    dummy_file.write_bytes(b"corrupt")

    mock_run = MagicMock()
    mock_run.returncode = 1
    mock_run.stdout = ""
    mock_run.stderr = "Invalid data found when processing input"

    monkeypatch.setattr("shutil.which", lambda cmd: f"/fake/{cmd}")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_run)

    with pytest.raises(RuntimeError, match="ffprobe failed"):
        probe(dummy_file)


# ----------------------------------------------------------------------
# 4. Tests for detect_cuts
# ----------------------------------------------------------------------


def test_detect_cuts_zero_duration(tmp_path: Path) -> None:
    """Verify detect_cuts short-circuits to empty list when duration <= 0."""
    dummy_file = tmp_path / "video.mp4"
    dummy_file.write_bytes(b"dummy")
    assert detect_cuts(dummy_file, duration=0.0) == []
    assert detect_cuts(dummy_file, duration=-5.0) == []


def test_detect_cuts_nonexistent_file(tmp_path: Path) -> None:
    """Verify detect_cuts raises FileNotFoundError if video does not exist."""
    missing = tmp_path / "absent.mp4"
    with pytest.raises(FileNotFoundError):
        detect_cuts(missing, duration=10.0)


def test_detect_cuts_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify detect_cuts extracts scene change timestamps from showinfo stderr."""
    dummy_file = tmp_path / "video.mp4"
    dummy_file.write_bytes(b"dummy")

    fake_stderr = """
[Parsed_showinfo_1 @ 000001] n: 0 pts: 0 pts_time:0.000 pos: 0 fmt:yuv420p
[Parsed_showinfo_1 @ 000001] n: 30 pts: 90000 pts_time:1.000 pos: 1000 fmt:yuv420p
[Parsed_showinfo_1 @ 000001] n: 90 pts: 270000 pts_time:3.450 pos: 2000 fmt:yuv420p
[Parsed_showinfo_1 @ 000001] n: 180 pts: 540000 pts_time:6.000 pos: 3000 fmt:yuv420p
[Parsed_showinfo_1 @ 000001] n: 360 pts: 1080000 pts_time:12.500 pos: 4000 fmt:yuv420p
"""
    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = ""
    mock_run.stderr = fake_stderr

    monkeypatch.setattr("shutil.which", lambda cmd: f"/fake/{cmd}")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_run)

    # With video duration of 10.0s:
    # 0.000 is ignored (start of video)
    # 1.000 is included
    # 3.450 is included
    # 6.000 is included
    # 12.500 is ignored (> duration)
    cuts = detect_cuts(dummy_file, duration=10.0, threshold=0.30)
    assert cuts == [1.0, 3.45, 6.0]


def test_detect_cuts_error_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify detect_cuts raises RuntimeError when ffmpeg exits with error."""
    dummy_file = tmp_path / "video.mp4"
    dummy_file.write_bytes(b"dummy")

    mock_run = MagicMock()
    mock_run.returncode = 1
    mock_run.stdout = ""
    mock_run.stderr = "Error reinitializing filters!"

    monkeypatch.setattr("shutil.which", lambda cmd: f"/fake/{cmd}")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_run)

    with pytest.raises(RuntimeError, match="ffmpeg cut detection failed"):
        detect_cuts(dummy_file, duration=10.0)


# ----------------------------------------------------------------------
# 5. Tests for pick_frame_times
# ----------------------------------------------------------------------


def test_pick_frame_times_hook_and_post_cuts() -> None:
    """Verify pick_frame_times samples hook timestamps and post-cut frames with spacing."""
    # Video duration = 10.0s, cuts at 3.5s and 7.0s
    cuts = [3.5, 7.0]
    duration = 10.0

    times = pick_frame_times(cuts=cuts, duration=duration, fast=False)

    # Standard hook frames: [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    # Post-cuts: 3.5 + 0.15 = 3.65, 7.0 + 0.15 = 7.15
    assert 0.0 in times
    assert 0.5 in times
    assert 1.0 in times
    assert 1.5 in times
    assert 2.0 in times
    assert 2.5 in times
    assert 3.65 in times
    assert 7.15 in times
    assert times == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.65, 7.15]


def test_pick_frame_times_minimum_spacing_deduplication() -> None:
    """Verify candidates too close to hook frames or preceding cuts are dropped."""
    # Cut at 1.0s produces post-cut 1.15s, which is within 0.3s of hook frame 1.0s
    # Rapid cuts at 4.0s, 4.1s, 4.2s produce post-cuts: 4.15s, 4.25s, 4.35s
    cuts = [1.0, 4.0, 4.1, 4.2]
    duration = 10.0

    times = pick_frame_times(cuts=cuts, duration=duration, fast=False)

    # 1.15s should be dropped because 1.0s is already selected
    assert 1.15 not in times
    # 4.15s should be kept
    assert 4.15 in times
    # 4.25s and 4.35s should be dropped (too close to 4.15s)
    assert 4.25 not in times
    assert 4.35 not in times
    assert times == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 4.15]


def test_pick_frame_times_fast_mode() -> None:
    """Verify fast mode uses sparser hook sampling and larger spacing."""
    cuts = [3.5, 3.8, 7.0]
    duration = 10.0

    times = pick_frame_times(cuts=cuts, duration=duration, fast=True)

    # In fast mode: hook frames are [0.0, 1.0, 2.0]
    assert times[:3] == [0.0, 1.0, 2.0]
    # Post cut 3.5 + 0.15 = 3.65 is kept
    assert 3.65 in times
    # Post cut 3.8 + 0.15 = 3.95 is dropped (spacing 1.0s from 3.65)
    assert 3.95 not in times
    # Post cut 7.0 + 0.15 = 7.15 is kept
    assert 7.15 in times
    assert times == [0.0, 1.0, 2.0, 3.65, 7.15]


def test_pick_frame_times_short_or_zero_duration() -> None:
    """Verify edge cases for short videos and zero duration."""
    assert pick_frame_times([], duration=0.0) == []
    assert pick_frame_times([], duration=-2.0) == []

    # Short video under 2.0s: only frames < duration are retained
    short_times = pick_frame_times(cuts=[], duration=1.2)
    assert short_times == [0.0, 0.5, 1.0]


# ----------------------------------------------------------------------
# 6. Live Integration Test (when system ffmpeg / ffprobe are present)
# ----------------------------------------------------------------------


def test_live_ffmpeg_probe_and_cut_pipeline(tmp_path: Path) -> None:
    """Verify live ffmpeg and ffprobe execution when available on the host system."""
    import shutil

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg or ffprobe not installed on this system")

    # Generate synthetic video: 1s black + 1s white with sine audio
    video_path = tmp_path / "live_sample.mp4"
    gen_cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi", "-i", "color=black:duration=1:size=320x240:rate=10",
        "-f", "lavfi", "-i", "color=white:duration=1:size=320x240:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=2",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]",
        "-map", "2:a",
        "-c:v", "libx264",
        "-c:a", "aac",
        str(video_path),
    ]
    gen_proc = subprocess.run(gen_cmd, capture_output=True, text=True, check=False)
    assert gen_proc.returncode == 0, f"FFmpeg failed to create test video: {gen_proc.stderr}"

    # 1. Test probe
    info = probe(video_path)
    assert info["duration"] == pytest.approx(2.0, abs=0.2)
    assert info["width"] == 320
    assert info["height"] == 240
    assert info["fps"] == pytest.approx(10.0, abs=0.5)
    assert info["has_audio"] is True

    # 2. Test detect_cuts
    cuts = detect_cuts(video_path, duration=info["duration"], threshold=0.30)
    assert len(cuts) >= 1
    assert any(pytest.approx(c, abs=0.2) == 1.0 for c in cuts)

    # 3. Test pick_frame_times
    times = pick_frame_times(cuts=cuts, duration=info["duration"])
    assert 0.0 in times
    assert 0.5 in times
    assert all(t < info["duration"] for t in times)

