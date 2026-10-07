"""Configuration and environment loader for Reel-Watcher."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import dotenv


@dataclass
class Config:
    """Application configuration for reel-watcher."""

    openrouter_api_key: str | None = None
    gemini_api_key: str | None = None
    openrouter_model: str = "google/gemini-2.5-pro"
    gemini_model: str = "gemini-2.5-flash"
    vault_dir: Path = Path("vault")
    downloads_dir: Path = Path("vault/downloads")
    db_path: Path = Path("vault/reels.db")
    cdp_url: str = "http://127.0.0.1:9222"

    def ensure_directories(self) -> None:
        """Create vault and downloads directories if they do not exist."""
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        if self.db_path.parent:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)


def get_status_indicator(status_type: str) -> str:
    """Return strictly ASCII bracket indicators for terminal and CLI output.

    Enforces cross-platform and Windows console safety:
    - 'success' -> '[+]'
    - 'error'   -> '[-]'
    - 'warning' -> '[!]'
    - 'info'    -> '[*]'
    """
    mapping = {
        "success": "[+]",
        "error": "[-]",
        "warning": "[!]",
        "warn": "[!]",
        "info": "[*]",
        "progress": "[*]",
    }
    return mapping.get(status_type.lower(), "[*]")


def format_status(status_type: str, message: str) -> str:
    """Format a message with the corresponding ASCII indicator."""
    indicator = get_status_indicator(status_type)
    return f"{indicator} {message}"


def load_config(env_path: Path | None = None) -> Config:
    """Load configuration from environment variables and optional .env file.

    Parameters
    ----------
    env_path : Path | None
        Optional explicit path to a .env file. If provided and exists,
        it will be loaded. If None, default .env discovery via python-dotenv is used.
    """
    file_values: Mapping[str, str | None] = {}
    if env_path is not None:
        if env_path.is_file():
            file_values = dotenv.dotenv_values(env_path)
    else:
        # Load standard .env if present in current directory or parents
        dotenv.load_dotenv()

    def get_val(key: str, default: str | None = None) -> str | None:
        if env_path is not None and env_path.is_file():
            val = file_values.get(key)
            if val is not None and val != "":
                return val
        return os.environ.get(key, default)

    # API Keys
    openrouter_key = get_val("OPENROUTER_API_KEY")
    gemini_key = get_val("GEMINI_API_KEY")

    # Models
    openrouter_model = get_val("OPENROUTER_MODEL", "google/gemini-2.5-pro") or "google/gemini-2.5-pro"
    gemini_model = get_val("GEMINI_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash"

    # Directory Paths - deterministically anchored to repository root
    repo_root = Path(__file__).resolve().parent.parent.parent
    canonical_vault = (repo_root / "vault") if (repo_root / "vault").is_dir() else (Path.cwd() / "vault")

    vault_dir_raw = get_val("REEL_WATCHER_VAULT_DIR") or get_val("VAULT_DIR")
    vault_dir = Path(vault_dir_raw).resolve() if vault_dir_raw else canonical_vault.resolve()

    downloads_dir_raw = get_val("REEL_WATCHER_DOWNLOADS_DIR") or get_val("DOWNLOADS_DIR")
    downloads_dir = Path(downloads_dir_raw).resolve() if downloads_dir_raw else (vault_dir / "downloads")

    db_path_raw = get_val("REEL_WATCHER_DB_PATH") or get_val("DB_PATH")
    db_path = Path(db_path_raw).resolve() if db_path_raw else (vault_dir / "reels.db")

    # CDP URL
    cdp_url = get_val("REEL_WATCHER_CDP_URL") or get_val("CDP_URL", "http://127.0.0.1:9222") or "http://127.0.0.1:9222"

    return Config(
        openrouter_api_key=openrouter_key,
        gemini_api_key=gemini_key,
        openrouter_model=openrouter_model,
        gemini_model=gemini_model,
        vault_dir=vault_dir,
        downloads_dir=downloads_dir,
        db_path=db_path,
        cdp_url=cdp_url,
    )
