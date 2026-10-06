# Reel-Watcher

Universal Short-Form Video Harvester, Scene Deconstructor, and Intelligence Engine.

Reel-Watcher automates the capture, decomposition, transcription, and multi-modal analysis of short-form video assets (Instagram Reels, TikToks, YouTube Shorts) into actionable creative intelligence and viral hook playbooks.

## Features

- **Harvester & Downloader:** Live browser session capture via Chrome DevTools Protocol (CDP) and `yt-dlp` integration with cookie injection.
- **Scene Cut Engine:** Automated shot boundary detection and frame extraction.
- **Signal & OCR Extraction:** Frame deduplication, visual contact sheets, and on-screen text recognition.
- **Audio & Speech Transcription:** High-fidelity speech-to-text with word-level timestamps.
- **Multi-Provider Vision & Synthesis:** Deep multi-modal video deconstruction using Gemini and OpenRouter models.
- **Vault Persistence:** Local SQLite database tracking all video assets, metadata, extracted signals, and reports.
- **Web Dashboard:** Interactive playbook viewer and asset explorer.

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) or pip
- FFmpeg (for video extraction and scene splitting)

## Installation

```bash
git clone https://github.com/gwelix/reel-watcher.git
cd reel-watcher
uv venv
uv pip install -e .
```

## Configuration

Create a `.env` file in the root directory:

```env
OPENROUTER_API_KEY=your_openrouter_api_key
GEMINI_API_KEY=your_gemini_api_key
REEL_WATCHER_VAULT_DIR=vault
```

Supported environment variables:
- `OPENROUTER_API_KEY`: API key for OpenRouter models.
- `GEMINI_API_KEY`: API key for Google Gemini models.
- `OPENROUTER_MODEL`: Default OpenRouter model (default: `google/gemini-2.5-pro`).
- `GEMINI_MODEL`: Default Gemini model (default: `gemini-2.5-flash`).
- `REEL_WATCHER_VAULT_DIR`: Base vault storage directory (default: `vault`).
- `REEL_WATCHER_DOWNLOADS_DIR`: Media downloads directory (default: `vault/downloads`).
- `REEL_WATCHER_DB_PATH`: SQLite database file path (default: `vault/reels.db`).
- `REEL_WATCHER_CDP_URL`: Chrome DevTools Protocol endpoint (default: `http://127.0.0.1:9222`).

## Testing

```bash
pytest
```
