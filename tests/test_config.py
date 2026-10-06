import os
from pathlib import Path
import pytest

from reel_watcher.config import Config, load_config, get_status_indicator


def test_default_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test default configuration when no environment variables or .env files are present."""
    # Ensure env vars are cleared
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("REEL_WATCHER_VAULT_DIR", raising=False)
    monkeypatch.delenv("REEL_WATCHER_DOWNLOADS_DIR", raising=False)
    monkeypatch.delenv("REEL_WATCHER_DB_PATH", raising=False)

    # Point to a nonexistent env path so no local .env is picked up
    nonexistent_env = tmp_path / "empty.env"
    cfg = load_config(env_path=nonexistent_env)

    assert isinstance(cfg, Config)
    assert cfg.openrouter_api_key is None
    assert cfg.gemini_api_key is None
    assert cfg.vault_dir == Path("vault")
    assert cfg.downloads_dir == Path("vault/downloads")
    assert cfg.db_path == Path("vault/reels.db")
    assert cfg.cdp_url == "http://127.0.0.1:9222"


def test_load_config_from_custom_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test loading configuration from a designated .env file."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    env_file = tmp_path / "custom.env"
    env_content = """
OPENROUTER_API_KEY=test-openrouter-key-123
GEMINI_API_KEY=test-gemini-key-456
REEL_WATCHER_VAULT_DIR=custom_vault
REEL_WATCHER_DOWNLOADS_DIR=custom_vault/custom_downloads
REEL_WATCHER_DB_PATH=custom_vault/custom_reels.db
REEL_WATCHER_CDP_URL=http://localhost:9222
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
GEMINI_MODEL=gemini-2.5-pro
"""
    env_file.write_text(env_content.strip(), encoding="utf-8")

    cfg = load_config(env_path=env_file)

    assert cfg.openrouter_api_key == "test-openrouter-key-123"
    assert cfg.gemini_api_key == "test-gemini-key-456"
    assert cfg.vault_dir == Path("custom_vault")
    assert cfg.downloads_dir == Path("custom_vault/custom_downloads")
    assert cfg.db_path == Path("custom_vault/custom_reels.db")
    assert cfg.cdp_url == "http://localhost:9222"
    assert cfg.openrouter_model == "anthropic/claude-3.5-sonnet"
    assert cfg.gemini_model == "gemini-2.5-pro"


def test_load_config_from_os_environ(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Test that environment variables take priority or populate config correctly."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-openrouter-abc")
    monkeypatch.setenv("GEMINI_API_KEY", "env-gemini-xyz")
    monkeypatch.setenv("REEL_WATCHER_VAULT_DIR", str(tmp_path / "os_vault"))

    empty_env = tmp_path / "nonexistent.env"
    cfg = load_config(env_path=empty_env)

    assert cfg.openrouter_api_key == "env-openrouter-abc"
    assert cfg.gemini_api_key == "env-gemini-xyz"
    assert cfg.vault_dir == tmp_path / "os_vault"
    assert cfg.downloads_dir == (tmp_path / "os_vault") / "downloads"


def test_status_indicators_ascii_safety():
    """Verify status indicator helpers strictly output ASCII brackets only."""
    assert get_status_indicator("success") == "[+]"
    assert get_status_indicator("info") == "[*]"
    assert get_status_indicator("warning") == "[!]"
    assert get_status_indicator("error") == "[-]"

    # Test unknown fallback
    assert get_status_indicator("other") == "[*]"


def test_format_status():
    from reel_watcher.config import format_status

    assert format_status("success", "Operation completed") == "[+] Operation completed"
    assert format_status("error", "Failed to connect") == "[-] Failed to connect"
    assert format_status("warning", "Low disk space") == "[!] Low disk space"
    assert format_status("info", "Starting job") == "[*] Starting job"


def test_ensure_directories(tmp_path: Path):
    vault = tmp_path / "test_vault"
    downloads = vault / "downloads"
    db_file = vault / "reels.db"

    cfg = Config(vault_dir=vault, downloads_dir=downloads, db_path=db_file)
    assert not vault.exists()
    assert not downloads.exists()

    cfg.ensure_directories()
    assert vault.is_dir()
    assert downloads.is_dir()

