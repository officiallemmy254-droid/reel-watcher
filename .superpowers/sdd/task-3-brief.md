# Task 3: Media Utilities & Scene Cut Engine (`media.py`)

**Working Directory:** `C:\Users\SIR\reel-watcher`

**Files to create:**
- `src/reel_watcher/media.py`
- `tests/test_media.py`

**Global Constraints:**
- Python 3.11+, cross-platform Windows / Linux / macOS
- Clean subprocess invocation (handling errors with stderr snippets)
- Uses Windows ffmpeg and ffprobe on PATH
- Output ASCII status indicators only (`[+]`, `[-]`, `[!]`, `[*]`)

**Interfaces:**
- Produces:
  - `preflight() -> str`: Empty string if ffmpeg/ffprobe exist, else install instructions.
  - `id_from_url(url: str) -> str | None`: Parses Instagram, TikTok, and YouTube Shorts URLs into normalized identifiers (`ig_<code>`, `tt_<code>`, `yt_<code>`).
  - `probe(path: str | Path) -> dict`: Returns `{"duration": float, "width": int, "height": int, "fps": float, "has_audio": bool}`.
  - `detect_cuts(video: str | Path, duration: float, threshold: float = 0.30) -> list[float]`: Uses ffmpeg `select='gt(scene,0.30)',showinfo` to detect shot cuts.
  - `pick_frame_times(cuts: list[float], duration: float, fast: bool = False) -> list[float]`: Samples hook frames ($t \in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]\text{s}$) plus post-cut frames ($c + 0.15\text{s}$) with minimum spacing.

**Steps:**
1. Write tests in `tests/test_media.py` testing `id_from_url`, `pick_frame_times`, `preflight`, and mocked `probe` / `detect_cuts`.
2. Run `pytest tests/test_media.py -v` to verify it fails (`ModuleNotFoundError`).
3. Implement `src/reel_watcher/media.py`.
4. Run `pytest tests/test_media.py -v` to verify all tests pass.
5. Run full test suite (`pytest tests/ -v`).
6. Commit with message "feat: implement media probing, scene cut detection, and hook time sampling".
7. Update `.superpowers/sdd/progress.md`, write report to `task-3-report.md`, and report status DONE.
