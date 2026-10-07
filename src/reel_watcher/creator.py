"""Creator Profile Harvester, Baseline Metrics & Outlier Scoring (`creator.py`).

Provides:
- CreatorPost and CreatorStats data abstractions
- Median view count, average engagement, and outlier multiplier computation
- Instagram GraphQL feed response payload parsing
- Dual-engine creator scraping (Chrome CDP live session & yt-dlp flat-playlist fallback)
- Outlier filtering for cost-efficient, high-leverage reel intelligence
Strict ASCII console output formatting across Windows environments.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time
from typing import Any

from reel_watcher.browser_sync import CDPSession, extract_reel_codes_from_html, get_active_instagram_tabs
from reel_watcher.config import format_status
from reel_watcher.db import Vault, extract_shortcode


@dataclass
class CreatorPost:
    """Represents a harvested post or reel from a creator's profile grid."""

    shortcode: str
    url: str
    title: str = ""
    caption: str = ""
    views: int = 0
    likes: int = 0
    comments: int = 0
    duration: float = 0.0
    posted_at: str = ""
    outlier_multiplier: float = 1.0
    is_outlier: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert post to dictionary representation."""
        return asdict(self)


@dataclass
class CreatorStats:
    """Summary metrics and baseline engagement for a specific creator profile."""

    handle: str
    platform: str = "instagram"
    total_posts: int = 0
    median_views: int = 0
    mean_views: int = 0
    mean_likes: int = 0
    mean_comments: int = 0
    outlier_threshold: float = 1.5
    top_outliers: list[CreatorPost] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to dictionary representation."""
        d = asdict(self)
        d["top_outliers"] = [p.to_dict() for p in self.top_outliers]
        return d


def calculate_creator_baselines(
    posts: list[CreatorPost],
    handle: str = "",
    platform: str = "instagram",
    outlier_threshold: float = 1.5,
) -> CreatorStats:
    """Calculate median views, mean engagement, and outlier scores across creator posts.

    Parameters
    ----------
    posts : list[CreatorPost]
        List of harvested creator posts.
    handle : str
        Creator handle or username.
    platform : str
        Platform name (default: 'instagram').
    outlier_threshold : float
        Multiplier above median views required to flag an outlier (default: 1.5).

    Returns
    -------
    CreatorStats
        Calculated baseline statistics with posts tagged in-place.
    """
    if not posts:
        return CreatorStats(
            handle=handle,
            platform=platform,
            total_posts=0,
            median_views=0,
            mean_views=0,
            mean_likes=0,
            mean_comments=0,
            outlier_threshold=outlier_threshold,
            top_outliers=[],
        )

    view_counts = [p.views for p in posts if p.views > 0]
    if not view_counts:
        # Fallback if view counts not available: use likes
        view_counts = [p.likes for p in posts] or [1]

    median_views = int(statistics.median(view_counts)) if view_counts else 1
    # Guard against 0 median
    effective_median = max(1, median_views)

    total_views = sum(p.views for p in posts)
    total_likes = sum(p.likes for p in posts)
    total_comments = sum(p.comments for p in posts)
    count = len(posts)

    mean_views = total_views // count
    mean_likes = total_likes // count
    mean_comments = total_comments // count

    # Tag each post with its outlier multiplier
    for post in posts:
        metric = post.views if post.views > 0 else post.likes
        multiplier = round(metric / effective_median, 2)
        post.outlier_multiplier = multiplier
        post.is_outlier = multiplier >= outlier_threshold

    # Find top outliers sorted by multiplier descending
    outliers = [p for p in posts if p.is_outlier]
    outliers.sort(key=lambda p: (p.outlier_multiplier, p.views), reverse=True)

    return CreatorStats(
        handle=handle,
        platform=platform,
        total_posts=count,
        median_views=median_views,
        mean_views=mean_views,
        mean_likes=mean_likes,
        mean_comments=mean_comments,
        outlier_threshold=outlier_threshold,
        top_outliers=outliers,
    )


def filter_outliers(
    posts: list[CreatorPost],
    stats: CreatorStats | None = None,
    min_multiplier: float = 1.5,
    top_n: int = 10,
) -> list[CreatorPost]:
    """Filter and sort posts meeting or exceeding outlier threshold.

    Parameters
    ----------
    posts : list[CreatorPost]
        List of creator posts.
    stats : CreatorStats | None
        Optional precalculated creator stats.
    min_multiplier : float
        Minimum multiplier over median views (default: 1.5).
    top_n : int
        Maximum number of outliers to return (default: 10).

    Returns
    -------
    list[CreatorPost]
        Filtered outliers sorted highest-signal first.
    """
    candidates = [p for p in posts if p.outlier_multiplier >= min_multiplier]
    candidates.sort(key=lambda p: (p.outlier_multiplier, p.views), reverse=True)
    return candidates[:top_n]


def extract_creator_posts_from_graphql_payload(payload: dict[str, Any]) -> list[CreatorPost]:
    """Parse Instagram GraphQL or REST user feed JSON payload into CreatorPost records."""
    posts: list[CreatorPost] = []
    if not isinstance(payload, dict):
        return posts

    # Look for edge_owner_to_timeline_media or items in various IG response shapes
    edges: list[dict] = []
    user_data = payload.get("data", {}).get("user", {}) or payload.get("user", {})
    if isinstance(user_data, dict):
        timeline = user_data.get("edge_owner_to_timeline_media", {})
        if isinstance(timeline, dict) and "edges" in timeline:
            edges = timeline.get("edges", [])

    if not edges:
        # Fallback to items list (mobile REST feed format)
        items = payload.get("items") or payload.get("data", {}).get("items") or []
        for it in items:
            if isinstance(it, dict):
                edges.append({"node": it})

    for edge in edges:
        node = edge.get("node") if isinstance(edge, dict) else edge
        if not isinstance(node, dict):
            continue

        shortcode = node.get("code") or node.get("shortcode") or ""
        if not shortcode:
            continue

        # Extract play count / views
        views = (
            node.get("video_play_count")
            or node.get("play_count")
            or node.get("video_view_count")
            or node.get("view_count")
            or 0
        )
        try:
            views = int(views)
        except (ValueError, TypeError):
            views = 0

        # Likes
        likes = 0
        liked_by = node.get("edge_liked_by") or node.get("edge_media_preview_like")
        if isinstance(liked_by, dict):
            likes = int(liked_by.get("count", 0))
        elif "like_count" in node:
            likes = int(node.get("like_count", 0))

        # Comments
        comments = 0
        comment_by = node.get("edge_media_to_comment")
        if isinstance(comment_by, dict):
            comments = int(comment_by.get("count", 0))
        elif "comment_count" in node:
            comments = int(node.get("comment_count", 0))

        # Caption
        caption = ""
        caption_edge = node.get("edge_media_to_caption", {})
        if isinstance(caption_edge, dict) and "edges" in caption_edge:
            c_edges = caption_edge.get("edges", [])
            if c_edges and isinstance(c_edges[0], dict):
                caption = c_edges[0].get("node", {}).get("text", "")
        if not caption and isinstance(node.get("caption"), dict):
            caption = node["caption"].get("text", "")
        elif not caption and isinstance(node.get("caption"), str):
            caption = node.get("caption", "")

        # Timestamp
        taken_at = node.get("taken_at_timestamp") or node.get("taken_at")
        posted_at = ""
        if taken_at:
            try:
                posted_at = datetime.fromtimestamp(int(taken_at), tz=timezone.utc).isoformat()
            except Exception:
                posted_at = str(taken_at)

        url = f"https://www.instagram.com/reel/{shortcode}/"
        posts.append(
            CreatorPost(
                shortcode=str(shortcode),
                url=url,
                caption=caption.strip(),
                views=views,
                likes=likes,
                comments=comments,
                posted_at=posted_at,
            )
        )

    return posts


def harvest_creator_via_ytdlp(
    handle: str,
    platform: str = "instagram",
    max_posts: int = 50,
    use_cookies: bool = True,
    browser: str = "chrome",
    timeout: int = 120,
) -> list[CreatorPost]:
    """Discover creator posts and metadata using yt-dlp flat-playlist mode.

    Parameters
    ----------
    handle : str
        Creator handle/username.
    platform : str
        Target platform ('instagram', 'tiktok', 'youtube_shorts').
    max_posts : int
        Maximum number of posts to retrieve (default: 50).
    use_cookies : bool
        Whether to inject browser cookies.
    browser : str
        Browser name for cookie extraction.
    timeout : int
        Subprocess timeout in seconds.

    Returns
    -------
    list[CreatorPost]
        Extracted post records with metrics.
    """
    clean_handle = handle.strip().lstrip("@")
    if platform == "instagram":
        target_url = f"https://www.instagram.com/{clean_handle}/reels/"
    elif platform == "tiktok":
        target_url = f"https://www.tiktok.com/@{clean_handle}"
    elif platform in ("youtube", "youtube_shorts"):
        target_url = f"https://www.youtube.com/@{clean_handle}/shorts"
    else:
        target_url = f"https://www.instagram.com/{clean_handle}/"

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--playlist-end",
        str(max_posts),
        "--no-warnings",
    ]

    if use_cookies:
        cmd.extend(["--cookies-from-browser", browser])

    cmd.append(target_url)

    print(format_status("info", f"Executing yt-dlp playlist scan for @{clean_handle}..."), file=sys.stderr)
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        print(format_status("warning", f"yt-dlp playlist scan failed: {exc}"), file=sys.stderr)
        return []

    posts: list[CreatorPost] = []
    seen: set[str] = set()

    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue

        raw_url = entry.get("url") or entry.get("webpage_url") or ""
        code = extract_shortcode(raw_url) or entry.get("id") or ""
        if not code or code in seen:
            continue
        seen.add(code)

        views = entry.get("view_count") or 0
        likes = entry.get("like_count") or 0
        comments = entry.get("comment_count") or 0
        duration = float(entry.get("duration") or 0.0)
        title = entry.get("title") or ""
        desc = entry.get("description") or ""

        post_url = raw_url if "://" in raw_url else f"https://www.instagram.com/reel/{code}/"
        posts.append(
            CreatorPost(
                shortcode=code,
                url=post_url,
                title=title,
                caption=desc,
                views=int(views),
                likes=int(likes),
                comments=int(comments),
                duration=duration,
            )
        )

    print(format_status("success", f"yt-dlp discovered {len(posts)} posts for @{clean_handle}."), file=sys.stderr)
    return posts


def harvest_creator_via_cdp(
    handle: str,
    platform: str = "instagram",
    max_scrolls: int = 6,
    cdp_base: str = "http://127.0.0.1:9222",
    scroll_delay: float = 0.8,
) -> list[CreatorPost]:
    """Harvest creator posts using active Chrome CDP session.

    Parameters
    ----------
    handle : str
        Creator handle/username.
    platform : str
        Platform name (default: 'instagram').
    max_scrolls : int
        Number of scroll operations to perform (default: 6).
    cdp_base : str
        Chrome CDP endpoint URL.
    scroll_delay : float
        Delay between scrolls in seconds.

    Returns
    -------
    list[CreatorPost]
        Extracted creator posts.
    """
    clean_handle = handle.strip().lstrip("@")
    print(format_status("info", f"Harvesting @{clean_handle} via Chrome CDP session at {cdp_base}..."), file=sys.stderr)

    tabs = get_active_instagram_tabs(cdp_base=cdp_base)
    if not tabs:
        print(format_status("warning", "No active Instagram tabs found on CDP port."), file=sys.stderr)
        return []

    # Choose first active tab
    tab = tabs[0]
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        print(format_status("error", "Active tab missing webSocketDebuggerUrl."), file=sys.stderr)
        return []

    target_reels_url = f"https://www.instagram.com/{clean_handle}/reels/"
    posts: list[CreatorPost] = []
    seen_codes: set[str] = set()

    try:
        with CDPSession(ws_url) as session:
            current_url = session.evaluate("window.location.href") or ""
            if clean_handle.lower() not in current_url.lower():
                print(format_status("info", f"Navigating to creator profile: {target_reels_url}..."), file=sys.stderr)
                session.evaluate(f"window.location.href = '{target_reels_url}'")
                time.sleep(3.5)

            # Scrape initial grid
            for scroll_idx in range(max_scrolls + 1):
                html = session.evaluate(
                    "document.documentElement ? document.documentElement.outerHTML : document.body.innerHTML"
                )
                codes = extract_reel_codes_from_html(html or "")
                for c in codes:
                    if c not in seen_codes:
                        seen_codes.add(c)
                        posts.append(
                            CreatorPost(
                                shortcode=c,
                                url=f"https://www.instagram.com/reel/{c}/",
                            )
                        )

                if scroll_idx < max_scrolls:
                    scroll_script = "window.scrollBy(0, Math.floor(window.innerHeight * 1.4));"
                    session.evaluate(scroll_script)
                    time.sleep(scroll_delay)

    except Exception as exc:
        print(format_status("warning", f"CDP creator harvest error: {exc}"), file=sys.stderr)

    print(format_status("success", f"CDP session harvested {len(posts)} reels for @{clean_handle}."), file=sys.stderr)
    return posts


def harvest_creator(
    handle: str,
    platform: str = "instagram",
    max_posts: int = 50,
    outlier_threshold: float = 1.5,
    method: str = "auto",
    use_cookies: bool = True,
    cdp_base: str = "http://127.0.0.1:9222",
) -> tuple[list[CreatorPost], CreatorStats]:
    """Unified entry point to harvest creator posts and calculate baselines.

    Tries yt-dlp first for fast metric rich flat-playlist extraction; falls back to live CDP.
    """
    clean_handle = handle.strip().lstrip("@")
    posts: list[CreatorPost] = []

    if method in ("auto", "ytdlp"):
        posts = harvest_creator_via_ytdlp(
            handle=clean_handle,
            platform=platform,
            max_posts=max_posts,
            use_cookies=use_cookies,
        )

    if not posts and method in ("auto", "cdp"):
        posts = harvest_creator_via_cdp(
            handle=clean_handle,
            platform=platform,
            max_scrolls=max(3, max_posts // 10),
            cdp_base=cdp_base,
        )

    stats = calculate_creator_baselines(
        posts=posts,
        handle=clean_handle,
        platform=platform,
        outlier_threshold=outlier_threshold,
    )

    return posts, stats
