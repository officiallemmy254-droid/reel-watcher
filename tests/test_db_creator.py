"""Unit tests for Vault Creator schema extension and queries (`test_db_creator.py`)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from reel_watcher.db import Vault, extract_shortcode


def test_vault_creator_lifecycle(tmp_path: Path):
    """Verify creating, upserting, and retrieving a creator record."""
    db_path = tmp_path / "test_vault.db"
    vault = Vault(db_path=db_path, out_root=tmp_path)

    # 1. Upsert new creator
    creator_id = vault.upsert_creator(
        handle="dan_koe",
        platform="instagram",
        follower_count=1200000,
        median_views=45000,
        mean_likes=3200,
        profile_url="https://www.instagram.com/dan_koe/",
        metadata={"niche": "philosophy", "bio": "The modern renaissance man"},
    )
    assert creator_id > 0

    # 2. Retrieve creator
    creator = vault.get_creator("dan_koe", platform="instagram")
    assert creator is not None
    assert creator["id"] == creator_id
    assert creator["handle"] == "dan_koe"
    assert creator["follower_count"] == 1200000
    assert creator["median_views"] == 45000
    assert creator["metadata"]["niche"] == "philosophy"

    # 3. Update creator (upsert same handle)
    updated_id = vault.upsert_creator(
        handle="dan_koe",
        platform="instagram",
        follower_count=1250000,
        median_views=52000,
        mean_likes=3500,
        metadata={"niche": "philosophy", "updated": True},
    )
    assert updated_id == creator_id

    refreshed = vault.get_creator("dan_koe")
    assert refreshed["follower_count"] == 1250000
    assert refreshed["median_views"] == 52000
    assert refreshed["metadata"]["updated"] is True


def test_vault_enqueue_with_creator_and_metrics(tmp_path: Path):
    """Verify enqueuing a reel with creator_id, views, and outlier_multiplier."""
    db_path = tmp_path / "test_vault.db"
    vault = Vault(db_path=db_path, out_root=tmp_path)

    cid = vault.upsert_creator("hormozi", platform="instagram", median_views=100000)

    url = "https://www.instagram.com/reel/C_HORMOZI_OUTLIER/"
    enqueued = vault.enqueue_url(
        url=url,
        collection="creator:hormozi",
        creator_id=cid,
        views=350000,
        likes=25000,
        outlier_multiplier=3.5,
    )
    assert enqueued is True

    pending = vault.get_pending_urls(limit=10)
    assert len(pending) == 1
    item = pending[0]
    assert item["shortcode"] == "C_HORMOZI_OUTLIER"
    assert item["creator_id"] == cid
    assert item["views"] == 350000
    assert item["outlier_multiplier"] == 3.5


def test_vault_record_and_query_studies_by_creator(tmp_path: Path):
    """Verify recording a study linked to a creator and querying by creator_id."""
    db_path = tmp_path / "test_vault.db"
    vault = Vault(db_path=db_path, out_root=tmp_path)

    cid = vault.upsert_creator("mrbeast", platform="youtube_shorts", median_views=5000000)

    study_data = {
        "shortcode": "BEAST_HOOK_1",
        "url": "https://www.youtube.com/shorts/BEAST_HOOK_1",
        "collection": "creator:mrbeast",
        "title": "I Survived 7 Days In A Bunker",
        "author": "mrbeast",
        "hook_text": "I just locked myself in a bunker for 7 days",
        "summary": "Fast-paced challenge intro",
        "framework": "Urgent Challenge Hook",
        "score": 9.4,
        "creator_id": cid,
        "views": 15000000,
        "likes": 900000,
        "outlier_multiplier": 3.0,
    }

    vault.record_study(study_data)

    studies = vault.get_studies_by_creator(cid)
    assert len(studies) == 1
    s = studies[0]
    assert s["shortcode"] == "BEAST_HOOK_1"
    assert s["creator_id"] == cid
    assert s["views"] == 15000000
    assert s["outlier_multiplier"] == 3.0
