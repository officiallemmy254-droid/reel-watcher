# Task 8: Multi-Provider Vision & Synthesis Pipeline (`vision.py`, `study.py`)

**Working Directory:** `C:\Users\SIR\reel-watcher`

**Files to create:**
- `src/reel_watcher/vision.py`
- `src/reel_watcher/study.py`
- `tests/test_vision.py`
- `tests/test_study.py`

**Global Constraints:**
- Python 3.11+, cross-platform Windows / Linux / macOS
- Output ASCII status indicators only (`[+]`, `[-]`, `[!]`, `[*]`)
- Multi-provider vision client: Gemini 2.5 Flash, OpenRouter, Ollama, OpenAI, and Fake (for tests and offline mode)
- Robust JSON response extraction (stripping `<think>`, markdown fences ```json, etc.)
- Deterministic regex giveaway extraction combined with VLM analysis

**Interfaces:**
- `src/reel_watcher/vision.py`:
  - `VisionClient(provider: str = "gemini", api_key: str | None = None, model: str | None = None)`
  - `VisionClient.ask_contact_sheet(sheet_path: Path | str, context_prompt: str = "") -> dict`
- `src/reel_watcher/study.py`:
  - `parse_comment_words(*texts: str) -> list[str]`
  - `parse_giveaway(sources: list[tuple[str, str]], vlm_cta: dict | None = None) -> dict`
  - `analyze_video_study(video_path: Path | str, item: dict, meta: dict, work_dir: Path | str, vision: VisionClient, fast: bool = False) -> dict`
  - `analyze_carousel_study(slides: list[Path | str], item: dict, meta: dict, work_dir: Path | str, vision: VisionClient) -> dict`

**Steps:**
1. Write unit and integration tests in `tests/test_vision.py` and `tests/test_study.py`.
2. Run pytest to verify failures.
3. Implement `src/reel_watcher/vision.py` and `src/reel_watcher/study.py`.
4. Export public symbols in `src/reel_watcher/__init__.py`.
5. Run `pytest tests/test_vision.py tests/test_study.py -v` to verify they pass.
6. Run full test suite (`pytest tests/ -v`).
7. Git add and commit with message "feat: implement multi-provider vision client and study pipeline".
8. Update `.superpowers/sdd/progress.md`, write report to `task-8-report.md`, and report status DONE.
