# Task 5: Chrome DevTools Protocol Live Saved Reels Harvester (`browser_sync.py`)

**Working Directory:** `C:\Users\SIR\reel-watcher`

**Files to create:**
- `src/reel_watcher/browser_sync.py`
- `tests/test_browser_sync.py`

**Global Constraints:**
- Python 3.11+, cross-platform Windows / Linux / macOS
- Zero raw user credentials or passwords. Uses the user's active desktop Chrome session via CDP (port 9222).
- Clean HTTP requests to `http://127.0.0.1:9222/json` for tab discovery.
- WebSocket or HTTP CDP command evaluation (`Runtime.evaluate`) to read links and emulate gentle human scroll.
- Output ASCII status indicators only (`[+]`, `[-]`, `[!]`, `[*]`).

**Interfaces:**
- `src/reel_watcher/browser_sync.py`:
  - `extract_reel_codes_from_html(html: str) -> list[str]`: Extracts unique shortcodes from Instagram reel/post anchor tags.
  - `get_active_instagram_tabs(cdp_base: str = "http://127.0.0.1:9222") -> list[dict]`: Queries CDP targets list and filters for active Instagram sessions.
  - `harvest_saved_reels_via_cdp(cdp_base: str = "http://127.0.0.1:9222", target_collection: str = "all-posts", max_scrolls: int = 5, vault: Vault | None = None) -> list[dict]`:
    Discovers saved reels from the active tab, executes scrolls, extracts unique links, enqueues them into Vault if provided, and returns `[{"code": str, "url": str, "collection": str}]`.

**Steps:**
1. Write unit and integration tests in `tests/test_browser_sync.py`.
2. Run pytest to verify failures.
3. Implement `src/reel_watcher/browser_sync.py`.
4. Export public symbols in `src/reel_watcher/__init__.py`.
5. Run `pytest tests/test_browser_sync.py -v` to verify they pass.
6. Run full test suite (`pytest tests/ -v`).
7. Git add and commit with message "feat: implement Chrome CDP browser sync harvester".
8. Update `.superpowers/sdd/progress.md`, write report to `task-5-report.md`, and report status DONE.
