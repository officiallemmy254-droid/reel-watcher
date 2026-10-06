# Task 10: Interactive Web Playbook Dashboard (`web/server.py`, `web/static/`)

**Working Directory:** `C:\Users\SIR\reel-watcher`

**Files to create:**
- `src/reel_watcher/web/__init__.py`
- `src/reel_watcher/web/server.py`
- `src/reel_watcher/web/static/index.html`
- `tests/test_web.py`
- Modify `src/reel_watcher/cli.py` to support `reel-watcher serve --port 8440`

**Global Constraints:**
- Python 3.11+, cross-platform Windows / Linux / macOS
- FastAPI + Uvicorn
- Path traversal protection on static/media routes
- Output ASCII status indicators only (`[+]`, `[-]`, `[!]`, `[*]`)
- Clean, responsive dark-mode Playbook UI with zero external CDN dependencies

**Interfaces:**
- `src/reel_watcher/web/server.py`:
  - `create_app(vault: Vault | None = None) -> FastAPI`
  - `run_server(port: int = 8440, host: str = "127.0.0.1", vault: Vault | None = None)`
  - Endpoints:
    - `GET /` -> static index.html
    - `GET /api/studies` -> list with query, format, and giveaway filters
    - `GET /api/studies/{code}` -> single study record
    - `POST /api/enqueue` -> enqueues new URL
    - `GET /api/stats` -> summary metrics

**Steps:**
1. Write unit and integration tests in `tests/test_web.py` using `fastapi.testclient.TestClient`.
2. Run pytest to verify failures.
3. Implement `src/reel_watcher/web/server.py` and `src/reel_watcher/web/static/index.html`.
4. Connect `serve` subcommand in `src/reel_watcher/cli.py`.
5. Export public symbols in `src/reel_watcher/__init__.py`.
6. Run `pytest tests/test_web.py -v` to verify they pass.
7. Run full test suite (`pytest tests/ -v`).
8. Git add and commit with message "feat: implement interactive Playbook Web Dashboard and API".
9. Update `.superpowers/sdd/progress.md`, write report to `task-10-report.md`, and report status DONE.
