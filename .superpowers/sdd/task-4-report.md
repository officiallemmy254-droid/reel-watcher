# Task 4 Report: Downloader Engine with Chrome Cookie Injection & Export Parser (`downloader.py` & `ig_export.py`)

**Status:** DONE  
**Timestamp:** 2026-10-06T05:36:30Z  
**Commit:** `2c45615`  
**Working Directory:** `C:\Users\SIR\reel-watcher`

## 1. Overview
Implemented the robust media download engine and Instagram export parser for `reel-watcher`. The downloader wraps system `yt-dlp` on PATH with Chrome session cookie extraction (`--cookies-from-browser chrome`), provides automatic fallback when the browser cookie database is locked by an active browser instance, supports optional secondary fallback to Apify actor scraping, and sanitizes filenames across Windows, macOS, and Linux. The export parser inspects Meta/Instagram data downloads in both JSON (`saved_saved_media`, `saved_collections`, flat lists) and HTML formats, extracting unique reel URLs, shortcodes, creator usernames, and collections, with TSV export capability.

## 2. Deliverables Created & Modified
- `src/reel_watcher/downloader.py`:
  - `sanitize_filename(name: str, max_length: int = 128) -> str`: Normalizes strings for cross-platform filesystem safety, escaping forbidden characters (`/ \ : * ? " < > |`), Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`), control characters, and trimming to a safe length.
  - `download_media(url: str, dest_dir: Path | str, use_cookies: bool = True, browser: str = "chrome", apify_token: str | None = None, timeout: int = 180) -> dict`: Executes `yt-dlp` to download video streams and info JSON. Handles Chrome cookie database locks by gracefully retrying without cookies. If all yt-dlp attempts fail, automatically triggers the Apify fallback if `APIFY_TOKEN` is present. Extracts canonical metadata (`id`, `title`, `author`, `caption`, `duration`, `video_path`, `likes`, `views`) and probes duration if missing.
  - `download_with_apify(url: str, dest_dir: Path, token: str, clean_id: str | None = None) -> dict`: Direct Apify scraper integration fallback using `httpx` to trigger the Instagram reel scraper actor and download video stream bytes.
- `src/reel_watcher/ig_export.py`:
  - `extract_urls_from_export(path: Path | str, collection: str = "") -> list[dict]`: Recursively walks JSON and HTML exports. Parses standard Meta Accounts Center formats (`saved_saved_media`, `saved_collections`, flat lists, and HTML markup). Filters by collection name when specified and deduplicates records by shortcode.
  - `export_to_tsv(input_files: list[Path | str], out_tsv: Path | str, collection: str = "") -> int`: Aggregates export records across multiple files/directories, deduplicates by shortcode, and writes tab-separated rows (`url`, `shortcode`, `creator`, `collection`, `timestamp`).
- `src/reel_watcher/__init__.py`:
  - Exported `download_media`, `download_with_apify`, `sanitize_filename`, `extract_urls_from_export`, and `export_to_tsv`.
- `tests/test_downloader.py`:
  - 13 comprehensive unit tests covering filename sanitization, Windows reserved device names, empty URL rejection, successful download with Chrome cookie injection, browser lock fallback retry, `--use_cookies=False` flag, custom browser selection, yt-dlp error reporting, and Apify fallback execution.
- `tests/test_ig_export.py`:
  - 10 unit tests covering `saved_posts.json`, `saved_collections.json` with filtering, flat JSON schemas, HTML exports, HTML collection headers, directory recursive walk, shortcode deduplication, empty/corrupt files, and TSV export generation.
- `.superpowers/sdd/progress.md`:
  - Updated progress ledger with Task 4 completed at commit `2c45615`.

## 3. Test-Driven Verification (TDD)
1. **Red Phase (Initial Failure):**
   - Executed `uv run pytest tests/test_downloader.py tests/test_ig_export.py -v`.
   - Verified failure with `ModuleNotFoundError: No module named 'reel_watcher.downloader'` and `ModuleNotFoundError: No module named 'reel_watcher.ig_export'`.
2. **Green Phase (Implementation & Verification):**
   - Implemented `downloader.py` and `ig_export.py`, exported interfaces in `__init__.py`.
   - Executed `uv run pytest tests/test_downloader.py tests/test_ig_export.py -v`.
   - All 23 tests passed in 1.93s.
3. **Full Test Suite Verification:**
   - Executed `uv run pytest tests/ -v`.
   - All 55 test cases passed across configuration, vault storage, media utilities, downloader, and export parser in 3.17s (100% pass rate).

## 4. Git Commit
- Message: `feat: implement yt-dlp downloader with cookie bridge and export parser`
- Commit Hash: `2c45615`
