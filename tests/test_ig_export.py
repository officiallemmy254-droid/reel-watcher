"""Tests for Instagram Export Parser (`ig_export.py`)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import pytest

from reel_watcher.ig_export import (
    export_to_tsv,
    extract_urls_from_export,
)


def test_extract_urls_from_saved_posts_json(tmp_path: Path) -> None:
    """Test standard Instagram saved_posts.json export format."""
    data = {
        "saved_saved_media": [
            {
                "title": "natgeo",
                "string_map_data": {
                    "Saved on": {
                        "href": "https://www.instagram.com/reel/C123abc456/",
                        "timestamp": 1705000000,
                    }
                },
            },
            {
                "title": "techinsider",
                "string_map_data": {
                    "Saved on": {
                        "href": "https://www.instagram.com/p/C789xyz123/?utm_source=ig_web_copy_link",
                        "timestamp": 1705100000,
                    }
                },
            },
        ]
    }
    export_file = tmp_path / "saved_posts.json"
    export_file.write_text(json.dumps(data), encoding="utf-8")

    results = extract_urls_from_export(export_file)

    assert len(results) == 2
    assert results[0]["shortcode"] == "C123abc456"
    assert results[0]["id"] == "ig_C123abc456"
    assert results[0]["url"] == "https://www.instagram.com/reel/C123abc456/"
    assert results[0]["creator"] == "natgeo"
    assert results[0]["timestamp"] == 1705000000

    assert results[1]["shortcode"] == "C789xyz123"
    assert results[1]["creator"] == "techinsider"


def test_extract_urls_from_saved_collections_json_all_and_filtered(tmp_path: Path) -> None:
    """Test saved_collections.json format with both unfiltered and filtered extraction."""
    data = {
        "saved_collections": [
            {
                "title": "Viral Hooks",
                "media": [
                    {
                        "title": "growth_hacker",
                        "string_map_data": {
                            "Saved on": {
                                "href": "https://www.instagram.com/reel/HookPost01/",
                                "timestamp": 1706000000,
                            }
                        },
                    },
                    {
                        "title": "hook_master",
                        "string_map_data": {
                            "Saved on": {
                                "href": "https://www.instagram.com/reel/HookPost02/",
                                "timestamp": 1706010000,
                            }
                        },
                    },
                ],
            },
            {
                "title": "Design Inspo",
                "media": [
                    {
                        "title": "minimal_designer",
                        "string_map_data": {
                            "Saved on": {
                                "href": "https://www.instagram.com/reel/DesignPost01/",
                                "timestamp": 1707000000,
                            }
                        },
                    }
                ],
            },
        ]
    }
    export_file = tmp_path / "saved_collections.json"
    export_file.write_text(json.dumps(data), encoding="utf-8")

    # Unfiltered - extracts all 3
    all_results = extract_urls_from_export(export_file)
    assert len(all_results) == 3
    collections = {r["collection"] for r in all_results}
    assert collections == {"Viral Hooks", "Design Inspo"}

    # Filtered by "Viral Hooks"
    filtered = extract_urls_from_export(export_file, collection="Viral Hooks")
    assert len(filtered) == 2
    assert all(r["collection"] == "Viral Hooks" for r in filtered)
    assert {r["shortcode"] for r in filtered} == {"HookPost01", "HookPost02"}

    # Filtered by case-insensitive partial/exact match
    filtered_ci = extract_urls_from_export(export_file, collection="viral hooks")
    assert len(filtered_ci) == 2


def test_extract_urls_from_flat_json_formats(tmp_path: Path) -> None:
    """Test variant flat JSON list format."""
    flat_data = [
        {
            "title": "creator_a",
            "string_map_data": {
                "Saved on": {
                    "href": "https://www.instagram.com/reel/FlatReel1/",
                    "timestamp": 1700000001,
                }
            },
        },
        {
            "url": "https://www.instagram.com/reel/FlatReel2/",
            "author": "creator_b",
        },
    ]
    export_file = tmp_path / "flat_posts.json"
    export_file.write_text(json.dumps(flat_data), encoding="utf-8")

    results = extract_urls_from_export(export_file)
    assert len(results) == 2
    assert {r["shortcode"] for r in results} == {"FlatReel1", "FlatReel2"}


def test_extract_urls_from_html_export(tmp_path: Path) -> None:
    """Test parsing Instagram HTML export files."""
    html_content = """<!DOCTYPE html>
<html>
<head><title>Saved Posts</title></head>
<body>
  <div class="content">
    <div>
      <div>creator_one</div>
      <a href="https://www.instagram.com/reel/HtmlReel01/?utm_source=ig">Saved on Jan 10, 2024</a>
    </div>
    <div>
      <div>creator_two</div>
      <a href="https://www.instagram.com/p/HtmlPost02/">Saved on Jan 11, 2024</a>
    </div>
  </div>
</body>
</html>
"""
    export_file = tmp_path / "saved_posts.html"
    export_file.write_text(html_content, encoding="utf-8")

    results = extract_urls_from_export(export_file)
    assert len(results) == 2
    assert {r["shortcode"] for r in results} == {"HtmlReel01", "HtmlPost02"}
    assert any(r["creator"] == "creator_one" for r in results)


def test_extract_urls_from_html_with_collection_headers(tmp_path: Path) -> None:
    """Test parsing HTML export with collection headers."""
    html_content = """<!DOCTYPE html>
<html>
<body>
  <h2>Growth Strategies</h2>
  <div>
    <div>strategist_1</div>
    <a href="https://www.instagram.com/reel/StrategyReel1/">Post 1</a>
  </div>
  <h2>Lifestyle</h2>
  <div>
    <div>lifestyle_1</div>
    <a href="https://www.instagram.com/reel/LifestyleReel2/">Post 2</a>
  </div>
</body>
</html>
"""
    export_file = tmp_path / "saved_collections.html"
    export_file.write_text(html_content, encoding="utf-8")

    filtered = extract_urls_from_export(export_file, collection="Growth Strategies")
    assert len(filtered) == 1
    assert filtered[0]["shortcode"] == "StrategyReel1"
    assert filtered[0]["collection"] == "Growth Strategies"


def test_extract_urls_from_directory_walk(tmp_path: Path) -> None:
    """Test passing a directory recursively extracts from all JSON and HTML files."""
    sub_dir = tmp_path / "activity" / "saved"
    sub_dir.mkdir(parents=True)

    f1 = sub_dir / "file1.json"
    f1.write_text(
        json.dumps({
            "saved_saved_media": [
                {
                    "title": "user1",
                    "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/DirReel1/"}},
                }
            ]
        }),
        encoding="utf-8",
    )

    f2 = sub_dir / "file2.html"
    f2.write_text(
        '<a href="https://www.instagram.com/reel/DirReel2/">link</a>',
        encoding="utf-8",
    )

    results = extract_urls_from_export(tmp_path)
    assert len(results) == 2
    assert {r["shortcode"] for r in results} == {"DirReel1", "DirReel2"}


def test_extract_urls_deduplication(tmp_path: Path) -> None:
    """Test that duplicate URLs/shortcodes are deduplicated."""
    data = {
        "saved_saved_media": [
            {
                "title": "same_user",
                "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/DupReel/"}},
            },
            {
                "title": "same_user",
                "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/DupReel/?igsh=123"}},
            },
        ]
    }
    export_file = tmp_path / "duplicates.json"
    export_file.write_text(json.dumps(data), encoding="utf-8")

    results = extract_urls_from_export(export_file)
    assert len(results) == 1
    assert results[0]["shortcode"] == "DupReel"


def test_extract_urls_empty_or_corrupt_files(tmp_path: Path) -> None:
    """Test handling of empty or corrupted files without throwing unhandled exceptions."""
    empty_file = tmp_path / "empty.json"
    empty_file.write_text("", encoding="utf-8")

    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text("NOT_JSON{[[", encoding="utf-8")

    assert extract_urls_from_export(empty_file) == []
    assert extract_urls_from_export(corrupt_file) == []
    assert extract_urls_from_export(tmp_path / "nonexistent.json") == []


def test_export_to_tsv_success(tmp_path: Path) -> None:
    """Test export_to_tsv writes valid TSV with headers and correct counts."""
    data = {
        "saved_saved_media": [
            {
                "title": "creator_alpha",
                "string_map_data": {
                    "Saved on": {
                        "href": "https://www.instagram.com/reel/TSVReel01/",
                        "timestamp": 1709000000,
                    }
                },
            },
            {
                "title": "creator_beta",
                "string_map_data": {
                    "Saved on": {
                        "href": "https://www.instagram.com/reel/TSVReel02/",
                        "timestamp": 1709000001,
                    }
                },
            },
        ]
    }
    input_file = tmp_path / "saved_posts.json"
    input_file.write_text(json.dumps(data), encoding="utf-8")

    out_tsv = tmp_path / "output" / "saved_posts.tsv"

    count = export_to_tsv([input_file], out_tsv)

    assert count == 2
    assert out_tsv.exists()

    with out_tsv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)

    assert len(rows) == 2
    assert rows[0]["shortcode"] == "TSVReel01"
    assert rows[0]["creator"] == "creator_alpha"
    assert rows[0]["url"] == "https://www.instagram.com/reel/TSVReel01/"
    assert rows[1]["shortcode"] == "TSVReel02"
    assert rows[1]["creator"] == "creator_beta"


def test_export_to_tsv_collection_filter_and_multiple_files(tmp_path: Path) -> None:
    """Test export_to_tsv with multiple files and collection filtering."""
    file1 = tmp_path / "f1.json"
    file1.write_text(
        json.dumps({
            "saved_collections": [
                {
                    "title": "Target Collection",
                    "media": [
                        {
                            "title": "u1",
                            "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/Rec1/"}},
                        }
                    ],
                },
                {
                    "title": "Other Collection",
                    "media": [
                        {
                            "title": "u2",
                            "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/Rec2/"}},
                        }
                    ],
                },
            ]
        }),
        encoding="utf-8",
    )

    out_tsv = tmp_path / "filtered.tsv"
    count = export_to_tsv([file1], out_tsv, collection="Target Collection")

    assert count == 1
    with out_tsv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["shortcode"] == "Rec1"
