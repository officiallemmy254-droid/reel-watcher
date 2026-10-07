"""Unified Saved Collections Sync & Local Folder Ingestion Engine (`saved_processor.py`).

Provides:
- End-to-end sync of Instagram saved posts & collections via live Chrome CDP
- Dead/private reel resilience (marking 'unavailable' without stalling queue)
- Batch local video folder discovery, deduplication, and Vault ingestion
- Vision-first study orchestration for local videos lacking social captions
Strict ASCII output formatting across Windows environments.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys
from typing import Any

from reel_watcher.browser_sync import harvest_saved_reels_via_cdp
from reel_watcher.config import format_status, load_config
from reel_watcher.db import Vault, extract_shortcode
from reel_watcher.downloader import VIDEO_EXTENSIONS, download_media, sanitize_filename
from reel_watcher.study import analyze_video_study
from reel_watcher.vision import VisionClient


def sync_saved_collection(
    collection: str = "all-posts",
    max_scrolls: int = 5,
    auto_download: bool = True,
    auto_study: bool = False,
    vault: Vault | None = None,
    cdp_base: str = "http://127.0.0.1:9222",
    downloads_dir: Path | str | None = None,
    vision: VisionClient | None = None,
    scroll_delay: float = 0.6,
) -> dict[str, int]:
    """Execute end-to-end synchronization of an Instagram saved collection.

    Orchestrates:
    1. CDP live session harvest of specified saved collection
    2. Automatic downloading of new pending reels with dead-reel fault tolerance
    3. Optional automated multimodal study synthesis

    Parameters
    ----------
    collection : str
        Target saved collection name (e.g., 'all-posts', 'Hooks', 'Offers').
    max_scrolls : int
        Number of scroll passes to perform.
    auto_download : bool
        Whether to immediately download harvested items.
    auto_study : bool
        Whether to immediately deconstruct downloaded videos.
    vault : Vault | None
        Vault instance.
    cdp_base : str
        Chrome CDP endpoint URL.
    downloads_dir : Path | str | None
        Destination folder for downloaded media.
    vision : VisionClient | None
        VisionClient instance if auto_study is True.
    scroll_delay : float
        Delay between CDP scrolls in seconds.

    Returns
    -------
    dict[str, int]
        Summary metrics: {'harvested', 'downloaded', 'studied', 'unavailable'}
    """
    config = load_config()
    v = vault or Vault(db_path=config.db_path, out_root=config.vault_dir)
    d_dir = Path(downloads_dir) if downloads_dir else config.downloads_dir
    d_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "harvested": 0,
        "downloaded": 0,
        "studied": 0,
        "unavailable": 0,
    }

    # 1. Harvest via CDP
    print(format_status("info", f"Syncing saved collection '{collection}' via CDP at {cdp_base}..."))
    harvested = harvest_saved_reels_via_cdp(
        cdp_base=cdp_base,
        target_collection=collection,
        max_scrolls=max_scrolls,
        vault=v,
        scroll_delay=scroll_delay,
    )
    summary["harvested"] = len(harvested)

    if not auto_download:
        return summary

    # 2. Process pending downloads
    pending = v.get_pending_urls(limit=100)
    # Filter by collection if specified
    col_filter = collection.lower().strip()
    target_items = [
        item for item in pending
        if not col_filter or col_filter in str(item.get("collection", "")).lower()
    ]

    if not target_items:
        print(format_status("info", f"No pending reels to download for collection '{collection}'."))
        return summary

    print(format_status("info", f"Downloading {len(target_items)} pending reels for collection '{collection}'..."))

    for item in target_items:
        code = item["shortcode"]
        url = item["url"]
        v.update_queue_status(code, "processing")

        try:
            downloaded = download_media(
                url=url,
                dest_dir=d_dir,
                use_cookies=True,
                browser="chrome",
            )
            # download_media returns either a dict or Path
            video_file = (
                downloaded.get("video_path")
                if isinstance(downloaded, dict)
                else Path(downloaded)
            )
            v.update_queue_status(code, "downloaded")
            summary["downloaded"] += 1
            print(format_status("success", f"Downloaded [{code}] -> {Path(video_file).name}"))

            # 3. Optional auto-study
            if auto_study and video_file and Path(video_file).is_file():
                v_client = vision or VisionClient()
                work_dir = Path(video_file).parent / f"work_{code}"
                meta = {
                    "title": downloaded.get("title", f"Reel {code}") if isinstance(downloaded, dict) else f"Reel {code}",
                    "author": downloaded.get("author", "unknown") if isinstance(downloaded, dict) else "unknown",
                    "caption": downloaded.get("caption", "") if isinstance(downloaded, dict) else "",
                }
                study = analyze_video_study(
                    video_path=video_file,
                    item=item,
                    meta=meta,
                    work_dir=work_dir,
                    vision=v_client,
                )
                v.record_study(study)
                summary["studied"] += 1
                print(format_status("success", f"Studied and vaulted [{code}]."))

        except Exception as exc:
            err_msg = str(exc).lower()
            if any(k in err_msg for k in ("unavailable", "removed", "private", "not found", "deleted")):
                v.update_queue_status(code, "unavailable")
                summary["unavailable"] += 1
                print(format_status("warning", f"Reel [{code}] is unavailable/private: {exc}"))
            else:
                v.update_queue_status(code, "failed")
                print(format_status("error", f"Failed downloading [{code}]: {exc}"))

    print(
        format_status(
            "success",
            f"Sync finished: {summary['harvested']} harvested, "
            f"{summary['downloaded']} downloaded, "
            f"{summary['studied']} studied, "
            f"{summary['unavailable']} unavailable.",
        )
    )
    return summary


def ingest_local_folder(
    folder_path: Path | str,
    collection: str = "local_ingest",
    recursive: bool = False,
    auto_study: bool = False,
    vault: Vault | None = None,
    vision: VisionClient | None = None,
    fast: bool = False,
) -> list[dict[str, Any]]:
    """Scan and ingest local video files into the Vault.

    Parameters
    ----------
    folder_path : Path | str
        Path to local folder containing video files.
    collection : str
        Collection tag for ingested files (default: 'local_ingest').
    recursive : bool
        Whether to recursively scan subdirectories.
    auto_study : bool
        Whether to immediately run multimodal study analysis.
    vault : Vault | None
        Vault instance.
    vision : VisionClient | None
        VisionClient instance if auto_study is True.
    fast : bool
        Whether to use fast frame extraction.

    Returns
    -------
    list[dict[str, Any]]
        List of ingested video records.
    """
    f_path = Path(folder_path).resolve()
    if not f_path.is_dir():
        print(format_status("error", f"Provided path is not a directory: {f_path}"))
        return []

    config = load_config()
    v = vault or Vault(db_path=config.db_path, out_root=config.vault_dir)

    print(format_status("info", f"Scanning {f_path} for video files (recursive={recursive})..."))

    candidates: list[Path] = []
    if recursive:
        for root, _, files in os.walk(f_path):
            for file in files:
                p = Path(root) / file
                if p.suffix.lower() in VIDEO_EXTENSIONS:
                    candidates.append(p)
    else:
        for p in f_path.iterdir():
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
                candidates.append(p)

    if not candidates:
        print(format_status("warning", f"No video files found in {f_path} matching {VIDEO_EXTENSIONS}."))
        return []

    print(format_status("info", f"Found {len(candidates)} video file(s) to ingest."))
    ingested: list[dict[str, Any]] = []

    v_client = vision or VisionClient() if auto_study else None

    for vid in candidates:
        safe_name = sanitize_filename(vid.stem)
        code = f"local_{safe_name}"
        pseudo_url = f"file:///{vid.as_posix()}"

        enqueued = v.enqueue_url(url=pseudo_url, collection=collection)
        if enqueued:
            print(format_status("success", f"Enqueued local video [{code}] into Vault."))
        else:
            print(format_status("info", f"Local video [{code}] already exists in Vault."))

        record = {
            "code": code,
            "path": str(vid),
            "collection": collection,
            "url": pseudo_url,
        }
        ingested.append(record)

        if auto_study and v_client is not None:
            work_dir = vid.parent / f"work_{code}"
            item = {
                "url": pseudo_url,
                "shortcode": code,
                "collection": collection,
            }
            meta = {
                "title": vid.stem.replace("_", " ").title(),
                "author": "local_import",
                "caption": "",
            }
            try:
                study = analyze_video_study(
                    video_path=vid,
                    item=item,
                    meta=meta,
                    work_dir=work_dir,
                    vision=v_client,
                    fast=fast,
                )
                v.record_study(study)
                print(format_status("success", f"Studied and vaulted [{code}]."))
            except Exception as err:
                print(format_status("error", f"Study failed for [{code}]: {err}"))

    print(format_status("success", f"Ingested {len(ingested)} local video(s) into collection '{collection}'."))
    return ingested
