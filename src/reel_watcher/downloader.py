"""Downloader Engine with Chrome Cookie Injection & Export Parser for Reel-Watcher (`downloader.py`)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

import httpx

from reel_watcher.config import format_status
from reel_watcher.db import extract_shortcode
from reel_watcher.media import id_from_url, probe

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"}
AUDIO_EXTENSIONS = {".m4a", ".mp3", ".aac", ".wav", ".opus", ".ogg"}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

# Windows reserved device names
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str, max_length: int = 128) -> str:
    """Sanitize arbitrary string into safe cross-platform filesystem filename.

    - Replaces OS-invalid characters (\\ / : * ? " < > | and control chars) with underscores.
    - Strips leading/trailing dots and spaces (forbidden on Windows).
    - Escapes Windows reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9).
    - Truncates to max_length.
    - Defaults to 'unnamed' if empty.
    """
    if not name or not isinstance(name, str):
        return "unnamed"

    # Replace forbidden filename characters and control characters
    cleaned = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', "_", name.strip())

    # Replace multiple spaces/underscores with single underscore
    cleaned = re.sub(r"[\s_]+", "_", cleaned)

    # Strip leading/trailing dots and underscores
    cleaned = cleaned.strip("._")

    if not cleaned:
        return "unnamed"

    # Check for Windows reserved names (case-insensitive)
    base_name = cleaned.split(".")[0].upper()
    if base_name in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"

    # Truncate to max_length
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip("._")

    return cleaned or "unnamed"


def _find_video_file(dest_dir: Path, clean_id: str) -> Path | None:
    """Locate downloaded video or audio file matching clean_id in dest_dir."""
    # Direct match: clean_id.<ext>
    for ext in MEDIA_EXTENSIONS:
        candidate = dest_dir / f"{clean_id}{ext}"
        if candidate.exists() and candidate.is_file():
            return candidate

    # Prefix match
    for f in dest_dir.iterdir():
        if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS:
            if f.name.startswith(clean_id):
                return f

    return None


def download_with_apify(
    url: str,
    dest_dir: Path,
    token: str,
    clean_id: str | None = None,
) -> dict:
    """Fallback media downloader using Apify Instagram Reel Scraper actor.

    Args:
        url: Direct Instagram video/reel URL.
        dest_dir: Directory where downloaded video will be saved.
        token: Apify API token.
        clean_id: Canonical identifier for naming.

    Returns:
        Metadata dictionary for downloaded reel.
    """
    dest_dir = Path(dest_dir).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    cid = clean_id or id_from_url(url) or f"reel_{extract_shortcode(url)}"
    safe_stem = sanitize_filename(cid)

    actor_url = (
        f"https://api.apify.com/v2/acts/apify~instagram-reel-scraper/"
        f"run-sync-get-dataset-items?token={token}"
    )

    try:
        post_resp = httpx.post(
            actor_url,
            json={"directUrls": [url]},
            timeout=120.0,
        )
        post_resp.raise_for_status()
        items = post_resp.json()
        if not items or not isinstance(items, list):
            raise RuntimeError(f"Apify returned no dataset items for {url}")

        item = items[0]
        video_url = item.get("videoUrl")
        if not video_url:
            raise RuntimeError(f"No videoUrl present in Apify response for {url}")

        caption = item.get("caption") or item.get("text") or ""
        author = item.get("ownerUsername") or item.get("username") or ""
        likes = item.get("likesCount")
        views = item.get("videoViewCount")
        duration = float(item.get("videoDuration") or 0.0)

        # Download video stream
        video_resp = httpx.get(video_url, follow_redirects=True, timeout=120.0)
        video_resp.raise_for_status()

        video_file = dest_dir / f"{safe_stem}.mp4"
        video_file.write_bytes(video_resp.content)

        info_file = dest_dir / f"{safe_stem}.info.json"
        metadata_dump = {
            "id": cid,
            "title": caption[:60] if caption else safe_stem,
            "uploader": author,
            "description": caption,
            "duration": duration,
            "like_count": likes,
            "view_count": views,
        }
        info_file.write_text(json.dumps(metadata_dump, indent=2), encoding="utf-8")

        print(format_status("+", f"Apify successfully downloaded {cid} to {video_file.name}"), file=sys.stderr)

        return {
            "id": cid,
            "title": metadata_dump["title"],
            "author": author,
            "caption": caption,
            "duration": duration,
            "video_path": video_file,
            "likes": int(likes) if likes is not None else None,
            "views": int(views) if views is not None else None,
        }
    except Exception as exc:
        raise RuntimeError(f"Apify download failed for {url}: {exc}") from exc


def download_media(
    url: str,
    dest_dir: Path | str,
    use_cookies: bool = True,
    browser: str = "chrome",
    apify_token: str | None = None,
    timeout: int = 180,
    audio_only: bool = False,
) -> dict:
    """Download video or audio-first stream and extract rich metadata via yt-dlp with cookie bridge.

    Supports automatic fallback if Chrome cookie database is locked, and optional
    secondary fallback to Apify actor if APIFY_TOKEN is supplied.

    Args:
        url: Video URL to download (Instagram Reels, TikTok, YouTube Shorts).
        dest_dir: Destination folder path.
        use_cookies: Whether to inject browser session cookies.
        browser: Browser identifier for cookie extraction (default: 'chrome').
        apify_token: Optional Apify API token for fallback.
        timeout: Subprocess execution timeout in seconds.
        audio_only: If True, pulls audio-only stream (saving ~85% bandwidth & storage).

    Returns:
        dict: {
            "id": str,
            "title": str,
            "author": str,
            "caption": str,
            "duration": float,
            "video_path": Path,
            "likes": int | None,
            "views": int | None,
        }

    Raises:
        ValueError: If url is empty or invalid.
        RuntimeError: If download fails across all attempted methods.
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise ValueError("url must not be empty")

    url = url.strip()
    dest = Path(dest_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    # Derive canonical ID and safe file stem
    cid = id_from_url(url)
    if not cid:
        shortcode = extract_shortcode(url)
        cid = f"ig_{shortcode}" if shortcode else "reel_unknown"
    safe_stem = sanitize_filename(cid)

    # Base yt-dlp execution arguments (audio-only or full video)
    if audio_only:
        base_cmd = [
            "yt-dlp",
            "--no-playlist",
            "--no-warnings",
            "--write-info-json",
            "-x",
            "--audio-format", "m4a",
            "-o", str(dest / f"{safe_stem}.%(ext)s"),
        ]
    else:
        base_cmd = [
            "yt-dlp",
            "--no-playlist",
            "--no-warnings",
            "--write-info-json",
            "--merge-output-format", "mp4",
            "-f", "bv*[height<=1080]+ba/b[height<=1080]/bv+ba/b",
            "-o", str(dest / f"{safe_stem}.%(ext)s"),
        ]

    last_error = ""
    success = False

    # First attempt: With browser cookies if requested
    if use_cookies:
        cookie_cmd = [*base_cmd, "--cookies-from-browser", browser, url]
        print(format_status("*", f"Attempting yt-dlp download with {browser} cookies for {url}..."), file=sys.stderr)
        proc = subprocess.run(
            cookie_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )

        vid_file = _find_video_file(dest, safe_stem)
        if proc.returncode == 0 or vid_file is not None:
            success = True
        else:
            last_error = proc.stderr.strip()
            print(
                format_status("!", f"Failed to extract cookies from {browser} (locked or unavailable). Retrying without cookies..."),
                file=sys.stderr,
            )

    # Second attempt: Without cookies (or first attempt if use_cookies is False)
    if not success:
        no_cookie_cmd = [*base_cmd, url]
        print(format_status("*", f"Attempting yt-dlp download without cookies for {url}..."), file=sys.stderr)
        proc = subprocess.run(
            no_cookie_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )

        vid_file = _find_video_file(dest, safe_stem)
        if proc.returncode == 0 or vid_file is not None:
            success = True
        else:
            last_error = proc.stderr.strip() or last_error

    # Check for downloaded video file
    video_path = _find_video_file(dest, safe_stem)

    if not success or video_path is None:
        # Check for Apify fallback
        effective_token = apify_token or os.environ.get("APIFY_TOKEN")
        if effective_token:
            print(format_status("*", f"yt-dlp failed, attempting Apify fallback for {url}..."), file=sys.stderr)
            try:
                return download_with_apify(url, dest, token=effective_token, clean_id=cid)
            except Exception as apify_exc:
                raise RuntimeError(
                    f"Failed to download media from {url}: yt-dlp failed ({last_error}) "
                    f"and Apify fallback failed: {apify_exc}"
                ) from apify_exc

        raise RuntimeError(f"Failed to download media from {url} via yt-dlp: {last_error}")

    # Parse metadata from info.json
    info_path = dest / f"{safe_stem}.info.json"
    raw_info: dict[str, Any] = {}
    if info_path.exists():
        try:
            raw_info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            raw_info = {}

    title = str(raw_info.get("title") or "")
    author = str(
        raw_info.get("uploader")
        or raw_info.get("channel")
        or raw_info.get("creator")
        or raw_info.get("uploader_id")
        or ""
    )
    caption = str(
        raw_info.get("description")
        or raw_info.get("caption")
        or title
    )

    duration = float(raw_info.get("duration") or 0.0)
    if duration <= 0.0:
        try:
            p_res = probe(video_path)
            duration = float(p_res.get("duration") or 0.0)
        except Exception:
            pass

    likes_val = raw_info.get("like_count")
    likes = int(likes_val) if likes_val is not None else None

    views_val = raw_info.get("view_count")
    views = int(views_val) if views_val is not None else None

    print(format_status("+", f"Successfully downloaded {cid} to {video_path.name}"), file=sys.stderr)

    return {
        "id": cid,
        "title": title,
        "author": author,
        "caption": caption,
        "duration": duration,
        "video_path": video_path,
        "likes": likes,
        "views": views,
    }
