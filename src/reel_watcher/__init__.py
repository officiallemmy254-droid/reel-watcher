"""Reel-Watcher: Universal short-form video harvester, deconstructor, and intelligence engine."""

from reel_watcher.config import Config, load_config, get_status_indicator
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
    "__version__",
]
