"""Unit tests for Creator Dossier Synthesis Engine (`test_dossier.py`)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from reel_watcher.db import Vault
from reel_watcher.dossier import (
    render_dossier_markdown,
    synthesize_creator_dossier,
)


def test_synthesize_creator_dossier(tmp_path: Path):
    """Verify aggregation of studied reels into structured creator intelligence dossier."""
    db_path = tmp_path / "test_vault.db"
    vault = Vault(db_path=db_path, out_root=tmp_path)

    cid = vault.upsert_creator("dan_koe", platform="instagram", follower_count=1200000, median_views=50000)

    # Record 2 studied reels for dan_koe
    vault.record_study({
        "shortcode": "KOE_REEL_1",
        "url": "https://instagram.com/reel/KOE_REEL_1/",
        "title": "How to escape the 9-5",
        "author": "dan_koe",
        "hook_text": "You are working 40 hours a week for someone else's dream.",
        "summary": "Solopreneurship mindset pivot",
        "framework": "Contrarian Reality Check",
        "score": 9.2,
        "creator_id": cid,
        "views": 180000,
        "outlier_multiplier": 3.6,
        "duration": 45.0,
        "cuts_count": 12,
        "giveaway": {
            "has_giveaway": True,
            "action": "comment",
            "comment_words": ["FREEDOM"],
            "offer": "1-Person Business Blueprint",
            "details": "Comment 'FREEDOM' to receive the blueprint.",
        },
    })

    vault.record_study({
        "shortcode": "KOE_REEL_2",
        "url": "https://instagram.com/reel/KOE_REEL_2/",
        "title": "Focus is the new superpower",
        "author": "dan_koe",
        "hook_text": "If you cannot focus for 60 minutes, you are broke.",
        "summary": "Dopamine detox framework",
        "framework": "Urgent Problem Warning",
        "score": 8.8,
        "creator_id": cid,
        "views": 65000,
        "outlier_multiplier": 1.3,
        "duration": 30.0,
        "cuts_count": 8,
        "giveaway": {
            "has_giveaway": False,
            "action": "none",
            "comment_words": [],
            "offer": "",
            "details": "No lead magnet detected.",
        },
    })

    dossier = synthesize_creator_dossier(handle="dan_koe", vault=vault)

    assert dossier["handle"] == "dan_koe"
    assert dossier["total_studies"] == 2
    assert len(dossier["top_hooks"]) == 2
    assert "FREEDOM" in dossier["funnel"]["comment_triggers"]
    assert "1-Person Business Blueprint" in dossier["funnel"]["offers"]
    assert round(dossier["pacing"]["avg_duration"], 1) == 37.5

    md = render_dossier_markdown(dossier)
    assert "# Creator Intelligence Dossier: @dan_koe" in md
    assert "FREEDOM" in md
    assert "Contrarian Reality Check" in md
