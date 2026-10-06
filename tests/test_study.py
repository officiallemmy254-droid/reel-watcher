"""Unit and integration tests for Study & Synthesis Pipeline (`study.py`)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image
import pytest

from reel_watcher.study import (
    analyze_carousel_study,
    analyze_video_study,
    parse_comment_words,
    parse_giveaway,
)
from reel_watcher.vision import VisionClient


@pytest.fixture
def dummy_image_file(tmp_path: Path) -> Path:
    """Create a temporary image file."""
    p = tmp_path / "slide.jpg"
    img = Image.new("RGB", (200, 200), color=(100, 150, 200))
    img.save(p, "JPEG")
    return p


# ==============================================================================
# 1. parse_comment_words Tests
# ==============================================================================


def test_parse_comment_words_empty() -> None:
    assert parse_comment_words() == []
    assert parse_comment_words("", "   ", None) == []


def test_parse_comment_words_quoted() -> None:
    text1 = "Comment 'SCALE' below and I'll send you the system!"
    assert parse_comment_words(text1) == ["SCALE"]

    text2 = 'Drop "AI" in comments for immediate access'
    assert parse_comment_words(text2) == ["AI"]

    text3 = "Comment “WORKFLOW” 👇"
    assert parse_comment_words(text3) == ["WORKFLOW"]


def test_parse_comment_words_unquoted() -> None:
    text1 = "Comment GUIDE below to get it"
    assert parse_comment_words(text1) == ["GUIDE"]

    text2 = "Type TEMPLATE to receive the link"
    assert parse_comment_words(text2) == ["TEMPLATE"]

    text3 = "DM me SCALE for the blueprint"
    assert parse_comment_words(text3) == ["SCALE"]


def test_parse_comment_words_multiple_and_dedupe() -> None:
    t1 = "Comment 'ALPHA' below"
    t2 = "Drop 'BETA' or comment 'ALPHA' in the chat"
    words = parse_comment_words(t1, t2)
    assert words == ["ALPHA", "BETA"]


def test_parse_comment_words_non_giveaways_and_stopwords() -> None:
    # General conversational sentences should not falsely trigger comment words
    assert parse_comment_words("Leave a comment below with your thoughts!") == []
    assert parse_comment_words("I had a great time walking in the park.") == []
    assert parse_comment_words("Click the link to learn more.") == []


# ==============================================================================
# 2. parse_giveaway Tests
# ==============================================================================


def test_parse_giveaway_comment_funnel() -> None:
    sources = [
        (
            "caption",
            "Want my 7-figure system? Comment 'BLUEPRINT' below and I will send you the free playbook!",
        ),
        ("ocr", "COMMENT 'BLUEPRINT' FOR FREE SOP"),
    ]
    res = parse_giveaway(sources)
    assert res["has_giveaway"] is True
    assert res["action"] == "comment"
    assert "BLUEPRINT" in res["comment_words"]
    assert res["confidence"] >= 0.8
    assert res["offer"] != ""


def test_parse_giveaway_link_in_bio() -> None:
    sources = [
        (
            "caption",
            "Grab the free Notion template at the link in bio before it's gone!",
        ),
    ]
    res = parse_giveaway(sources)
    assert res["has_giveaway"] is True
    assert res["action"] == "link_in_bio"
    assert res["comment_words"] == []
    assert res["confidence"] >= 0.7


def test_parse_giveaway_dm_action() -> None:
    sources = [
        (
            "transcript",
            "If you want this exact framework, send me a DM and I'll share it.",
        ),
    ]
    res = parse_giveaway(sources)
    assert res["has_giveaway"] is True
    assert res["action"] == "dm"


def test_parse_giveaway_with_vlm_cta() -> None:
    sources = [("caption", "Here is how to automate content.")]
    vlm_cta = {
        "action": "comment",
        "keyword": "GROWTH",
        "offer": "Free Growth Checklist",
    }
    res = parse_giveaway(sources, vlm_cta=vlm_cta)
    assert res["has_giveaway"] is True
    assert res["action"] == "comment"
    assert "GROWTH" in res["comment_words"]
    assert res["offer"] == "Free Growth Checklist"


def test_parse_giveaway_none() -> None:
    sources = [
        ("caption", "Morning coffee routine in Seattle."),
        ("transcript", "I like drinking espresso every morning."),
    ]
    res = parse_giveaway(sources)
    assert res["has_giveaway"] is False
    assert res["action"] == "none"
    assert res["confidence"] == 0.0


# ==============================================================================
# 3. analyze_video_study Tests
# ==============================================================================


def test_analyze_video_study_missing_file(tmp_path: Path) -> None:
    missing_video = tmp_path / "missing.mp4"
    vision = VisionClient(provider="fake")
    with pytest.raises(FileNotFoundError):
        analyze_video_study(
            missing_video,
            item={"url": "https://instagram.com/reel/abc123"},
            meta={},
            work_dir=tmp_path,
            vision=vision,
        )


def test_analyze_video_study_pipeline(tmp_path: Path) -> None:
    # Create a dummy video file
    dummy_video = tmp_path / "test_reel.mp4"
    dummy_video.write_bytes(b"dummy mp4 video bytes")

    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    vision = VisionClient(
        provider="fake",
        mock_response={
            "hook": {"text": "Stop Making This Mistake", "rating": 9.2},
            "summary": "Video deconstruction summary",
            "framework": "Problem-Agitate-Solve",
            "score": 8.9,
            "cta": {
                "action": "comment",
                "keyword": "SYSTEM",
                "offer": "AI System Guide",
            },
        },
    )

    # Patch underlying media and signal operations
    with (
        patch(
            "reel_watcher.study.probe",
            return_value={
                "duration": 15.0,
                "width": 1080,
                "height": 1920,
                "fps": 30.0,
                "has_audio": True,
            },
        ),
        patch(
            "reel_watcher.study.detect_cuts",
            return_value=[2.5, 6.0, 11.2],
        ),
        patch(
            "reel_watcher.study.pick_frame_times",
            return_value=[0.0, 1.0, 2.5, 6.0],
        ) as mock_pick,
        patch(
            "reel_watcher.study.extract_frame_jpg",
            side_effect=lambda v, t, d: Path(d).touch() or Path(d),
        ),
        patch(
            "reel_watcher.study.ocr_image",
            return_value="Comment 'SYSTEM' below",
        ),
        patch(
            "reel_watcher.study.dhash_bits",
            return_value=123456789,
        ),
        patch(
            "reel_watcher.study.dedupe_frames",
            return_value=([0, 1, 2], [3]),
        ),
        patch(
            "reel_watcher.study.make_contact_sheet",
            side_effect=lambda tiles, dest, **kw: Path(dest).touch()
            or Path(dest),
        ),
        patch(
            "reel_watcher.study.transcribe",
            return_value={
                "text": "Hey everyone, comment SYSTEM for the free AI guide.",
                "language": "en",
                "segments": [],
                "words": [{"w": "comment", "s": 0.5, "e": 0.8}],
                "backend": "mock",
            },
        ),
        patch(
            "reel_watcher.study.non_speech_energy_heuristic",
            return_value={
                "has_music_bed": True,
                "has_dead_silence": False,
                "speech_ratio": 0.75,
            },
        ),
    ):
        item = {
            "url": "https://www.instagram.com/reel/CXYZ1234/",
            "shortcode": "CXYZ1234",
            "collection": "marketing",
        }
        meta = {
            "title": "Scaling Reel",
            "author": "creator_name",
            "caption": "Comment 'SYSTEM' below for full access!",
        }

        # Run study analysis
        study = analyze_video_study(
            dummy_video,
            item=item,
            meta=meta,
            work_dir=work_dir,
            vision=vision,
            fast=False,
        )

        assert study["shortcode"] == "CXYZ1234"
        assert study["url"] == "https://www.instagram.com/reel/CXYZ1234/"
        assert study["title"] == "Scaling Reel"
        assert study["author"] == "creator_name"
        assert study["duration"] == 15.0
        assert study["hook_text"] == "Stop Making This Mistake"
        assert study["summary"] == "Video deconstruction summary"
        assert study["framework"] == "Problem-Agitate-Solve"
        assert study["score"] == 8.9

        # Verify giveaway parsed properly
        assert study["giveaway"]["has_giveaway"] is True
        assert "SYSTEM" in study["giveaway"]["comment_words"]

        # Verify contact sheet path present
        assert Path(study["contact_sheet"]).is_file()

        # Test fast mode flag propagation
        study_fast = analyze_video_study(
            dummy_video,
            item=item,
            meta=meta,
            work_dir=work_dir,
            vision=vision,
            fast=True,
        )
        assert mock_pick.call_args[1].get("fast") is True


# ==============================================================================
# 4. analyze_carousel_study Tests
# ==============================================================================


def test_analyze_carousel_study_empty_slides(tmp_path: Path) -> None:
    vision = VisionClient(provider="fake")
    with pytest.raises(ValueError, match="slides list cannot be empty"):
        analyze_carousel_study([], item={}, meta={}, work_dir=tmp_path, vision=vision)


def test_analyze_carousel_study_missing_slide(tmp_path: Path) -> None:
    vision = VisionClient(provider="fake")
    missing = tmp_path / "nonexistent_slide.jpg"
    with pytest.raises(FileNotFoundError):
        analyze_carousel_study(
            [missing], item={}, meta={}, work_dir=tmp_path, vision=vision
        )


def test_analyze_carousel_study_pipeline(
    tmp_path: Path, dummy_image_file: Path
) -> None:
    slides = [dummy_image_file]
    work_dir = tmp_path / "carousel_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    vision = VisionClient(
        provider="fake",
        mock_response={
            "hook": {"text": "Carousel Hook Headline", "rating": 8.8},
            "summary": "Carousel visual breakdown",
            "framework": "Step-by-Step Guide",
            "score": 8.5,
            "cta": {
                "action": "comment",
                "keyword": "DECK",
                "offer": "Free Pitch Deck",
            },
        },
    )

    with (
        patch("reel_watcher.study.ocr_image", return_value="Slide 1 Headline"),
        patch(
            "reel_watcher.study.make_contact_sheet",
            side_effect=lambda tiles, dest, **kw: Path(dest).touch()
            or Path(dest),
        ),
    ):
        item = {
            "url": "https://www.instagram.com/p/CAROUSEL123/",
            "shortcode": "CAROUSEL123",
            "collection": "education",
        }
        meta = {
            "title": "Design Carousel",
            "author": "designer_pro",
            "caption": "Drop 'DECK' in the comments for the PDF!",
        }

        study = analyze_carousel_study(
            slides,
            item=item,
            meta=meta,
            work_dir=work_dir,
            vision=vision,
        )

        assert study["media_type"] == "carousel"
        assert study["shortcode"] == "CAROUSEL123"
        assert study["slides_count"] == 1
        assert study["hook_text"] == "Carousel Hook Headline"
        assert study["framework"] == "Step-by-Step Guide"
        assert study["giveaway"]["has_giveaway"] is True
        assert "DECK" in study["giveaway"]["comment_words"]
        assert Path(study["contact_sheet"]).is_file()
