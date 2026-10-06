"""Tests for Vault State Storage & Persistence Engine (`db.py`)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from reel_watcher.db import Vault, extract_shortcode


def test_extract_shortcode_various_urls() -> None:
    """Verify shortcode extraction across supported short-form platforms and formats."""
    # Instagram URLs
    assert extract_shortcode("https://www.instagram.com/reel/C8xyz12345/") == "C8xyz12345"
    assert extract_shortcode("https://instagram.com/reels/D9abc67890?utm_source=ig_web") == "D9abc67890"
    assert extract_shortcode("https://www.instagram.com/p/E0def11122/") == "E0def11122"
    assert extract_shortcode("https://www.instagram.com/share/reel/F1ghi33344/") == "F1ghi33344"

    # YouTube Shorts
    assert extract_shortcode("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_shortcode("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    # TikTok URLs
    assert extract_shortcode("https://www.tiktok.com/@creator/video/7123456789012345678") == "7123456789012345678"
    assert extract_shortcode("https://vm.tiktok.com/ZM8abc123/") == "ZM8abc123"

    # Raw shortcode fallback
    assert extract_shortcode("C8xyz12345") == "C8xyz12345"


def test_vault_init_and_db_creation(tmp_path: Path) -> None:
    """Verify Vault creates sqlite database and table schema properly."""
    db_path = tmp_path / "sub" / "reels.db"
    out_root = tmp_path / "out"

    vault = Vault(db_path=db_path, out_root=out_root)
    vault.init_db()

    assert db_path.is_file()
    assert (out_root / "study").is_dir()


def test_enqueue_url_and_deduplication(tmp_path: Path) -> None:
    """Verify enqueueing URLs and deduplication by shortcode."""
    vault = Vault(db_path=tmp_path / "test.db", out_root=tmp_path / "out")
    vault.init_db()

    url_1 = "https://www.instagram.com/reel/C8xyz12345/?utm_source=ig_web"
    url_1_alt = "https://www.instagram.com/p/C8xyz12345/"
    url_2 = "https://www.instagram.com/reel/D9abc67890/"

    # First enqueue succeeds
    assert vault.enqueue_url(url_1, collection="finance") is True

    # Same URL returns False (deduplication)
    assert vault.enqueue_url(url_1, collection="finance") is False

    # Alternate URL with same shortcode returns False
    assert vault.enqueue_url(url_1_alt, collection="marketing") is False

    # Different reel succeeds
    assert vault.enqueue_url(url_2, collection="marketing") is True


def test_get_pending_urls(tmp_path: Path) -> None:
    """Verify retrieval of pending queue items with limit."""
    vault = Vault(db_path=tmp_path / "test.db", out_root=tmp_path / "out")
    vault.init_db()

    vault.enqueue_url("https://www.instagram.com/reel/AAA111/", collection="batch1")
    vault.enqueue_url("https://www.instagram.com/reel/BBB222/", collection="batch1")
    vault.enqueue_url("https://www.instagram.com/reel/CCC333/", collection="batch2")

    # Limit to 2
    pending_two = vault.get_pending_urls(limit=2)
    assert len(pending_two) == 2
    assert pending_two[0]["shortcode"] == "AAA111"
    assert pending_two[0]["collection"] == "batch1"
    assert pending_two[0]["status"] == "pending"
    assert pending_two[1]["shortcode"] == "BBB222"

    # Retrieve all
    all_pending = vault.get_pending_urls(limit=50)
    assert len(all_pending) == 3


def test_save_study_and_filesystem_sync(tmp_path: Path) -> None:
    """Verify save_study writes DB record, individual JSON, and appends to study_index.jsonl."""
    out_root = tmp_path / "out"
    vault = Vault(db_path=tmp_path / "test.db", out_root=out_root)
    vault.init_db()

    # Enqueue first to test queue status transition
    url = "https://www.instagram.com/reel/C8study001/"
    vault.enqueue_url(url, collection="hooks")
    assert len(vault.get_pending_urls()) == 1

    study_data = {
        "code": "C8study001",
        "url": url,
        "title": "3 Psychology Hacks for Viral Hooks",
        "author": "growth_expert",
        "hook_text": "Nobody tells you this about retention rate...",
        "summary": "Explains visual pattern interruption within 1.5 seconds.",
        "framework": "PAS",
        "score": 9.4,
        "scenes": [
            {"t_start": 0.0, "t_end": 1.5, "action": "Hand snap transition"},
            {"t_start": 1.5, "t_end": 4.0, "action": "Key visual demonstration"},
        ],
    }

    vault.save_study(study_data)

    # 1. Verify queue status updated to completed
    pending = vault.get_pending_urls()
    assert len(pending) == 0

    # 2. Verify individual JSON file exists and is valid
    json_path = out_root / "study" / "C8study001.json"
    assert json_path.is_file()
    with open(json_path, "r", encoding="utf-8") as f:
        loaded_json = json.load(f)
    assert loaded_json["title"] == "3 Psychology Hacks for Viral Hooks"
    assert loaded_json["score"] == 9.4
    assert len(loaded_json["scenes"]) == 2

    # 3. Verify study_index.jsonl appended
    index_path = out_root / "study_index.jsonl"
    assert index_path.is_file()
    lines = index_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    index_record = json.loads(lines[0])
    assert index_record["code"] == "C8study001"
    assert index_record["title"] == "3 Psychology Hacks for Viral Hooks"

    # 4. Verify get_study returns the saved record
    study_from_db = vault.get_study("C8study001")
    assert study_from_db is not None
    assert study_from_db["code"] == "C8study001"
    assert study_from_db["author"] == "growth_expert"
    assert study_from_db["scenes"][0]["action"] == "Hand snap transition"


def test_save_study_upsert_behavior(tmp_path: Path) -> None:
    """Verify save_study updates existing records when called repeatedly."""
    out_root = tmp_path / "out"
    vault = Vault(db_path=tmp_path / "test.db", out_root=out_root)
    vault.init_db()

    data_v1 = {
        "code": "C8upsert99",
        "title": "Version 1 Title",
        "score": 7.0,
    }
    vault.save_study(data_v1)

    data_v2 = {
        "code": "C8upsert99",
        "title": "Version 2 Updated Title",
        "score": 9.5,
    }
    vault.save_study(data_v2)

    study = vault.get_study("C8upsert99")
    assert study is not None
    assert study["title"] == "Version 2 Updated Title"
    assert study["score"] == 9.5


def test_get_study_nonexistent(tmp_path: Path) -> None:
    """Verify get_study returns None when code is not found."""
    vault = Vault(db_path=tmp_path / "test.db", out_root=tmp_path / "out")
    vault.init_db()
    assert vault.get_study("nonexistent_code") is None


def test_list_studies_and_search_query(tmp_path: Path) -> None:
    """Verify listing studies with and without search query filtering."""
    vault = Vault(db_path=tmp_path / "test.db", out_root=tmp_path / "out")
    vault.init_db()

    studies = [
        {
            "code": "CODE_A",
            "title": "Alex Hormozi Grand Slam Offer Breakdown",
            "author": "alex_fan",
            "hook_text": "How to make offers so good people feel stupid saying no",
            "framework": "Value Equation",
            "score": 9.8,
        },
        {
            "code": "CODE_B",
            "title": "StoryBrand 5 Second Grunt Test",
            "author": "miller_student",
            "hook_text": "If you confuse you lose in the first 3 seconds",
            "framework": "SB7",
            "score": 8.9,
        },
        {
            "code": "CODE_C",
            "title": "Direct Response E-commerce Ad Structure",
            "author": "ad_master",
            "hook_text": "Stop scrolling if your ROAS dropped this week",
            "framework": "AIDA",
            "score": 8.5,
        },
    ]

    for item in studies:
        vault.save_study(item)

    # List all
    all_studies = vault.list_studies()
    assert len(all_studies) == 3

    # Respect limit
    limited = vault.list_studies(limit=2)
    assert len(limited) == 2

    # Search query matching title
    hormozi_results = vault.list_studies(query="Hormozi")
    assert len(hormozi_results) == 1
    assert hormozi_results[0]["code"] == "CODE_A"

    # Search query matching framework
    sb7_results = vault.list_studies(query="SB7")
    assert len(sb7_results) == 1
    assert sb7_results[0]["code"] == "CODE_B"

    # Search query matching hook text
    roas_results = vault.list_studies(query="ROAS")
    assert len(roas_results) == 1
    assert roas_results[0]["code"] == "CODE_C"

    # Search query matching nothing
    empty_results = vault.list_studies(query="NonExistentTerm123")
    assert len(empty_results) == 0
