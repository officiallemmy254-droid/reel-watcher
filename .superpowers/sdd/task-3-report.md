# Task 3 Report: Media Utilities & Scene Cut Engine (`media.py`)

**Status:** DONE  
**Timestamp:** 2026-10-06T05:28:00Z  
**Commit:** `88bb6f2`  
**Working Directory:** `C:\Users\SIR\reel-watcher`

## 1. Overview
Implemented the media inspection, shot cut boundary detection, URL normalization, and intelligent frame sampling engine for `reel-watcher`. The system interfaces with system FFmpeg and FFprobe binaries via clean, error-tolerant subprocess execution with informative stderr snippet reporting. It enforces ASCII status indicators and cross-platform compatibility across Windows, macOS, and Linux.

## 2. Deliverables Created & Modified
- `src/reel_watcher/media.py`:
  - `preflight() -> str`: Inspects system `PATH` for `ffmpeg` and `ffprobe` using `shutil.which`. Returns an empty string if both tools are present, or helpful installation commands for Windows (`winget`), macOS (`brew`), and Linux (`apt`).
  - `id_from_url(url: str) -> str | None`: Parses URLs across Instagram Reels (`ig_<code>`), TikTok (`tt_<code>`), and YouTube Shorts (`yt_<code>`) into canonical prefixed identifiers. Preserves already normalized identifiers and safely returns `None` on unsupported or empty URLs.
  - `probe(path: str | Path) -> dict`: Executes `ffprobe` to extract video stream dimensions (`width`, `height`), frame rate (`fps`), duration in seconds (`duration`), and whether audio is present (`has_audio`).
  - `detect_cuts(video: str | Path, duration: float, threshold: float = 0.30) -> list[float]`: Uses ffmpeg `select='gt(scene,0.30)',showinfo` to accurately identify scene transition cuts, filtering and deduplicating timestamps within `0.0 < t < duration`.
  - `pick_frame_times(cuts: list[float], duration: float, fast: bool = False, min_spacing: float | None = None) -> list[float]`: Implements prioritized hook sampling:
    - Standard mode: Densely samples hook frames at $t \in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]\text{s}$ plus post-cut transition frames ($c + 0.15\text{s}$) with minimum 0.3s spacing deduplication.
    - Fast mode: Samples sparser hook frames at $t \in [0.0, 1.0, 2.0]\text{s}$ with 1.0s minimum spacing to minimize multimodal LLM latency.
    - Bounds checking: Guarantees candidate timestamps are strictly within video duration ($t < \text{duration}$) and returns `[]` on zero or negative duration.
- `src/reel_watcher/__init__.py`: Exported `detect_cuts`, `id_from_url`, `pick_frame_times`, `preflight`, and `probe`.
- `tests/test_media.py`: 18 comprehensive test cases covering URL parsing, mocked preflight/probe/cut detection, spacing deduplication, fast mode, and live FFmpeg/FFprobe integration on the host system.
- `.superpowers/sdd/progress.md`: Updated Task 3 progress ledger with commit hash `88bb6f2`.

## 3. Test-Driven Verification (TDD)
1. **Red Phase (Initial Failure):**
   - Executed `pytest tests/test_media.py -v`.
   - Result: Failed as expected with `ModuleNotFoundError: No module named 'reel_watcher.media'`.
2. **Green Phase (Implementation & Verification):**
   - Implemented `src/reel_watcher/media.py` and exported utilities in `src/reel_watcher/__init__.py`.
   - Executed `pytest tests/test_media.py -v`.
   - Result: All 18 unit and integration tests passed in 1.00s.
3. **Full Test Suite Verification:**
   - Executed `pytest -v`.
   - Result: All 32 tests passed across configuration, vault persistence, and media processing modules in 2.33s (100% pass rate).

## 4. Git Commit
Committed with message:
`feat: implement media probing, scene cut detection, and hook time sampling`  
Commit Hash: `88bb6f2`
