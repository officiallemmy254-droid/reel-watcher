"""CLI Interface & Subcommand Dispatcher for Reel-Watcher (`cli.py`).

Provides unified console commands for media preflight checks, URL enqueueing,
Chrome CDP harvester sync, Instagram export parsing, downloading, multimodal
study deconstruction, SQLite vault queries, and static advice library generation.
Strict ASCII output formatting ([+], [-], [!], [*]) across all environments.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

from reel_watcher.advice_library import render_advice_html
from reel_watcher.browser_sync import harvest_saved_reels_via_cdp
from reel_watcher.config import Config, format_status, load_config
from reel_watcher.db import Vault, extract_shortcode
from reel_watcher.downloader import download_media
from reel_watcher.creator import filter_outliers, harvest_creator
from reel_watcher.dossier import export_dossier
from reel_watcher.ig_export import export_to_tsv, extract_urls_from_export
from reel_watcher.media import preflight
from reel_watcher.saved_processor import ingest_local_folder, sync_saved_collection
from reel_watcher.study import analyze_carousel_study, analyze_video_study
from reel_watcher.vision import VisionClient


def _get_vault(args: argparse.Namespace, config: Config) -> Vault:
    """Helper to instantiate Vault using CLI arguments or active configuration."""
    db_path = getattr(args, "db", None) or config.db_path
    out_root = getattr(args, "out_root", None) or getattr(args, "vault_dir", None) or config.vault_dir
    return Vault(db_path=db_path, out_root=out_root)


# ==============================================================================
# Subcommand Handlers
# ==============================================================================


def cmd_preflight(args: argparse.Namespace) -> int:
    """Run preflight check on external binaries and dependencies."""
    print(format_status("info", "Executing environment preflight check..."))
    res = preflight()

    if isinstance(res, dict):
        for binary, ok in res.items():
            if ok:
                print(format_status("success", f"Found operational dependency: {binary}"))
            else:
                print(format_status("warning", f"Dependency missing or unavailable: {binary}"))

        if res.get("ffmpeg", False) and res.get("ffprobe", False):
            print(format_status("success", "All core media tools operational."))
            return 0
        else:
            print(format_status("error", "Critical media dependencies missing (ffmpeg/ffprobe required)."))
            return 1

    if not res:
        print(format_status("success", "All core media tools operational (ffmpeg, ffprobe)."))
        return 0
    else:
        print(format_status("error", res))
        return 1


def cmd_enqueue(args: argparse.Namespace) -> int:
    """Enqueue one or more reel URLs into SQLite Vault."""
    config = load_config()
    vault = _get_vault(args, config)

    urls_to_enqueue: list[str] = []

    # Positional or explicit URLs
    if args.urls:
        urls_to_enqueue.extend(args.urls)

    # From file
    if args.file:
        file_path = Path(args.file)
        if not file_path.is_file():
            print(format_status("error", f"URLs file not found: {file_path}"))
            return 1
        lines = file_path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            cleaned = line.strip()
            if cleaned and not cleaned.startswith("#"):
                urls_to_enqueue.append(cleaned)

    if not urls_to_enqueue:
        print(format_status("warning", "No URLs provided to enqueue. Specify URLs or --file."))
        return 1

    collection = getattr(args, "collection", "") or ""
    enqueued_count = 0

    for url in urls_to_enqueue:
        shortcode = extract_shortcode(url)
        if vault.enqueue_url(url, collection=collection):
            enqueued_count += 1
            print(format_status("success", f"Enqueued {shortcode} (collection: '{collection}')."))
        else:
            print(format_status("info", f"Skipped {shortcode or url} (already in queue or studied)."))

    print(format_status("success", f"{enqueued_count} URL(s) enqueued into Vault queue."))
    return 0


def cmd_harvest(args: argparse.Namespace) -> int:
    """Harvest saved reels from live Chrome CDP session."""
    config = load_config()
    vault = _get_vault(args, config)

    cdp_url = args.cdp_url or config.cdp_url
    collection = args.collection or "saved_feed"

    print(format_status("info", f"Harvesting saved reels from Chrome CDP session at {cdp_url}..."))
    try:
        results = harvest_saved_reels_via_cdp(cdp_base=cdp_url, target_collection=collection, vault=vault)
    except Exception as err:
        print(format_status("error", f"Chrome CDP harvest failed: {err}"))
        return 1

    enqueued_count = 0
    for item in results:
        code = item.get("code") if isinstance(item, dict) else str(item)
        url = item.get("url") if isinstance(item, dict) else f"https://www.instagram.com/reel/{code}/"
        if vault.enqueue_url(url, collection=collection):
            enqueued_count += 1
        print(format_status("success", f"Harvested reel: {code}"))

    print(format_status("success", f"Harvester finished. {len(results)} reel(s) harvested."))
    return 0


def cmd_export_parse(args: argparse.Namespace) -> int:
    """Parse Instagram export directory/file to TSV and optional Vault enqueue."""
    config = load_config()
    export_path = Path(args.path)
    if not export_path.exists():
        print(format_status("error", f"Export path not found: {export_path}"))
        return 1

    collection_filter = args.collection or ""
    print(format_status("info", f"Parsing Instagram export from {export_path}..."))

    records = extract_urls_from_export(export_path, collection_filter=collection_filter)
    print(format_status("info", f"Extracted {len(records)} reel URLs from export."))

    if args.tsv:
        tsv_path = Path(args.tsv)
        export_to_tsv(records, tsv_path)
        print(format_status("success", f"Exported {len(records)} records to TSV: {tsv_path}"))

    if args.enqueue:
        vault = _get_vault(args, config)
        enqueued_count = 0
        for url, coll in records:
            if vault.enqueue_url(url, collection=coll):
                enqueued_count += 1
        print(format_status("success", f"Enqueued {enqueued_count} URLs from export into Vault queue."))

    return 0


def cmd_download(args: argparse.Namespace) -> int:
    """Download media for single URL or batch pending queue items."""
    config = load_config()
    out_dir = Path(args.out_dir) if args.out_dir else config.downloads_dir
    browser = args.browser or "chrome"
    use_cookies = not args.no_cookies

    if args.url:
        print(format_status("info", f"Downloading media for {args.url}..."))
        try:
            downloaded = download_media(
                args.url,
                dest_dir=out_dir,
                browser=browser,
                use_cookies=use_cookies,
            )
            v_path = downloaded.get("video_path") if isinstance(downloaded, dict) else downloaded
            print(format_status("success", f"Downloaded media to {v_path}"))
            return 0
        except Exception as err:
            print(format_status("error", f"Download failed: {err}"))
            return 1

    if args.pending:
        vault = _get_vault(args, config)
        pending = vault.get_pending_urls(limit=args.limit)
        if not pending:
            print(format_status("info", "No pending reels in Vault queue to download."))
            return 0

        print(format_status("info", f"Processing {len(pending)} pending reels from Vault queue..."))
        success_count = 0

        for item in pending:
            url = item["url"]
            code = item["shortcode"]
            vault.update_queue_status(code, "processing")
            try:
                dest = download_media(
                    url,
                    dest_dir=out_dir,
                    browser=browser,
                    use_cookies=use_cookies,
                )
                vault.update_queue_status(code, "downloaded")
                success_count += 1
                v_path = dest.get("video_path") if isinstance(dest, dict) else dest
                print(format_status("success", f"Downloaded [{code}] -> {getattr(v_path, 'name', v_path)}"))
            except Exception as err:
                vault.update_queue_status(code, "failed")
                print(format_status("error", f"Failed downloading [{code}]: {err}"))

        print(format_status("success", f"Downloaded {success_count}/{len(pending)} pending reels."))
        return 0

    print(format_status("warning", "Specify a URL or pass --pending to process the Vault queue."))
    return 1


def cmd_study(args: argparse.Namespace) -> int:
    """Deconstruct media and synthesize multimodal study into Vault."""
    config = load_config()
    vault = _get_vault(args, config)

    target_path = Path(args.path)
    if not target_path.exists():
        print(format_status("error", f"Target media file not found: {target_path}"))
        return 1

    provider = args.provider or "gemini"
    model = args.model
    api_key = args.api_key

    # Initialize VisionClient
    vision = VisionClient(provider=provider, model=model, api_key=api_key)

    work_dir = target_path.parent / f"work_{target_path.stem}"
    work_dir.mkdir(parents=True, exist_ok=True)

    item = {
        "url": args.url or f"https://instagram.com/reel/{target_path.stem}/",
        "shortcode": target_path.stem,
        "collection": args.collection or "study",
    }
    meta = {
        "title": args.title or target_path.stem.replace("_", " ").title(),
        "author": args.author or "unknown",
    }

    print(format_status("info", f"Starting multimodal study deconstruction for {target_path.name}..."))
    try:
        study = analyze_video_study(
            video_path=target_path,
            item=item,
            meta=meta,
            work_dir=work_dir,
            vision=vision,
            fast=args.fast,
        )
        vault.save_study(study)
        print(format_status("success", f"Saved study {study['code']} to Vault (score: {study.get('score', 0.0)})."))
        return 0
    except Exception as err:
        print(format_status("error", f"Study deconstruction failed: {err}"))
        return 1


def cmd_advice(args: argparse.Namespace) -> int:
    """Generate static, self-contained HTML advice library from Vault studies."""
    config = load_config()
    vault = _get_vault(args, config)

    out_file = Path(args.out) if args.out else (vault.out_root / "advice_library.html")
    title = args.title or "Reel-Watcher Advice Library"
    query = args.query or ""
    limit = args.limit or 200

    print(format_status("info", f"Querying studies from Vault (limit={limit}, query='{query}')..."))
    studies = vault.list_studies(limit=limit, query=query)

    render_advice_html(studies, out_file, title=title)
    print(format_status("success", f"Advice Library HTML rendered to {out_file} ({len(studies)} studies)."))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List studies or queue items stored in Vault."""
    config = load_config()
    vault = _get_vault(args, config)

    if args.queue:
        items = vault.get_pending_urls(limit=args.limit)
        if not items:
            print(format_status("info", "No items currently pending in Vault queue."))
            return 0
        print(format_status("info", f"Vault Pending Queue ({len(items)} items):"))
        for it in items:
            print(f"  [{it.get('status', 'pending')}] {it['shortcode']} | {it.get('collection', '')} | {it['url']}")
        return 0

    studies = vault.list_studies(limit=args.limit, query=args.query or "")
    if not studies:
        print(format_status("info", "No studies recorded in Vault yet."))
        return 0

    print(format_status("info", f"Vault Studies ({len(studies)} records):"))
    for s in studies:
        code = s.get("code") or s.get("shortcode")
        score = s.get("score", 0.0)
        fw = s.get("framework") or "N/A"
        title = s.get("title") or "Untitled"
        author = s.get("author") or "unknown"
        print(f"  [{score:.1f}/10] {code} - '{title}' (@{author}) | Framework: {fw}")

    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Run interactive Playbook Web Dashboard and REST API."""
    from reel_watcher.web.server import run_server

    config = load_config()
    vault = _get_vault(args, config)
    port = getattr(args, "port", 8440)
    host = getattr(args, "host", "127.0.0.1")

    run_server(port=port, host=host, vault=vault)
    return 0


def cmd_creator(args: argparse.Namespace) -> int:
    """Handle creator commands: scan, harvest, dossier."""
    action = getattr(args, "creator_action", None)
    if not action:
        print(format_status("error", "Specify creator action: 'scan', 'harvest', or 'dossier'."))
        return 1

    config = load_config()
    vault = _get_vault(args, config)
    handle = args.handle.strip().lstrip("@")
    platform = getattr(args, "platform", "instagram") or "instagram"

    if action == "scan":
        limit = getattr(args, "limit", 50)
        thresh = getattr(args, "outlier_threshold", 1.5)
        print(format_status("info", f"Scanning @{handle} on {platform.title()} (max {limit} posts)..."))
        posts, stats = harvest_creator(handle=handle, platform=platform, max_posts=limit, outlier_threshold=thresh)
        vault.upsert_creator(
            handle=stats.handle,
            platform=stats.platform,
            median_views=stats.median_views,
            mean_likes=stats.mean_likes,
        )
        print(format_status("success", f"Creator @{stats.handle} ({stats.platform.title()}):"))
        print(f"  Total Posts Scanned: {stats.total_posts}")
        print(f"  Median Views: {stats.median_views:,}")
        print(f"  Mean Likes: {stats.mean_likes:,}")
        print(f"  Outliers Flagged (>{thresh}x median): {len(stats.top_outliers)}")
        for o in stats.top_outliers[:10]:
            print(f"    [{o.outlier_multiplier}x] {o.shortcode} - {o.views:,} views | {o.caption[:60]}...")
        return 0

    elif action == "harvest":
        limit = getattr(args, "limit", 50)
        thresh = getattr(args, "min_multiplier", 1.5)
        top_n = getattr(args, "top", 10)
        print(format_status("info", f"Harvesting outliers for @{handle} on {platform.title()}..."))
        posts, stats = harvest_creator(handle=handle, platform=platform, max_posts=limit, outlier_threshold=thresh)
        cid = vault.upsert_creator(
            handle=stats.handle,
            platform=stats.platform,
            median_views=stats.median_views,
            mean_likes=stats.mean_likes,
        )
        outliers = filter_outliers(posts, stats=stats, min_multiplier=thresh, top_n=top_n)
        enqueued_count = 0
        for o in outliers:
            if vault.enqueue_url(
                url=o.url,
                collection=f"creator:{handle}",
                creator_id=cid,
                views=o.views,
                likes=o.likes,
                outlier_multiplier=o.outlier_multiplier,
            ):
                enqueued_count += 1
                print(format_status("success", f"Enqueued outlier [{o.shortcode}] ({o.outlier_multiplier}x median, {o.views:,} views)"))

        print(format_status("success", f"Harvested {len(outliers)} outlier(s) for @{handle} ({enqueued_count} new enqueued)."))
        return 0

    elif action == "dossier":
        out_dir = getattr(args, "out_dir", None)
        print(format_status("info", f"Synthesizing competitive intelligence dossier for @{handle}..."))
        md_path = export_dossier(handle=handle, vault=vault, out_dir=out_dir, platform=platform)
        print(format_status("success", f"Generated Creator Dossier for @{handle}: {md_path.name}"))
        return 0

    print(format_status("error", f"Unknown creator action: {action}"))
    return 1


def cmd_sync_saved(args: argparse.Namespace) -> int:
    """Sync saved collection via live Chrome CDP."""
    config = load_config()
    vault = _get_vault(args, config)
    collection = getattr(args, "collection", "all-posts") or "all-posts"
    max_scrolls = getattr(args, "max_scrolls", 5)
    auto_download = not getattr(args, "no_download", False)
    auto_study = getattr(args, "auto_study", False)
    cdp_url = getattr(args, "cdp_url", None) or config.cdp_url

    summary = sync_saved_collection(
        collection=collection,
        max_scrolls=max_scrolls,
        auto_download=auto_download,
        auto_study=auto_study,
        vault=vault,
        cdp_base=cdp_url,
    )
    print(format_status("success", f"Sync complete for '{collection}': {summary['harvested']} harvested, {summary['downloaded']} downloaded, {summary['studied']} studied, {summary['unavailable']} unavailable."))
    return 0


def cmd_ingest_folder(args: argparse.Namespace) -> int:
    """Ingest local video folder into Vault."""
    config = load_config()
    vault = _get_vault(args, config)
    folder_path = Path(args.path)
    collection = getattr(args, "collection", "local_ingest") or "local_ingest"
    recursive = getattr(args, "recursive", False)
    auto_study = getattr(args, "auto_study", False)
    fast = getattr(args, "fast", False)

    results = ingest_local_folder(
        folder_path=folder_path,
        collection=collection,
        recursive=recursive,
        auto_study=auto_study,
        vault=vault,
        fast=fast,
    )
    print(format_status("success", f"Ingested {len(results)} local video(s) into collection '{collection}'."))
    return 0


# ==============================================================================
# Argument Parser Construction
# ==============================================================================


def build_parser() -> argparse.ArgumentParser:
    """Construct and configure the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="reel-watcher",
        description="Universal short-form video harvester, deconstructor, and intelligence engine.",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # 1. preflight
    p_preflight = subparsers.add_parser("preflight", help="Check system dependencies (ffmpeg, yt-dlp, OCR).")
    p_preflight.set_defaults(func=cmd_preflight)

    # 2. enqueue
    p_enqueue = subparsers.add_parser("enqueue", help="Enqueue reel URLs into Vault queue.")
    p_enqueue.add_argument("urls", nargs="*", help="One or more reel URLs to enqueue.")
    p_enqueue.add_argument("--file", "-f", help="Text file containing reel URLs to enqueue.")
    p_enqueue.add_argument("--collection", "-c", default="", help="Collection name tag.")
    p_enqueue.add_argument("--db", help="Path to SQLite database.")
    p_enqueue.add_argument("--out-root", help="Path to vault output root directory.")
    p_enqueue.set_defaults(func=cmd_enqueue)

    # 3. harvest
    p_harvest = subparsers.add_parser("harvest", help="Harvest saved reels from live Chrome CDP session.")
    p_harvest.add_argument("--cdp-url", default="", help="Chrome DevTools Protocol endpoint URL.")
    p_harvest.add_argument("--collection", "-c", default="saved_feed", help="Collection name tag.")
    p_harvest.add_argument("--db", help="Path to SQLite database.")
    p_harvest.add_argument("--out-root", help="Path to vault output root directory.")
    p_harvest.set_defaults(func=cmd_harvest)

    # 4. export-parse
    p_export = subparsers.add_parser("export-parse", help="Parse Instagram download exports (JSON/HTML).")
    p_export.add_argument("path", help="Path to export JSON/HTML file or directory.")
    p_export.add_argument("--collection", "-c", default="", help="Filter by collection name.")
    p_export.add_argument("--tsv", help="Optional output TSV file path.")
    p_export.add_argument("--enqueue", action="store_true", help="Enqueue extracted URLs into Vault queue.")
    p_export.add_argument("--db", help="Path to SQLite database.")
    p_export.add_argument("--out-root", help="Path to vault output root directory.")
    p_export.set_defaults(func=cmd_export_parse)

    # 5. download
    p_download = subparsers.add_parser("download", help="Download media using yt-dlp cookie bridge.")
    p_download.add_argument("url", nargs="?", default="", help="Single reel URL to download.")
    p_download.add_argument("--pending", action="store_true", help="Download all pending items from Vault queue.")
    p_download.add_argument("--limit", type=int, default=20, help="Max pending items to download.")
    p_download.add_argument("--browser", default="chrome", help="Browser for cookie extraction (default: chrome).")
    p_download.add_argument("--no-cookies", action="store_true", help="Disable browser cookie extraction.")
    p_download.add_argument("--out-dir", help="Output directory for downloaded media.")
    p_download.add_argument("--db", help="Path to SQLite database.")
    p_download.add_argument("--out-root", help="Path to vault output root directory.")
    p_download.set_defaults(func=cmd_download)

    # 6. study
    p_study = subparsers.add_parser("study", help="Deconstruct media and synthesize multimodal study.")
    p_study.add_argument("path", help="Path to media video file or slide image.")
    p_study.add_argument("--url", default="", help="Original reel URL.")
    p_study.add_argument("--title", default="", help="Title override.")
    p_study.add_argument("--author", default="", help="Author username override.")
    p_study.add_argument("--collection", default="", help="Collection name tag.")
    p_study.add_argument("--fast", action="store_true", help="Use fast frame sampling.")
    p_study.add_argument("--provider", default="gemini", help="Vision provider (gemini, openrouter, fake, etc.).")
    p_study.add_argument("--model", default=None, help="Vision model override.")
    p_study.add_argument("--api-key", default=None, help="API key override.")
    p_study.add_argument("--db", help="Path to SQLite database.")
    p_study.add_argument("--out-root", help="Path to vault output root directory.")
    p_study.set_defaults(func=cmd_study)

    # 7. advice
    p_advice = subparsers.add_parser("advice", help="Generate self-contained static HTML advice library.")
    p_advice.add_argument("--out", help="Output HTML file path (default: vault/advice_library.html).")
    p_advice.add_argument("--title", default="Reel-Watcher Advice Library", help="Title for the advice library.")
    p_advice.add_argument("--query", default="", help="Filter studies by query.")
    p_advice.add_argument("--limit", type=int, default=200, help="Maximum number of studies to include.")
    p_advice.add_argument("--db", help="Path to SQLite database.")
    p_advice.add_argument("--out-root", help="Path to vault output root directory.")
    p_advice.set_defaults(func=cmd_advice)

    # 8. list
    p_list = subparsers.add_parser("list", help="List studies or pending queue items in Vault.")
    p_list.add_argument("--queue", action="store_true", help="List pending queue items instead of studies.")
    p_list.add_argument("--limit", type=int, default=50, help="Max entries to list.")
    p_list.add_argument("--query", default="", help="Search query filter.")
    p_list.add_argument("--db", help="Path to SQLite database.")
    p_list.add_argument("--out-root", help="Path to vault output root directory.")
    p_list.set_defaults(func=cmd_list)

    # 9. serve
    p_serve = subparsers.add_parser("serve", help="Run interactive Playbook Web Dashboard and API.")
    p_serve.add_argument("--port", type=int, default=8440, help="Port to bind web server (default: 8440).")
    p_serve.add_argument("--host", default="127.0.0.1", help="Host address to bind web server (default: 127.0.0.1).")
    p_serve.add_argument("--db", help="Path to SQLite database.")
    p_serve.add_argument("--out-root", help="Path to vault output root directory.")
    p_serve.set_defaults(func=cmd_serve)

    # 10. creator
    p_creator = subparsers.add_parser("creator", help="Creator profile scanning, outlier harvesting, and dossier synthesis.")
    c_sub = p_creator.add_subparsers(dest="creator_action", help="Creator action ('scan', 'harvest', 'dossier')")

    # creator scan
    p_c_scan = c_sub.add_parser("scan", help="Scan creator profile and compute baselines and outliers.")
    p_c_scan.add_argument("handle", help="Creator handle or username.")
    p_c_scan.add_argument("--platform", default="instagram", help="Platform ('instagram', 'tiktok', 'youtube_shorts').")
    p_c_scan.add_argument("--limit", type=int, default=50, help="Max posts to scan.")
    p_c_scan.add_argument("--outlier-threshold", type=float, default=1.5, help="Multiplier threshold over median views.")
    p_c_scan.add_argument("--db", help="Path to SQLite database.")
    p_c_scan.add_argument("--out-root", help="Path to vault output root directory.")
    p_c_scan.set_defaults(func=cmd_creator)

    # creator harvest
    p_c_harvest = c_sub.add_parser("harvest", help="Harvest and enqueue top outlier reels for a creator.")
    p_c_harvest.add_argument("handle", help="Creator handle or username.")
    p_c_harvest.add_argument("--platform", default="instagram", help="Platform ('instagram', 'tiktok', 'youtube_shorts').")
    p_c_harvest.add_argument("--limit", type=int, default=50, help="Max posts to scan.")
    p_c_harvest.add_argument("--min-multiplier", type=float, default=1.5, help="Minimum outlier multiplier.")
    p_c_harvest.add_argument("--top", type=int, default=10, help="Top N outliers to enqueue.")
    p_c_harvest.add_argument("--auto-study", action="store_true", help="Automatically analyze downloaded media.")
    p_c_harvest.add_argument("--db", help="Path to SQLite database.")
    p_c_harvest.add_argument("--out-root", help="Path to vault output root directory.")
    p_c_harvest.set_defaults(func=cmd_creator)

    # creator dossier
    p_c_dossier = c_sub.add_parser("dossier", help="Synthesize competitive intelligence dossier for a creator.")
    p_c_dossier.add_argument("handle", help="Creator handle or username.")
    p_c_dossier.add_argument("--platform", default="instagram", help="Platform ('instagram', 'tiktok', 'youtube_shorts').")
    p_c_dossier.add_argument("--out-dir", help="Output directory for dossier report.")
    p_c_dossier.add_argument("--db", help="Path to SQLite database.")
    p_c_dossier.add_argument("--out-root", help="Path to vault output root directory.")
    p_c_dossier.set_defaults(func=cmd_creator)

    # 11. sync-saved
    p_sync_saved = subparsers.add_parser("sync-saved", help="End-to-end sync of Instagram saved collections.")
    p_sync_saved.add_argument("--collection", "-c", default="all-posts", help="Target collection name.")
    p_sync_saved.add_argument("--max-scrolls", type=int, default=5, help="Max scroll passes.")
    p_sync_saved.add_argument("--no-download", action="store_true", help="Only enqueue without downloading media.")
    p_sync_saved.add_argument("--auto-study", action="store_true", help="Automatically analyze downloaded media.")
    p_sync_saved.add_argument("--cdp-url", default="", help="Chrome CDP URL.")
    p_sync_saved.add_argument("--db", help="Path to SQLite database.")
    p_sync_saved.add_argument("--out-root", help="Path to vault output root directory.")
    p_sync_saved.set_defaults(func=cmd_sync_saved)

    # 12. ingest-folder
    p_ingest = subparsers.add_parser("ingest-folder", help="Batch ingest local video files into Vault.")
    p_ingest.add_argument("path", help="Directory path containing video files.")
    p_ingest.add_argument("--collection", "-c", default="local_ingest", help="Collection tag.")
    p_ingest.add_argument("--recursive", "-r", action="store_true", help="Recursively scan subdirectories.")
    p_ingest.add_argument("--auto-study", action="store_true", help="Automatically analyze video files.")
    p_ingest.add_argument("--fast", action="store_true", help="Use fast frame extraction.")
    p_ingest.add_argument("--db", help="Path to SQLite database.")
    p_ingest.add_argument("--out-root", help="Path to vault output root directory.")
    p_ingest.set_defaults(func=cmd_ingest_folder)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint dispatching commands and subcommands.

    Parameters
    ----------
    argv : list[str] | None
        Command-line argument vector. If None, sys.argv[1:] is used.

    Returns
    -------
    int
        Exit status code (0 for success, non-zero for error).
    """
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()

    if not argv:
        parser.print_help()
        return 0

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 0

    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    try:
        return int(args.func(args))
    except Exception as err:
        print(format_status("error", f"Command failed: {err}"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
