"""Unit and integration tests for Static Advice Library (`advice_library.py`)."""

from __future__ import annotations

import html
import json
from pathlib import Path

import pytest

from reel_watcher.advice_library import render_advice_html


@pytest.fixture
def sample_studies() -> list[dict]:
    """Sample study records mimicking end-to-end study pipeline outputs."""
    return [
        {
            "code": "CXYZ1234",
            "shortcode": "CXYZ1234",
            "url": "https://www.instagram.com/reel/CXYZ1234/",
            "collection": "growth_hacks",
            "title": "Scaling to $100k with AI",
            "author": "alex_founder",
            "duration": 24.5,
            "width": 1080,
            "height": 1920,
            "fps": 30.0,
            "hook_text": "Stop building tools nobody wants",
            "summary": "Breakdown of audience-first SaaS validation with automated comment-to-DM funnels.",
            "framework": "Problem-Agitate-Solve",
            "score": 9.2,
            "cuts": [1.5, 3.8, 7.2, 12.0, 18.5],
            "cuts_count": 5,
            "frame_count": 6,
            "transcript": {
                "text": "Stop building tools nobody wants. Comment SCALE below for the 5-step framework.",
                "language": "en",
                "words": [
                    {"w": "Stop", "s": 0.0, "e": 0.3},
                    {"w": "building", "s": 0.3, "e": 0.7},
                    {"w": "tools", "s": 0.7, "e": 1.1},
                ],
            },
            "audio_analysis": {
                "has_music_bed": True,
                "has_dead_silence": False,
                "speech_ratio": 0.82,
            },
            "giveaway": {
                "has_giveaway": True,
                "comment_words": ["SCALE"],
                "action": "comment",
                "offer": "5-step SaaS validation framework",
                "confidence": 0.95,
            },
            "visual_analysis": {
                "hook": {
                    "text": "Stop building tools nobody wants",
                    "visual_style": "High-contrast talking head with yellow keyword pop",
                    "rating": 9.5,
                },
                "summary": "Audience-first validation breakdown",
                "framework": "Problem-Agitate-Solve",
                "pacing": {
                    "style": "fast",
                    "average_shot_duration": 2.1,
                    "energy": "high",
                },
                "cta": {
                    "action": "comment",
                    "keyword": "SCALE",
                    "offer": "Validation framework",
                },
                "score": 9.2,
                "scenes": [
                    {"tile": 1, "description": "Bold negative hook frame"},
                    {"tile": 2, "description": "Pain point breakdown"},
                ],
                "strengths": ["Bold negative opener", "Clear comment trigger", "Dynamic pacing"],
                "weaknesses": ["Lighting slightly dark in scene 2"],
            },
            "contact_sheet": "vault/study/sheets/CXYZ1234_sheet.jpg",
            "created_at": "2026-10-06T06:00:00Z",
        },
        {
            "code": "DABC5678",
            "shortcode": "DABC5678",
            "url": "https://www.tiktok.com/@growth_lab/video/789101112",
            "collection": "content_strategy",
            "title": "3 Camera Angles in 10 Seconds",
            "author": "creative_director",
            "duration": 18.0,
            "width": 1080,
            "height": 1920,
            "fps": 60.0,
            "hook_text": "This editing trick tripled my retention",
            "summary": "Demonstration of jump cuts and multi-camera phone repositioning.",
            "framework": "Before-After-Bridge",
            "score": 8.4,
            "cuts": [0.8, 2.2, 4.1, 7.5],
            "cuts_count": 4,
            "frame_count": 5,
            "transcript": {
                "text": "This editing trick tripled my retention. Check the link in bio for preset pack.",
                "language": "en",
                "words": [],
            },
            "audio_analysis": {
                "has_music_bed": False,
                "has_dead_silence": False,
                "speech_ratio": 0.65,
            },
            "giveaway": {
                "has_giveaway": True,
                "comment_words": [],
                "action": "link_in_bio",
                "offer": "Free CapCut preset pack",
                "confidence": 0.85,
            },
            "visual_analysis": {
                "hook": {
                    "text": "This editing trick tripled my retention",
                    "visual_style": "Whip pan transition with split screen",
                    "rating": 8.7,
                },
                "summary": "Camera repositioning editing hack",
                "framework": "Before-After-Bridge",
                "pacing": {
                    "style": "ultra-fast",
                    "average_shot_duration": 1.4,
                    "energy": "very high",
                },
                "cta": {
                    "action": "link_in_bio",
                    "keyword": "",
                    "offer": "Preset pack",
                },
                "score": 8.4,
                "strengths": ["Instant pattern interrupt", "Show-don't-tell execution"],
                "weaknesses": ["Voiceover volume low relative to sfx"],
            },
            "contact_sheet": "vault/study/sheets/DABC5678_sheet.jpg",
            "created_at": "2026-10-06T06:05:00Z",
        },
    ]


def test_render_advice_html_empty_studies(tmp_path: Path) -> None:
    """Ensure rendering an empty study list produces a valid, clean HTML file."""
    out_file = tmp_path / "empty_advice.html"
    result_path = render_advice_html([], out_file, title="Custom Empty Library")

    assert result_path == out_file
    assert out_file.is_file()

    content = out_file.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "Custom Empty Library" in content
    assert "0" in content  # 0 studies recorded
    assert "No studies found" in content or "No reels analyzed" in content


def test_render_advice_html_creates_parent_directories(tmp_path: Path) -> None:
    """Ensure non-existent parent directories are created automatically."""
    out_file = tmp_path / "sub" / "folder" / "deep" / "library.html"
    result_path = render_advice_html([], out_file)

    assert result_path == out_file
    assert out_file.is_file()


def test_render_advice_html_self_contained(tmp_path: Path, sample_studies: list[dict]) -> None:
    """Enforce zero external network dependencies (no remote scripts, fonts, or stylesheets)."""
    out_file = tmp_path / "advice.html"
    render_advice_html(sample_studies, out_file)

    content = out_file.read_text(encoding="utf-8")

    # Zero external stylesheet or script references
    assert "<link rel=\"stylesheet\" href=\"http" not in content
    assert "<script src=\"http" not in content
    assert "fonts.googleapis.com" not in content
    assert "cdnjs.cloudflare.com" not in content

    # Contains embedded <style> and <script>
    assert "<style>" in content
    assert "</style>" in content
    assert "<script>" in content
    assert "</script>" in content


def test_render_advice_html_content_and_metadata(
    tmp_path: Path, sample_studies: list[dict]
) -> None:
    """Verify that all core study attributes, metrics, and cards are rendered correctly."""
    out_file = tmp_path / "advice.html"
    render_advice_html(sample_studies, out_file, title="Master Viral Playbook")

    content = out_file.read_text(encoding="utf-8")

    # Title & Branding
    assert "Master Viral Playbook" in content

    # Study items presence
    assert "CXYZ1234" in content
    assert "DABC5678" in content
    assert "Scaling to $100k with AI" in content
    assert "alex_founder" in content
    assert "creative_director" in content

    # Framework & Hook details
    assert "Problem-Agitate-Solve" in content
    assert "Before-After-Bridge" in content
    assert "Stop building tools nobody wants" in content
    assert "This editing trick tripled my retention" in content

    # Giveaway & Funnel details
    assert "SCALE" in content
    assert "5-step SaaS validation framework" in content
    assert "link_in_bio" in content or "Link In Bio" in content

    # Strengths and weaknesses
    assert "Bold negative opener" in content
    assert "Clear comment trigger" in content

    # Summary metrics header
    assert "2" in content  # Total 2 reels


def test_render_advice_html_local_storage_persistence(
    tmp_path: Path, sample_studies: list[dict]
) -> None:
    """Verify interactive checkboxes and notes textarea integrate with localStorage."""
    out_file = tmp_path / "advice.html"
    render_advice_html(sample_studies, out_file)

    content = out_file.read_text(encoding="utf-8")

    # Checkboxes and notes elements
    assert "checkbox" in content
    assert "<textarea" in content
    assert "localStorage" in content
    assert "localStorage.getItem" in content
    assert "localStorage.setItem" in content

    # Item-specific IDs or keys for persistence
    assert "CXYZ1234" in content
    assert "DABC5678" in content


def test_render_advice_html_xss_escaping(tmp_path: Path) -> None:
    """Verify unsafe strings in titles or text are properly escaped."""
    xss_study = [
        {
            "code": "XSS123",
            "shortcode": "XSS123",
            "url": "https://instagram.com/reel/XSS123/",
            "title": "<script>alert('pwned')</script>",
            "author": "<b>hacker</b>",
            "hook_text": "Safe hook & <unescaped>",
            "summary": "Summary with \"quotes\" & ampersands",
            "framework": "Framework <test>",
            "score": 7.5,
        }
    ]

    out_file = tmp_path / "xss_advice.html"
    render_advice_html(xss_study, out_file, title="<script>alert('title')</script>")

    content = out_file.read_text(encoding="utf-8")

    # Malicious raw tags should NOT appear unescaped
    assert "<script>alert('pwned')</script>" not in content
    assert "&lt;script&gt;alert(&#x27;pwned&#x27;)&lt;/script&gt;" in content or "&lt;script&gt;alert('pwned')&lt;/script&gt;" in content
    assert "&lt;b&gt;hacker&lt;/b&gt;" in content
    assert "&lt;script&gt;alert(&#x27;title&#x27;)&lt;/script&gt;" in content or "&lt;script&gt;alert('title')&lt;/script&gt;" in content
