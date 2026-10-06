"""Media Utilities & Scene Cut Engine for Reel-Watcher (`media.py`)."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from reel_watcher.config import format_status


def preflight() -> str:
    """Verify ffmpeg and ffprobe binaries exist on system PATH.

    Returns:
        Empty string if both binaries are present, otherwise user-friendly
        cross-platform installation instructions.
    """
    missing: list[str] = []
    if not shutil.which("ffmpeg"):
        missing.append("ffmpeg")
    if not shutil.which("ffprobe"):
        missing.append("ffprobe")

    if not missing:
        return ""

    missing_str = ", ".join(missing)
    return (
        f"Missing required media dependencies: {missing_str}.\n"
        "Please install FFmpeg and verify it is accessible on your system PATH.\n"
        "  Windows: winget install Gyan.FFmpeg\n"
        "  macOS:   brew install ffmpeg\n"
        "  Linux:   sudo apt update && sudo apt install -y ffmpeg"
    )


def id_from_url(url: str) -> str | None:
    """Parse video URL into normalized platform-prefixed identifier.

    Supported platforms:
    - Instagram: ig_<code> (from /reel/, /reels/, /p/, /share/reel/)
    - TikTok: tt_<code> (from /video/, /v/, /t/, vm.tiktok.com)
    - YouTube Shorts: yt_<code> (from /shorts/, youtu.be, watch?v=)

    Also returns the string unchanged if already in normalized format (ig_*, tt_*, yt_*).
    Returns None if unparseable or unsupported.
    """
    if not url or not isinstance(url, str):
        return None

    cleaned = url.strip()
    if not cleaned:
        return None

    # Already normalized format
    if re.match(r"^(ig|tt|yt)_[A-Za-z0-9_-]+$", cleaned):
        return cleaned

    # Instagram
    ig_match = re.search(
        r"(?:instagram\.com/(?:reel|reels|p|share/reel)/)([A-Za-z0-9_-]+)",
        cleaned,
    )
    if ig_match:
        return f"ig_{ig_match.group(1)}"

    # TikTok
    tt_match = re.search(
        r"(?:tiktok\.com/@[^/]+/video/|tiktok\.com/v/|vm\.tiktok\.com/|tiktok\.com/t/)([A-Za-z0-9_-]+)",
        cleaned,
    )
    if tt_match:
        return f"tt_{tt_match.group(1)}"

    # YouTube Shorts / youtu.be
    yt_shorts_match = re.search(
        r"(?:youtube\.com/shorts/|youtu\.be/)([A-Za-z0-9_-]+)",
        cleaned,
    )
    if yt_shorts_match:
        return f"yt_{yt_shorts_match.group(1)}"

    # YouTube watch?v=
    yt_watch_match = re.search(
        r"youtube\.com/watch\?.*v=([A-Za-z0-9_-]+)",
        cleaned,
    )
    if yt_watch_match:
        return f"yt_{yt_watch_match.group(1)}"

    return None


def _parse_fps(rate: str | None) -> float:
    """Parse frame rate string (e.g. '30/1' or '29.97') into float."""
    if not rate or rate == "0/0":
        return 0.0

    if "/" in rate:
        parts = rate.split("/", 1)
        try:
            num = float(parts[0])
            den = float(parts[1])
            return num / den if den != 0.0 else 0.0
        except ValueError:
            return 0.0

    try:
        return float(rate)
    except ValueError:
        return 0.0


def probe(path: str | Path) -> dict[str, Any]:
    """Inspect video media properties via ffprobe.

    Args:
        path: Path to video file.

    Returns:
        dict with keys:
            - duration: float (seconds)
            - width: int (pixels)
            - height: int (pixels)
            - fps: float (frames per second)
            - has_audio: bool

    Raises:
        FileNotFoundError: If the specified file does not exist.
        RuntimeError: If ffprobe is missing or execution fails.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Media file not found: {file_path}")

    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe is not found on PATH. Run preflight() for installation instructions.")

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(file_path),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as exc:
        raise RuntimeError(f"Failed to execute ffprobe: {exc}") from exc

    if proc.returncode != 0:
        snippet = proc.stderr.strip()[:200]
        raise RuntimeError(f"ffprobe failed (exit code {proc.returncode}): {snippet}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse ffprobe JSON output: {exc}") from exc

    streams: list[dict[str, Any]] = data.get("streams", [])
    fmt: dict[str, Any] = data.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    width = int(video_stream.get("width", 0)) if video_stream else 0
    height = int(video_stream.get("height", 0)) if video_stream else 0

    fps = 0.0
    if video_stream:
        fps = _parse_fps(video_stream.get("r_frame_rate")) or _parse_fps(video_stream.get("avg_frame_rate"))

    duration = 0.0
    if fmt.get("duration"):
        try:
            duration = float(fmt["duration"])
        except (ValueError, TypeError):
            pass
    if duration <= 0.0 and video_stream and video_stream.get("duration"):
        try:
            duration = float(video_stream["duration"])
        except (ValueError, TypeError):
            pass

    return {
        "duration": round(duration, 3),
        "width": width,
        "height": height,
        "fps": round(fps, 3),
        "has_audio": bool(has_audio),
    }


def detect_cuts(video: str | Path, duration: float, threshold: float = 0.30) -> list[float]:
    """Detect shot scene cuts using ffmpeg scene detection filter.

    Uses `select='gt(scene,<threshold>)',showinfo` to locate transition frames.

    Args:
        video: Path to target video file.
        duration: Total video duration in seconds.
        threshold: Scene change sensitivity threshold (default 0.30).

    Returns:
        Sorted list of cut timestamps in seconds.
    """
    if duration <= 0.0:
        return []

    file_path = Path(video)
    if not file_path.is_file():
        raise FileNotFoundError(f"Video file not found: {file_path}")

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not found on PATH. Run preflight() for installation instructions.")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(file_path),
        "-vf",
        f"select='gt(scene,{threshold})',showinfo",
        "-f",
        "null",
        "-",
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as exc:
        raise RuntimeError(f"Failed to execute ffmpeg: {exc}") from exc

    if proc.returncode != 0:
        snippet = proc.stderr.strip()[-300:]
        raise RuntimeError(f"ffmpeg cut detection failed (exit code {proc.returncode}): {snippet}")

    # Parse timestamps from showinfo lines in stderr: pts_time:1.240
    raw_timestamps = re.findall(r"pts_time:\s*([0-9]+(?:\.[0-9]+)?)", proc.stderr)
    cuts: list[float] = []

    for ts_str in raw_timestamps:
        try:
            ts = round(float(ts_str), 3)
            # Must be strictly after video start (0.0) and before total duration
            if 0.0 < ts < duration:
                # Deduplicate cuts occurring too close to preceding cut (< 0.1s)
                if not cuts or abs(ts - cuts[-1]) >= 0.1:
                    cuts.append(ts)
        except ValueError:
            continue

    return sorted(cuts)


def pick_frame_times(
    cuts: list[float],
    duration: float,
    fast: bool = False,
    min_spacing: float | None = None,
) -> list[float]:
    """Sample hook frames and post-cut transition frames with minimum spacing.

    Hook frames are prioritized at [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]s (or [0.0, 1.0, 2.0]s in fast mode).
    Post-cut frames are sampled at (cut + 0.15s).

    Args:
        cuts: List of detected scene cut timestamps in seconds.
        duration: Total video duration in seconds.
        fast: Whether to use sparse sampling for lower latency.
        min_spacing: Minimum separation in seconds between frames (defaults to 1.0s if fast else 0.3s).

    Returns:
        Sorted list of candidate frame timestamps strictly less than duration.
    """
    if duration <= 0.0:
        return []

    if min_spacing is None:
        spacing = 1.0 if fast else 0.3
    else:
        spacing = min_spacing

    # Hook frame sample times
    hook_candidates = [0.0, 1.0, 2.0] if fast else [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    selected: list[float] = [round(t, 3) for t in hook_candidates if t < duration]

    # Post-cut frames: c + 0.15s
    for c in sorted(cuts):
        if c < 0.0:
            continue
        candidate = round(c + 0.15, 3)
        if candidate >= duration:
            continue
        # Ensure minimum spacing from all currently selected frame times
        if all(abs(candidate - s) >= spacing for s in selected):
            selected.append(candidate)

    return sorted(selected)
