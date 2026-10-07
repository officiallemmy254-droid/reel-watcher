"""Unit tests for Creator & Saved Sync CLI subcommands (`test_cli_creator.py`)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from reel_watcher.cli import main
from reel_watcher.creator import CreatorPost, CreatorStats


def test_cli_creator_scan(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Verify creator scan subcommand prints baselines and outliers."""
    db_path = tmp_path / "reels.db"
    out_root = tmp_path / "vault"

    mock_posts = [
        CreatorPost(shortcode="REEL_1", url="https://instagram.com/reel/REEL_1/", views=10000, likes=500),
        CreatorPost(shortcode="REEL_2", url="https://instagram.com/reel/REEL_2/", views=45000, likes=2500, is_outlier=True, outlier_multiplier=4.5),
    ]
    mock_stats = CreatorStats(
        handle="dan_koe",
        platform="instagram",
        total_posts=2,
        median_views=10000,
        mean_views=27500,
        mean_likes=1500,
        top_outliers=[mock_posts[1]],
    )

    with patch("reel_watcher.cli.harvest_creator", return_value=(mock_posts, mock_stats)):
        exit_code = main([
            "creator", "scan", "dan_koe",
            "--db", str(db_path),
            "--out-root", str(out_root),
        ])

    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "[+]" in captured
    assert "dan_koe" in captured
    assert "REEL_2" in captured


def test_cli_creator_dossier(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Verify creator dossier generation subcommand writes report to disk."""
    db_path = tmp_path / "reels.db"
    out_root = tmp_path / "vault"

    with patch("reel_watcher.cli.export_dossier", return_value=out_root / "creators" / "dan_koe" / "dossier.md") as mock_exp:
        exit_code = main([
            "creator", "dossier", "dan_koe",
            "--db", str(db_path),
            "--out-root", str(out_root),
        ])

    assert exit_code == 0
    mock_exp.assert_called_once()
    captured = capsys.readouterr().out
    assert "[+]" in captured
    assert "dossier.md" in captured


def test_cli_sync_saved(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Verify sync-saved subcommand execution."""
    db_path = tmp_path / "reels.db"
    out_root = tmp_path / "vault"

    with patch(
        "reel_watcher.cli.sync_saved_collection",
        return_value={"harvested": 5, "downloaded": 4, "studied": 0, "unavailable": 1},
    ) as mock_sync:
        exit_code = main([
            "sync-saved",
            "--collection", "Hooks",
            "--db", str(db_path),
            "--out-root", str(out_root),
        ])

    assert exit_code == 0
    mock_sync.assert_called_once()
    captured = capsys.readouterr().out
    assert "[+]" in captured
    assert "Sync complete" in captured


def test_cli_ingest_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Verify ingest-folder subcommand execution."""
    db_path = tmp_path / "reels.db"
    out_root = tmp_path / "vault"
    vids_dir = tmp_path / "vids"
    vids_dir.mkdir()

    with patch(
        "reel_watcher.cli.ingest_local_folder",
        return_value=[{"code": "local_test", "collection": "local"}],
    ) as mock_ingest:
        exit_code = main([
            "ingest-folder", str(vids_dir),
            "--collection", "local",
            "--db", str(db_path),
            "--out-root", str(out_root),
        ])

    assert exit_code == 0
    mock_ingest.assert_called_once()
    captured = capsys.readouterr().out
    assert "[+]" in captured
    assert "Ingested 1 local video" in captured
