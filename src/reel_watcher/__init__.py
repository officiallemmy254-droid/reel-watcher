"""Reel-Watcher: Universal short-form video harvester, deconstructor, and intelligence engine."""

from reel_watcher.config import Config, load_config, get_status_indicator
from reel_watcher.db import Vault, extract_shortcode

__version__ = "0.1.0"
__all__ = [
    "Config",
    "load_config",
    "get_status_indicator",
    "Vault",
    "extract_shortcode",
    "__version__",
]
