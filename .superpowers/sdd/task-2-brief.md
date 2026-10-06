# Task 2: Vault State Storage & Persistence Engine (`db.py`)

**Working Directory:** `C:\Users\SIR\reel-watcher`

**Files to create:**
- `src/reel_watcher/db.py`
- `tests/test_db.py`

**Global Constraints:**
- Python 3.11+, sqlite3 standard library
- Thread-safe / connection-safe context managers
- Windows file path safety (utf-8 encoding, Path objects)
- Output ASCII status indicators only (`[+]`, `[-]`, `[!]`, `[*]`)

**Interfaces:**
- Produces `Vault` class with:
  - `__init__(db_path: Path, out_root: Path)`
  - `init_db()`
  - `enqueue_url(url: str, collection: str = "") -> bool` (deduplicates by shortcode)
  - `get_pending_urls(limit: int = 50) -> list[dict]`
  - `save_study(data: dict) -> None` (writes to DB, writes `study/<code>.json`, appends to `study_index.jsonl`, updates queue status)
  - `get_study(code: str) -> dict | None`
  - `list_studies(limit: int = 100, query: str = "") -> list[dict]`

**Steps:**
1. Write tests in `tests/test_db.py` covering all CRUD operations, deduplication, search querying, and JSON/JSONL sync.
2. Run `pytest tests/test_db.py -v` to verify it fails (`ModuleNotFoundError`).
3. Implement `src/reel_watcher/db.py`.
4. Run `pytest tests/test_db.py -v` to verify all tests pass.
5. Commit with message "feat: implement SQLite vault and index persistence engine".
6. Write full report to `C:\Users\SIR\reel-watcher\.superpowers\sdd\task-2-report.md` and report status DONE.
