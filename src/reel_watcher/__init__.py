"""Reel-Watcher: Universal short-form video harvester, deconstructor, and intelligence engine."""

from typing import Any

from reel_watcher.advice_library import render_advice_html
from reel_watcher.audio import (
    extract_audio,
    non_speech_energy_heuristic,
    normalize_transcript_segments,
    transcribe,
)
from reel_watcher.browser_sync import (
    CDPSession,
    extract_reel_codes_from_html,
    get_active_instagram_tabs,
    harvest_saved_reels_via_cdp,
)
from reel_watcher.config import Config, get_status_indicator, load_config
from reel_watcher.db import Vault, extract_shortcode
from reel_watcher.downloader import (
    download_media,
    download_with_apify,
    sanitize_filename,
)
from reel_watcher.ig_export import (
    export_to_tsv,
    extract_urls_from_export,
)
from reel_watcher.media import (
    detect_cuts,
    id_from_url,
    pick_frame_times,
    preflight,
    probe,
)
from reel_watcher.ocr import ocr_image
from reel_watcher.signal import (
    dedupe_frames,
    dhash_bits,
    extract_frame_jpg,
    make_contact_sheet,
    text_changed,
)
from reel_watcher.study import (
    analyze_carousel_study,
    analyze_video_study,
    parse_comment_words,
    parse_giveaway,
)
from reel_watcher.longform import (
    analyze_longform_study,
    get_longform_metadata,
)
from reel_watcher.vision import (
    VisionClient,
    extract_json_from_text,
)
from reel_watcher.web.server import (
    create_app,
    run_server,
)

__version__ = "0.1.0"
__all__ = [
    "Config",
    "load_config",
    "get_status_indicator",
    "Vault",
    "extract_shortcode",
    "detect_cuts",
    "id_from_url",
    "pick_frame_times",
    "preflight",
    "probe",
    "download_media",
    "download_with_apify",
    "sanitize_filename",
    "extract_urls_from_export",
    "export_to_tsv",
    "CDPSession",
    "extract_reel_codes_from_html",
    "get_active_instagram_tabs",
    "harvest_saved_reels_via_cdp",
    "extract_frame_jpg",
    "dhash_bits",
    "text_changed",
    "dedupe_frames",
    "make_contact_sheet",
    "ocr_image",
    "extract_audio",
    "normalize_transcript_segments",
    "transcribe",
    "non_speech_energy_heuristic",
    "VisionClient",
    "extract_json_from_text",
    "parse_comment_words",
    "parse_giveaway",
    "analyze_video_study",
    "analyze_carousel_study",
    "analyze_longform_study",
    "get_longform_metadata",
    "render_advice_html",
    "create_app",
    "run_server",
    "build_parser",
    "main",
    "__version__",
]


def __getattr__(name: str) -> Any:
    """Lazy import for CLI and subpackage symbols to avoid runpy RuntimeWarning when invoking via python -m."""
    if name in ("build_parser", "main"):
        from reel_watcher.cli import build_parser, main

        return {"build_parser": build_parser, "main": main}[name]
    if name == "web":
        import reel_watcher.web as web

        return web
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
