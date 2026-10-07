"""Unit tests for Saved Collections Sync and Local Folder Ingestion Engine (`test_saved_processor.py`)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from reel_watcher.db import Vault
from reel_watcher.saved_processor import (
    ingest_local_folder,
    sync_saved_collection,
)


def test_ingest_local_folder(tmp_path: Path):
    """Verify discovering local video files and enqueuing them into the Vault."""
    db_path = tmp_path / "test_vault.db"
    vault = Vault(db_path=db_path, out_root=tmp_path)

    videos_dir = tmp_path / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy video files
    (videos_dir / "clip_01.mp4").write_bytes(b"dummy mp4 content 1")
    (videos_dir / "clip_02.mov").write_bytes(b"dummy mov content 2")
    (videos_dir / "notes.txt").write_text("not a video")

    results = ingest_local_folder(
        folder_path=videos_dir,
        collection="swipe_file",
        recursive=False,
        vault=vault,
        auto_study=False,
    )

    assert len(results) == 2
    codes = {r["code"] for r in results}
    assert "local_clip_01" in codes
    assert "local_clip_02" in codes

    pending = vault.get_pending_urls(limit=10)
    assert len(pending) == 2
    assert all(item["collection"] == "swipe_file" for item in pending)


def test_sync_saved_collection_dead_reel_resilience(tmp_path: Path):
    """Verify syncing saved reels handles unavailable/dead reels without halting."""
    db_path = tmp_path / "test_vault.db"
    vault = Vault(db_path=db_path, out_root=tmp_path)

    # Enqueue a live reel and a dead reel
    vault.enqueue_url("https://instagram.com/reel/LIVE_REEL_1/", collection="hooks")
    vault.enqueue_url("https://instagram.com/reel/DEAD_REEL_2/", collection="hooks")

    def mock_download(url, **kwargs):
        if "DEAD_REEL_2" in url:
            raise RuntimeError("Video unavailable or removed by user")
        dest = tmp_path / "LIVE_REEL_1.mp4"
        dest.write_bytes(b"video data")
        return dest

    with patch("reel_watcher.saved_processor.harvest_saved_reels_via_cdp", return_value=[]), \
         patch("reel_watcher.saved_processor.download_media", side_effect=mock_download):
        summary = sync_saved_collection(
            collection="hooks",
            vault=vault,
            auto_download=True,
            auto_study=False,
        )

    assert summary["downloaded"] == 1
    assert summary["unavailable"] == 1

    item_dead = vault.get_queue_item("DEAD_REEL_2")
    assert item_dead["status"] == "unavailable"

    item_live = vault.get_queue_item("LIVE_REEL_1")
    assert item_live["status"] == "downloaded"
