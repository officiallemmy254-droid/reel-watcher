# Task 6 Report: Frame Deduplication, Contact-Sheet Generation & Signal Extraction (`signal.py`, `ocr.py`)

**Status:** DONE  
**Timestamp:** 2026-10-06T05:51:00Z  
**Commit:** `aae2b34`  
**Working Directory:** `C:\Users\SIR\reel-watcher`

## 1. Overview
Implemented the perceptual frame deduplication, contact-sheet generation, and signal/OCR extraction engines for `reel-watcher`. The engine extracts high-quality candidate frames via FFmpeg with sub-second precision, calculates 64-bit difference hashes (`dHash`) using Pillow and NumPy, detects semantic on-screen text mutations, deduplicates sequential frames while preserving textual transitions, uniformly caps frames to 9 tiles, generates dark-themed 3x3 contact sheets with burned-in yellow label badges (`#n  <timestamp>`), and provides cross-platform OCR extraction with graceful multi-engine fallback.

## 2. Deliverables Created & Modified
- `src/reel_watcher/signal.py`:
  - `extract_frame_jpg(video: Path | str, time_sec: float, dest: Path | str) -> Path`: Executes fast, accurate FFmpeg input-seeking (`-ss`, `-frames:v 1`, `-q:v 2`) to extract a pristine JPEG frame from a video file at arbitrary sub-second timestamps.
  - `dhash_bits(path: Path | str, size: int = 8) -> int`: Computes perceptual horizontal gradient difference hash (dHash) as a 64-bit integer by resizing images to `(size + 1, size)` in grayscale and comparing adjacent horizontal pixel luminances with NumPy.
  - `text_changed(a: str, b: str, threshold: float = 0.8) -> bool`: Normalizes strings and computes sequence similarity ratios via `difflib.SequenceMatcher` to detect meaningful on-screen text transitions (captions, slide headers) while filtering out minor OCR punctuation noise.
  - `dedupe_frames(hashes: list[int], texts: list[str], thr: int = 9, cap: int = 9) -> tuple[list[int], list[int]]`: Chronologically deduplicates candidate frames using Hamming distance (`(h1 ^ h2).bit_count()`) while retaining visually similar frames if OCR text changed. Uniformly downsamples retained frames to `cap` while strictly preserving initial hook frames and final frames.
  - `make_contact_sheet(tiles: list[tuple[Path | str, str]], dest: Path | str, tile_px: int = 512, cols: int = 3) -> Path`: Constructs an aesthetically balanced dark-themed grid of up to 9 tiles (max dimension 512px) with crisp, burned-in yellow label badges (`#n  <timestamp>`) backed by solid dark contrast rectangles.
- `src/reel_watcher/ocr.py`:
  - `ocr_image(path: Path | str) -> str`: Multi-backend OCR engine supporting RapidOCR (`rapidocr_onnxruntime`), PyTesseract, and system Tesseract CLI binary fallbacks. Gracefully returns empty string when no engine is installed or on execution exceptions.
- `src/reel_watcher/__init__.py`:
  - Exported `extract_frame_jpg`, `dhash_bits`, `text_changed`, `dedupe_frames`, `make_contact_sheet`, and `ocr_image` into public API package symbols.
- `tests/test_signal.py`:
  - 30 exhaustive unit and integration tests covering missing files, identical/distinct perceptual dHash, gradient inversions, text normalization and typos, visual deduplication, text-change overrides, capacity enforcement with boundary preservation, live and mocked FFmpeg frame extraction, contact sheet generation and yellow pixel verification, and OCR multi-engine mock/fallback behaviors.
- `.superpowers/sdd/progress.md`:
  - Updated progress ledger with Task 6 marked completed with commit `aae2b34`.

## 3. Test-Driven Verification (TDD)
1. **Red Phase (Initial Failure):**
   - Executed `pytest tests/test_signal.py`.
   - Verified failure due to `ImportError: cannot import name 'dedupe_frames' from 'reel_watcher'`.
2. **Green Phase (Implementation & Verification):**
   - Implemented `src/reel_watcher/ocr.py` and `src/reel_watcher/signal.py`.
   - Updated `src/reel_watcher/__init__.py` with public symbol exports.
   - Executed `pytest tests/test_signal.py -v`.
   - All 30 tests passed in 1.49s.
3. **Full Suite Regression Verification:**
   - Executed `pytest tests/ -v`.
   - All 102 test cases passed across configuration, vault database, media cut detector, downloader, export parser, browser sync, signal deduplication, contact sheet generation, and OCR in 3.80s (100% pass rate).

## 4. Git Commit
- Message: `feat: implement perceptual frame deduplication and labeled contact-sheet generator`
- Commit Hash: `aae2b34`
