# Task 9: CLI Interface & Static Advice Library (`cli.py`, `advice_library.py`)

**Working Directory:** `C:\Users\SIR\reel-watcher`

**Files to create:**
- `src/reel_watcher/advice_library.py`
- `src/reel_watcher/cli.py`
- `tests/test_advice_library.py`
- `tests/test_cli.py`

**Global Constraints:**
- Python 3.11+, cross-platform Windows / Linux / macOS
- Output ASCII status indicators only (`[+]`, `[-]`, `[!]`, `[*]`)
- CLI entrypoint callable directly via `reel-watcher` or `python -m reel_watcher.cli`
- Advice HTML must be self-contained (zero external network dependencies, embedded CSS and JS with localStorage checkboxes and note persistence)

**Interfaces:**
- `src/reel_watcher/advice_library.py`:
  - `render_advice_html(studies: list[dict], out_path: Path | str, title: str = "Reel-Watcher Advice Library") -> Path`
- `src/reel_watcher/cli.py`:
  - `build_parser() -> argparse.ArgumentParser`
  - `main(argv: list[str] | None = None) -> int`

**Steps:**
1. Write unit and integration tests in `tests/test_advice_library.py` and `tests/test_cli.py`.
2. Run pytest to verify failures.
3. Implement `src/reel_watcher/advice_library.py` and `src/reel_watcher/cli.py`.
4. Export public symbols in `src/reel_watcher/__init__.py`.
5. Run `pytest tests/test_advice_library.py tests/test_cli.py -v` to verify they pass.
6. Run full test suite (`pytest tests/ -v`).
7. Git add and commit with message "feat: implement CLI dispatcher and static advice HTML generator".
8. Update `.superpowers/sdd/progress.md`, write report to `task-9-report.md`, and report status DONE.
