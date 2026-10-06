"""Tests for Reel-Watcher Downloader Engine (`downloader.py`)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from reel_watcher.downloader import (
    download_media,
    download_with_apify,
    sanitize_filename,
)


def test_sanitize_filename_basic() -> None:
    """Test sanitization of standard alphanumeric strings."""
    assert sanitize_filename("simple_title") == "simple_title"
    assert sanitize_filename("Title With Spaces") == "Title_With_Spaces"
    assert sanitize_filename("Title   Multiple   Spaces") == "Title_Multiple_Spaces"


def test_sanitize_filename_invalid_characters() -> None:
    """Test removal and replacement of OS-forbidden characters."""
    raw = 'Bad/Name\\With:Illegal*Chars?"And<Arrows>|Pipe'
    cleaned = sanitize_filename(raw)
    for bad_char in r'/\:*?"<>|':
        assert bad_char not in cleaned
    assert "Bad_Name_With_Illegal_Chars_And_Arrows_Pipe" in cleaned


def test_sanitize_filename_reserved_windows_names() -> None:
    """Test handling of Windows reserved device names (CON, PRN, AUX, NUL, COM1, etc.)."""
    for reserved in ["CON", "prn", "AUX", "NUL", "COM1", "lpt3"]:
        sanitized = sanitize_filename(reserved)
        assert sanitized != reserved.upper()
        assert sanitized.lower() != reserved.lower()
        assert sanitized.startswith(f"_{reserved}") or sanitized.endswith("_")


def test_sanitize_filename_empty_or_whitespace() -> None:
    """Test fallback when string is empty, whitespace, or only illegal characters."""
    assert sanitize_filename("") == "unnamed"
    assert sanitize_filename("   ") == "unnamed"
    assert sanitize_filename("...:::???***...") == "unnamed"


def test_sanitize_filename_max_length() -> None:
    """Test truncation to maximum length."""
    long_name = "a" * 300
    sanitized = sanitize_filename(long_name, max_length=50)
    assert len(sanitized) <= 50
    assert sanitized.startswith("aaa")


def test_download_media_empty_url_raises_value_error(tmp_path: Path) -> None:
    """Test that empty or blank URL raises ValueError."""
    with pytest.raises(ValueError, match="url must not be empty"):
        download_media("", tmp_path)
    with pytest.raises(ValueError, match="url must not be empty"):
        download_media("   ", tmp_path)


def test_download_media_success_with_cookies(tmp_path: Path) -> None:
    """Test successful download with Chrome cookie injection."""
    url = "https://www.instagram.com/reel/C123abc456/"
    expected_id = "ig_C123abc456"

    def fake_run(cmd, *args, **kwargs):
        # cmd will include -o <dest_dir>/ig_C123abc456.%(ext)s
        # create the expected output video and info.json
        vid_path = tmp_path / f"{expected_id}.mp4"
        vid_path.write_bytes(b"dummy video data")
        info_path = tmp_path / f"{expected_id}.info.json"
        info_path.write_text(
            json.dumps({
                "id": "C123abc456",
                "title": "Viral Hook Secret",
                "uploader": "growthcreator",
                "description": "Here is how to hook viewers in 3 seconds #reels",
                "duration": 18.5,
                "like_count": 14200,
                "view_count": 250000,
            }),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("reel_watcher.downloader.subprocess.run", side_effect=fake_run) as mock_run:
        result = download_media(url, tmp_path, use_cookies=True, browser="chrome")

    assert result["id"] == expected_id
    assert result["title"] == "Viral Hook Secret"
    assert result["author"] == "growthcreator"
    assert result["duration"] == 18.5
    assert result["likes"] == 14200
    assert result["views"] == 250000
    assert result["video_path"] == tmp_path / f"{expected_id}.mp4"
    assert result["video_path"].exists()

    # Check subprocess was called with --cookies-from-browser chrome
    called_cmd = mock_run.call_args[0][0]
    assert "--cookies-from-browser" in called_cmd
    assert "chrome" in called_cmd


def test_download_media_cookie_lock_graceful_fallback(tmp_path: Path) -> None:
    """Test graceful fallback to cookie-less download when browser database is locked."""
    url = "https://www.instagram.com/reel/C999xyz888/"
    expected_id = "ig_C999xyz888"
    call_count = 0

    def fake_run(cmd, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if "--cookies-from-browser" in cmd:
            # First call fails due to Chrome lock
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=1,
                stdout="",
                stderr="[Cookies] Could not copy Chrome cookie database: database is locked",
            )
        # Second call without cookies succeeds
        vid_path = tmp_path / f"{expected_id}.mp4"
        vid_path.write_bytes(b"dummy video data")
        info_path = tmp_path / f"{expected_id}.info.json"
        info_path.write_text(
            json.dumps({
                "id": "C999xyz888",
                "title": "Fallback Video",
                "uploader": "testuser",
                "description": "Caption text",
                "duration": 12.0,
            }),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("reel_watcher.downloader.subprocess.run", side_effect=fake_run) as mock_run:
        result = download_media(url, tmp_path, use_cookies=True, browser="chrome")

    assert call_count == 2
    assert result["id"] == expected_id
    assert result["title"] == "Fallback Video"
    assert result["author"] == "testuser"
    assert result["duration"] == 12.0
    assert result["video_path"] == tmp_path / f"{expected_id}.mp4"


def test_download_media_no_cookies_flag(tmp_path: Path) -> None:
    """Test that use_cookies=False bypasses cookie extraction entirely."""
    url = "https://www.tiktok.com/@creator/video/7123456789"
    expected_id = "tt_7123456789"

    def fake_run(cmd, *args, **kwargs):
        vid_path = tmp_path / f"{expected_id}.mp4"
        vid_path.write_bytes(b"dummy video")
        info_path = tmp_path / f"{expected_id}.info.json"
        info_path.write_text(
            json.dumps({
                "id": "7123456789",
                "title": "TikTok Trend",
                "uploader": "creator",
                "duration": 15.0,
            }),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("reel_watcher.downloader.subprocess.run", side_effect=fake_run) as mock_run:
        result = download_media(url, tmp_path, use_cookies=False)

    called_cmd = mock_run.call_args[0][0]
    assert "--cookies-from-browser" not in called_cmd
    assert result["id"] == expected_id
    assert result["title"] == "TikTok Trend"


def test_download_media_custom_browser(tmp_path: Path) -> None:
    """Test that custom browser string (e.g. edge, firefox) is respected."""
    url = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
    expected_id = "yt_dQw4w9WgXcQ"

    def fake_run(cmd, *args, **kwargs):
        vid_path = tmp_path / f"{expected_id}.mp4"
        vid_path.write_bytes(b"dummy")
        info_path = tmp_path / f"{expected_id}.info.json"
        info_path.write_text(
            json.dumps({
                "id": "dQw4w9WgXcQ",
                "title": "Shorts Hit",
                "uploader": "rick",
                "duration": 30.0,
            }),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("reel_watcher.downloader.subprocess.run", side_effect=fake_run) as mock_run:
        result = download_media(url, tmp_path, use_cookies=True, browser="firefox")

    called_cmd = mock_run.call_args[0][0]
    assert "--cookies-from-browser" in called_cmd
    assert "firefox" in called_cmd
    assert result["id"] == expected_id


def test_download_media_yt_dlp_failure_raises_runtime_error(tmp_path: Path) -> None:
    """Test RuntimeError is raised when yt-dlp fails and no Apify fallback is present."""
    url = "https://www.instagram.com/reel/InvalidUrl123/"

    def fake_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="",
            stderr="ERROR: [Instagram] InvalidUrl123: Requested content is not available",
        )

    with patch("reel_watcher.downloader.subprocess.run", side_effect=fake_run):
        with pytest.raises(RuntimeError, match="Failed to download"):
            download_media(url, tmp_path, use_cookies=True, apify_token=None)


def test_download_with_apify_direct_success(tmp_path: Path) -> None:
    """Test direct download_with_apify helper function."""
    url = "https://www.instagram.com/reel/C123apify/"
    token = "apify_api_mock_token_123"

    mock_items = [
        {
            "id": "C123apify",
            "videoUrl": "https://cdn.instagram.com/dummy.mp4",
            "caption": "Apify Scraped Caption",
            "ownerUsername": "apify_creator",
            "likesCount": 8900,
            "videoViewCount": 120000,
            "videoDuration": 24.5,
        }
    ]

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = mock_items

    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.content = b"apify downloaded video binary"

    with patch("httpx.post", return_value=mock_post_resp) as mock_post, \
         patch("httpx.get", return_value=mock_get_resp) as mock_get:
        res = download_with_apify(url, tmp_path, token=token, clean_id="ig_C123apify")

    assert res["id"] == "ig_C123apify"
    assert res["author"] == "apify_creator"
    assert res["caption"] == "Apify Scraped Caption"
    assert res["duration"] == 24.5
    assert res["likes"] == 8900
    assert res["views"] == 120000
    assert res["video_path"].exists()


def test_download_media_apify_fallback_triggered_on_yt_dlp_failure(tmp_path: Path) -> None:
    """Test that Apify fallback is invoked when yt-dlp fails and apify_token is set."""
    url = "https://www.instagram.com/reel/LoginGatedReel/"
    token = "apify_mock_token"

    def fake_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="",
            stderr="ERROR: Login required to view this reel",
        )

    expected_return = {
        "id": "ig_LoginGatedReel",
        "title": "Apify Rescued",
        "author": "rescued_creator",
        "caption": "Apify caption",
        "duration": 15.0,
        "video_path": tmp_path / "ig_LoginGatedReel.mp4",
        "likes": 500,
        "views": 2000,
    }

    with patch("reel_watcher.downloader.subprocess.run", side_effect=fake_run), \
         patch("reel_watcher.downloader.download_with_apify", return_value=expected_return) as mock_apify:
        result = download_media(url, tmp_path, use_cookies=True, apify_token=token)

    mock_apify.assert_called_once()
    assert result == expected_return
