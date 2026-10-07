"""Tests for Additive Long-Form YouTube Deconstruction Module (`longform.py`)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from reel_watcher.longform import (
    align_transcript_to_chapters,
    extract_chapter_keyframes,
    fetch_subtitles,
    get_longform_metadata,
    parse_vtt,
    synthesize_chapters,
    analyze_longform_study,
)


SAMPLE_VTT = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.500
Welcome back to the channel. Today we're diving into AI architecture.

00:00:03.500 --> 00:00:06.000
Welcome back to the channel. Today we're diving into AI architecture.
Specifically, how agent memory scales.

00:00:06.000 --> 00:00:09.500
Specifically, how agent memory scales.
Let's look at the first diagram.
"""


def test_parse_vtt_cleans_and_deduplicates():
    cues = parse_vtt(SAMPLE_VTT)
    assert len(cues) >= 2
    full_text = " ".join(c["text"] for c in cues)
    assert "Welcome back to the channel" in full_text
    assert "agent memory scales" in full_text
    assert "first diagram" in full_text
    # Ensure repeated scrolling text is deduplicated
    assert full_text.count("Welcome back to the channel.") == 1


def test_parse_vtt_empty():
    assert parse_vtt("") == []
    assert parse_vtt("WEBVTT\n\n") == []


def test_synthesize_chapters():
    # Short video (e.g. 120s) -> single chapter
    short_ch = synthesize_chapters(120.0)
    assert len(short_ch) == 1
    assert short_ch[0]["start_time"] == 0.0

    # 30-minute video (1800s) -> split into 5-minute chunks (300s)
    long_ch = synthesize_chapters(1800.0, chunk_seconds=300.0)
    assert len(long_ch) == 6
    assert long_ch[0]["start_time"] == 0.0
    assert long_ch[0]["end_time"] == 300.0
    assert long_ch[-1]["end_time"] == 1800.0


def test_align_transcript_to_chapters():
    chapters = [
        {"title": "Intro", "start_time": 0.0, "end_time": 10.0},
        {"title": "Core Breakdown", "start_time": 10.0, "end_time": 30.0},
    ]
    cues = [
        {"start": 1.0, "end": 4.0, "text": "Hello world."},
        {"start": 12.0, "end": 18.0, "text": "Deep dive into agents."},
        {"start": 25.0, "end": 28.0, "text": "Final thoughts on this section."},
    ]

    aligned = align_transcript_to_chapters(chapters, cues)
    assert len(aligned) == 2
    assert "Hello world." in aligned[0]["transcript"]
    assert "Deep dive into agents." in aligned[1]["transcript"]
    assert "Final thoughts" in aligned[1]["transcript"]


@patch("subprocess.run")
def test_get_longform_metadata_mocked(mock_run):
    sample_json = {
        "id": "dQw4w9WgXcQ",
        "title": "Mastering Agent Systems in 2026",
        "uploader": "Tech Lead",
        "channel": "Tech Lead",
        "duration": 1200.0,
        "description": "Comprehensive guide to multi-agent architectures.",
        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "chapters": [
            {"title": "Introduction", "start_time": 0.0, "end_time": 180.0},
            {"title": "Memory Models", "start_time": 180.0, "end_time": 600.0},
            {"title": "Tool Dispatch", "start_time": 600.0, "end_time": 1200.0},
        ],
    }
    mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(sample_json), stderr="")

    meta = get_longform_metadata("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert meta["id"] == "dQw4w9WgXcQ"
    assert meta["title"] == "Mastering Agent Systems in 2026"
    assert meta["author"] == "Tech Lead"
    assert meta["duration"] == 1200.0
    assert len(meta["chapters"]) == 3


@patch("subprocess.run")
def test_fetch_subtitles_mocked(mock_run, tmp_path: Path):
    vtt_file = tmp_path / "test_video.en.vtt"
    vtt_file.write_text(SAMPLE_VTT, encoding="utf-8")

    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    cues = fetch_subtitles("https://www.youtube.com/watch?v=test", tmp_path)
    assert len(cues) >= 2
    assert "Welcome back" in cues[0]["text"]


@patch("reel_watcher.longform.extract_frame_jpg")
def test_extract_chapter_keyframes_mocked(mock_extract, tmp_path: Path):
    mock_extract.side_effect = lambda v, t, out: Path(out).write_text("fake_jpg")
    chapters = [
        {"title": "Intro", "start_time": 0.0, "end_time": 100.0},
        {"title": "Section 2", "start_time": 100.0, "end_time": 200.0},
    ]
    tiles = extract_chapter_keyframes("dummy.mp4", chapters, tmp_path)
    assert len(tiles) == 2
    assert tiles[0][0].exists()
    assert tiles[0][1] == "Intro"


@patch("reel_watcher.longform.get_longform_metadata")
@patch("reel_watcher.longform.fetch_subtitles")
@patch("reel_watcher.longform.extract_chapter_keyframes")
@patch("reel_watcher.longform.make_contact_sheet")
def test_analyze_longform_study_mocked_end_to_end(
    mock_sheet, mock_extract, mock_subs, mock_meta, tmp_path: Path
):
    mock_meta.return_value = {
        "id": "abc123long",
        "shortcode": "abc123long",
        "url": "https://www.youtube.com/watch?v=abc123long",
        "title": "Scaling Modern AI Startups",
        "author": "Gwelix Insights",
        "duration": 900.0,
        "description": "Full teardown of engineering systems.",
        "chapters": [
            {"title": "The Big Shift", "start_time": 0.0, "end_time": 300.0},
            {"title": "Execution Blueprint", "start_time": 300.0, "end_time": 900.0},
        ],
    }
    mock_subs.return_value = [
        {"start": 10.0, "end": 20.0, "text": "Welcome everyone to the shift."},
        {"start": 350.0, "end": 370.0, "text": "Here is the exact execution playbook."},
    ]
    dummy_frame = tmp_path / "frame1.jpg"
    dummy_frame.write_text("fake")
    mock_extract.return_value = [(dummy_frame, "The Big Shift")]

    vision_mock = MagicMock()
    vision_mock.ask_contact_sheet.return_value = {
        "summary": "Detailed exploration of scaling agent systems.",
        "framework": "System Blueprint",
        "score": 9.2,
        "executive_summary": "Comprehensive long-form guide.",
        "core_thesis": "Agents must be zero-touch and deterministic.",
        "chapters": [
            {
                "title": "The Big Shift",
                "timestamp": "0:00",
                "summary": "Why the shift matters.",
                "insights": ["Point 1", "Point 2"],
            }
        ],
        "actionable_takeaways": ["Build small primitives", "Verify before ship"],
    }

    study = analyze_longform_study(
        url="https://www.youtube.com/watch?v=abc123long",
        work_dir=tmp_path,
        vision=vision_mock,
    )

    assert study["shortcode"] == "abc123long"
    assert study["media_type"] == "longform"
    assert study["title"] == "Scaling Modern AI Startups"
    assert study["author"] == "Gwelix Insights"
    assert study["duration"] == 900.0
    assert len(study["chapters"]) == 2
    assert "execution playbook" in study["transcript"]["text"]
    assert study["score"] == 9.2
    assert "core_thesis" in study["longform_analysis"]
    assert "markdown" in study
    assert "## Executive Summary" in study["markdown"]


@patch("reel_watcher.cli.analyze_longform_study")
def test_cli_longform_subcommand(mock_study, tmp_path: Path):
    from reel_watcher.cli import main

    mock_study.return_value = {
        "shortcode": "yt_test_123",
        "url": "https://www.youtube.com/watch?v=yt_test_123",
        "title": "Test Title",
        "author": "Creator",
        "score": 9.0,
        "media_type": "longform",
        "markdown": "# Test Title\n## Executive Summary\nContent",
    }

    db_file = tmp_path / "test_vault.db"
    out_root = tmp_path / "vault"

    ret = main([
        "longform",
        "https://www.youtube.com/watch?v=yt_test_123",
        "--provider", "fake",
        "--db", str(db_file),
        "--out-root", str(out_root),
        "--no-cookies",
    ])

    assert ret == 0
    assert (out_root / "study" / "yt_test_123_longform.md").exists()
