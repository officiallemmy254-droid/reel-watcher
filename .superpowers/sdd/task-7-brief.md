# Task 7: Audio & Speech Transcription Engine (`audio.py`)

**Working Directory:** `C:\Users\SIR\reel-watcher`

**Files to create:**
- `src/reel_watcher/audio.py`
- `tests/test_audio.py`

**Global Constraints:**
- Python 3.11+, cross-platform Windows / Linux / macOS
- Uses ffmpeg to extract mono 16kHz audio for whisper
- Multi-engine fallback: `faster-whisper` -> `openai-whisper` -> `mlx-whisper` -> graceful empty fallback with warning
- Output ASCII status indicators only (`[+]`, `[-]`, `[!]`, `[*]`)
- Returns word-level timestamps (`[{"w": str, "s": float, "e": float}]`) and segment timestamps

**Interfaces:**
- `src/reel_watcher/audio.py`:
  - `extract_audio(video_path: Path | str, out_wav: Path | str) -> Path`
  - `normalize_transcript_segments(segments: list[dict], language: str = "en") -> dict`
  - `transcribe(video_or_audio: Path | str, backend: str = "auto", model_name: str = "base") -> dict`
  - `non_speech_energy_heuristic(video_or_audio: Path | str, words: list[dict], duration: float) -> dict`

**Steps:**
1. Write unit and integration tests in `tests/test_audio.py`.
2. Run pytest to verify failures.
3. Implement `src/reel_watcher/audio.py`.
4. Export public symbols in `src/reel_watcher/__init__.py`.
5. Run `pytest tests/test_audio.py -v` to verify they pass.
6. Run full test suite (`pytest tests/ -v`).
7. Git add and commit with message "feat: implement speech transcription engine with word timestamps".
8. Update `.superpowers/sdd/progress.md`, write report to `task-7-report.md`, and report status DONE.
