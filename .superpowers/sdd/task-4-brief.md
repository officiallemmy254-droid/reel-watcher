# Task 4: Downloader Engine with Chrome Cookie Injection & Export Parser (`downloader.py` & `ig_export.py`)

**Working Directory:** `C:\Users\SIR\reel-watcher`

**Files to create:**
- `src/reel_watcher/downloader.py`
- `src/reel_watcher/ig_export.py`
- `tests/test_downloader.py`
- `tests/test_ig_export.py`

**Global Constraints:**
- Python 3.11+, cross-platform Windows / Linux / macOS
- Uses `yt-dlp` on PATH (which is already installed on the system)
- Support for `--cookies-from-browser chrome` with graceful fallback if browser is locked
- Output ASCII status indicators only (`[+]`, `[-]`, `[!]`, `[*]`)
- No hardcoded secrets or credentials

**Interfaces:**
- `src/reel_watcher/downloader.py`:
  - `sanitize_filename(name: str) -> str`
  - `download_media(url: str, dest_dir: Path, use_cookies: bool = True, browser: str = "chrome") -> dict`:
    Returns dictionary with `{"id": str, "title": str, "author": str, "caption": str, "duration": float, "video_path": Path, "likes": int | None, "views": int | None}`
  - Optional Apify fallback if `APIFY_TOKEN` is passed
- `src/reel_watcher/ig_export.py`:
  - `extract_urls_from_export(path: Path, collection: str = "") -> list[dict]`:
    Walks JSON or HTML export files (such as `saved_posts.json`) extracting unique URLs with shortcodes and creator metadata.
  - Export CLI utility helper function `export_to_tsv(input_files: list[Path], out_tsv: Path, collection: str = "") -> int`

**Steps:**
1. Write tests in `tests/test_downloader.py` and `tests/test_ig_export.py`.
2. Run pytest to verify failures.
3. Implement `src/reel_watcher/downloader.py` and `src/reel_watcher/ig_export.py`.
4. Export public functions in `src/reel_watcher/__init__.py`.
5. Run `pytest tests/test_downloader.py tests/test_ig_export.py -v` to verify they pass.
6. Run full test suite (`pytest tests/ -v`).
7. Git add and commit with message "feat: implement yt-dlp downloader with cookie bridge and export parser".
8. Update `.superpowers/sdd/progress.md`, write report to `task-4-report.md`, and report status DONE.
