"""Unit tests for Creator Harvester & Outlier Scoring (`test_creator.py`)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from reel_watcher.creator import (
    CreatorPost,
    CreatorStats,
    calculate_creator_baselines,
    filter_outliers,
    extract_creator_posts_from_graphql_payload,
)


def test_calculate_creator_baselines():
    """Verify median calculation, mean calculations, and outlier multipliers."""
    posts = [
        CreatorPost(shortcode="P1", url="https://instagram.com/reel/P1/", views=10000, likes=500),
        CreatorPost(shortcode="P2", url="https://instagram.com/reel/P2/", views=12000, likes=600),
        CreatorPost(shortcode="P3", url="https://instagram.com/reel/P3/", views=10000, likes=550),
        CreatorPost(shortcode="P4", url="https://instagram.com/reel/P4/", views=15000, likes=700),
        CreatorPost(shortcode="P5", url="https://instagram.com/reel/P5/", views=80000, likes=4000),  # Outlier!
    ]

    stats = calculate_creator_baselines(posts, handle="alex_hormozi", platform="instagram", outlier_threshold=2.0)

    assert stats.handle == "alex_hormozi"
    assert stats.total_posts == 5
    # Median of [10000, 10000, 12000, 15000, 80000] is 12000
    assert stats.median_views == 12000
    assert stats.mean_likes == (500 + 600 + 550 + 700 + 4000) // 5

    # Check outlier post
    outlier_post = next(p for p in posts if p.shortcode == "P5")
    assert round(outlier_post.outlier_multiplier, 2) == round(80000 / 12000, 2)
    assert outlier_post.is_outlier is True

    # Check non-outlier post
    normal_post = next(p for p in posts if p.shortcode == "P1")
    assert round(normal_post.outlier_multiplier, 2) == round(10000 / 12000, 2)
    assert normal_post.is_outlier is False


def test_filter_outliers():
    """Verify filtering posts above outlier threshold sorted by views."""
    posts = [
        CreatorPost(shortcode="P1", url="url1", views=10000, outlier_multiplier=1.0),
        CreatorPost(shortcode="P2", url="url2", views=35000, outlier_multiplier=3.5, is_outlier=True),
        CreatorPost(shortcode="P3", url="url3", views=22000, outlier_multiplier=2.2, is_outlier=True),
        CreatorPost(shortcode="P4", url="url4", views=12000, outlier_multiplier=1.2),
        CreatorPost(shortcode="P5", url="url5", views=50000, outlier_multiplier=5.0, is_outlier=True),
    ]

    outliers = filter_outliers(posts, min_multiplier=2.0, top_n=2)
    assert len(outliers) == 2
    # Should be sorted highest outlier first
    assert outliers[0].shortcode == "P5"
    assert outliers[1].shortcode == "P2"


def test_extract_creator_posts_from_graphql():
    """Verify extracting posts from Instagram GraphQL payload structure."""
    fake_graphql = {
        "data": {
            "user": {
                "edge_owner_to_timeline_media": {
                    "edges": [
                        {
                            "node": {
                                "id": "12345",
                                "shortcode": "CODE_VIRAL_1",
                                "display_url": "https://cdn.example.com/img1.jpg",
                                "is_video": True,
                                "video_view_count": 95000,
                                "video_play_count": 120000,
                                "edge_media_to_caption": {
                                    "edges": [{"node": {"text": "How to double your MRR in 30 days"}}]
                                },
                                "edge_liked_by": {"count": 4800},
                                "edge_media_to_comment": {"count": 320},
                                "taken_at_timestamp": 1720000000,
                            }
                        },
                        {
                            "node": {
                                "id": "12346",
                                "shortcode": "CODE_NORMAL_2",
                                "display_url": "https://cdn.example.com/img2.jpg",
                                "is_video": True,
                                "video_view_count": 8500,
                                "edge_media_to_caption": {
                                    "edges": [{"node": {"text": "Casual Monday coffee"}}]
                                },
                                "edge_liked_by": {"count": 450},
                                "edge_media_to_comment": {"count": 25},
                                "taken_at_timestamp": 1720100000,
                            }
                        }
                    ]
                }
            }
        }
    }

    posts = extract_creator_posts_from_graphql_payload(fake_graphql)
    assert len(posts) == 2
    assert posts[0].shortcode == "CODE_VIRAL_1"
    assert posts[0].views == 120000  # Prefers play count
    assert posts[0].likes == 4800
    assert posts[0].comments == 320
    assert "double your MRR" in posts[0].caption

    assert posts[1].shortcode == "CODE_NORMAL_2"
    assert posts[1].views == 8500
