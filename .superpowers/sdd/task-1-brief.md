# Task 1: Repository Scaffolding, Configuration & Environment Loader

**Working Directory:** `C:\Users\SIR\reel-watcher`

**Files to create:**
- `pyproject.toml`
- `.gitignore`
- `README.md`
- `AGENTS.md`
- `src/reel_watcher/__init__.py`
- `src/reel_watcher/config.py`
- `tests/test_config.py`

**Global Constraints:**
- Python 3.11+, uv compatible
- Cross-platform Windows/Linux/macOS
- Output ASCII indicators only (`[+]`, `[-]`, `[!]`, `[*]`)
- Reads OPENROUTER_API_KEY and GEMINI_API_KEY from environment or .env

**Interfaces:**
- Produces `Config` dataclass and `load_config(env_path: Path | None = None) -> Config`

**Steps:**
1. Write failing test in `tests/test_config.py` testing `load_config`
2. Run test using `pytest tests/test_config.py -v` (verify FAIL)
3. Implement `pyproject.toml`, `.gitignore`, `README.md`, `AGENTS.md`, `src/reel_watcher/__init__.py`, `src/reel_watcher/config.py`
4. Run `pytest tests/test_config.py -v` (verify PASS)
5. Commit changes: `git add . && git commit -m "feat: scaffold universal reel-watcher repository and configuration loader"`
