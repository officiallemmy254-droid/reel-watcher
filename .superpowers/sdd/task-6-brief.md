# Task 6: Frame Deduplication, Contact-Sheet Generation & Signal Extraction (`signal.py`, `ocr.py`)

**Working Directory:** `C:\Users\SIR\reel-watcher`

**Files to create:**
- `src/reel_watcher/signal.py`
- `src/reel_watcher/ocr.py`
- `tests/test_signal.py`

**Global Constraints:**
- Python 3.11+, cross-platform Windows / Linux / macOS
- Uses Pillow (`PIL`) and `numpy` for image manipulation and perceptual hashing
- Output ASCII status indicators only (`[+]`, `[-]`, `[!]`, `[*]`)
- Contact sheet must generate a grid of up to 9 tiles (each 512px max) with burned-in yellow label `#n  <timestamp>`

**Interfaces:**
- `src/reel_watcher/signal.py`:
  - `extract_frame_jpg(video: Path | str, time_sec: float, dest: Path | str) -> Path`
  - `dhash_bits(path: Path | str, size: int = 8) -> int`
  - `text_changed(a: str, b: str) -> bool`
  - `dedupe_frames(hashes: list[int], texts: list[str], thr: int = 9, cap: int = 9) -> tuple[list[int], list[int]]`
  - `make_contact_sheet(tiles: list[tuple[Path | str, str]], dest: Path | str, tile_px: int = 512, cols: int = 3) -> Path`
- `src/reel_watcher/ocr.py`:
  - `ocr_image(path: Path | str) -> str`: Cross-platform OCR extraction using RapidOCR / Tesseract or returning empty string when neither is installed.

**Steps:**
1. Write tests in `tests/test_signal.py`.
2. Run pytest to verify failures.
3. Implement `src/reel_watcher/signal.py` and `src/reel_watcher/ocr.py`.
4. Export public symbols in `src/reel_watcher/__init__.py`.
5. Run `pytest tests/test_signal.py -v` to verify they pass.
6. Run full test suite (`pytest tests/ -v`).
7. Git add and commit with message "feat: implement perceptual frame deduplication and labeled contact-sheet generator".
8. Update `.superpowers/sdd/progress.md`, write report to `task-6-report.md`, and report status DONE.
