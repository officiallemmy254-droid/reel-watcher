# Creator Intelligence Scraping & Saved Reels Processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a robust, end-to-end creator profile scraper with baseline/outlier calculation, competitive dossier synthesis, and a unified pipeline for both Instagram in-app saved collections and local video folder batch processing.

**Architecture:**
1. **Core Ingestion:** Leverages existing CDP browser session (and Playwright CDP connection / fallback `yt-dlp` flat-playlist) to harvest creator profiles (`/reels/`) and user saved collections without bot detection.
2. **Signal Filtering:** Computes median views, likes, and engagement baselines to tag reels with an `outlier_multiplier`, allowing selective deep deconstruction of top 10–20% performers.
3. **Synthesis Engine:** Multi-modal analysis via Gemini Flash on contact sheets, Whisper transcripts, and scene cuts; aggregates reel studies into a comprehensive Creator Dossier (hooks, funnels, formats).
4. **Local & Saved Batching:** Adds single-command automated workflows for synchronizing Instagram saved collections and batch ingesting local video folders with vision-first synthesis when social captions are absent.

**Tech Stack:** Python 3.11+, SQLite (WAL mode), FFmpeg / ffprobe, yt-dlp, Playwright / CDP WebSockets, Pillow, NumPy, Gemini 2.5 Flash / OpenRouter.

## Global Constraints
- Windows CLI safety: strictly use ASCII status indicators (`[+]`, `[-]`, `[*]`, `[!]`). No raw emojis in stdout/stderr.
- Environment secrets loaded via `reel_watcher.config.load_config()`.
- Zero unnecessary bloat: avoid local heavy PyTorch/Whisper models; rely on Gemini Flash / cloud APIs for speech and OCR.
- Strict backwards compatibility: existing `reel-watcher` commands (`harvest`, `download`, `study`, `serve`) must remain fully operational.

---

### Task 1: Fix Existing Harvester & CLI Test Regressions

**Files:**
- Modify: `src/reel_watcher/browser_sync.py`
- Modify: `src/reel_watcher/cli.py`
- Test: `tests/test_browser_sync.py`, `tests/test_cli.py`

**Interfaces:**
- `harvest_saved_reels_via_cdp`: Ensure navigation logic uses `chosen_tab.get("url")` without consuming mock evaluate responses unexpectedly, and only navigates if explicitly needed.
- `cmd_harvest`: Print harvested reel identifiers or count to satisfy CLI output assertions.

- [x] **Step 1: Inspect failing tests in `tests/test_browser_sync.py` and `tests/test_cli.py`**
- [x] **Step 2: Update `browser_sync.py` and `cli.py` to fix mock evaluation alignment and output**
- [x] **Step 3: Run pytest on `test_browser_sync.py` and `test_cli.py` to verify green status**

---

### Task 2: Database Schema & Vault Extension for Creators and Local Media

**Files:**
- Modify: `src/reel_watcher/db.py`
- Test: `tests/test_db_creator.py`

**Interfaces:**
- `Vault.init_db`: Create `creators` table (`id`, `handle`, `platform`, `follower_count`, `median_views`, `mean_likes`, `profile_url`, `metadata_json`, `created_at`, `updated_at`).
- `Vault.upsert_creator(handle: str, platform: str, follower_count: int, median_views: int, mean_likes: int, metadata: dict) -> int`
- `Vault.get_creator(handle: str, platform: str) -> dict | None`
- `Vault.enqueue_url`: Support optional `creator_id: int | None`, `views: int | None`, `likes: int | None`, `outlier_multiplier: float | None`.
- `Vault.record_study`: Support optional `creator_id: int | None`, `views: int | None`, `outlier_multiplier: float | None`.
- `Vault.get_studies_by_creator(creator_id: int) -> list[dict]`

- [x] **Step 1: Write unit tests in `tests/test_db_creator.py` covering creator table creation, upsert, query, and linking to studies**
- [x] **Step 2: Implement schema migrations and helper methods in `src/reel_watcher/db.py`**
- [x] **Step 3: Run pytest on `tests/test_db_creator.py` and ensure all pass**

---

### Task 3: Creator Profile Harvester & Outlier Scoring

**Files:**
- Create: `src/reel_watcher/creator.py`
- Test: `tests/test_creator.py`

**Interfaces:**
- `CreatorPost`: Dataclass containing `shortcode`, `url`, `caption`, `views`, `likes`, `comments`, `posted_at`, `outlier_multiplier`.
- `CreatorStats`: Dataclass containing `handle`, `platform`, `total_posts`, `median_views`, `mean_likes`, `outlier_threshold`.
- `calculate_creator_baselines(posts: list[CreatorPost]) -> CreatorStats`
- `harvest_creator_reels(handle: str, platform: str = "instagram", max_posts: int = 50, cdp_base: str = "http://127.0.0.1:9222", use_playwright: bool = True) -> list[CreatorPost]`
- `filter_outliers(posts: list[CreatorPost], stats: CreatorStats, min_multiplier: float = 1.5, top_n: int = 10) -> list[CreatorPost]`

- [x] **Step 1: Write unit tests in `tests/test_creator.py` for baseline calculation, outlier filtering, and profile scraping mock**
- [x] **Step 2: Implement `src/reel_watcher/creator.py` with baseline statistics and dual scraper engine (Playwright CDP / raw CDP / yt-dlp fallback)**
- [x] **Step 3: Run pytest on `tests/test_creator.py`**

---

### Task 4: Creator Intelligence Dossier Synthesis

**Files:**
- Create: `src/reel_watcher/dossier.py`
- Test: `tests/test_dossier.py`

**Interfaces:**
- `synthesize_creator_dossier(handle: str, vault: Vault, vision: VisionClient | None = None) -> dict[str, Any]`
- `render_dossier_markdown(dossier_data: dict[str, Any]) -> str`
- Aggregates:
  - Top 3–5 Hook Formulas used by the creator
  - Funnel & ManyChat Trigger keywords and offers
  - Editing & Pacing Archetypes (cuts/sec, average video duration)
  - Reusable Gwelix Script Templates derived from top outliers

- [x] **Step 1: Write unit tests in `tests/test_dossier.py` verifying aggregation, formatting, and markdown report generation**
- [x] **Step 2: Implement `src/reel_watcher/dossier.py`**
- [x] **Step 3: Run pytest on `tests/test_dossier.py`**

---

### Task 5: Unified Saved Collections Sync & Local Folder Ingestion Engine

**Files:**
- Create: `src/reel_watcher/saved_processor.py`
- Modify: `src/reel_watcher/study.py` (vision-first fallback for raw videos with missing captions)
- Test: `tests/test_saved_processor.py`

**Interfaces:**
- `sync_saved_collection(collection: str, max_scrolls: int, auto_download: bool, auto_study: bool, vault: Vault, cdp_base: str) -> dict[str, int]`
  - Handles dead/private reels gracefully (`status="unavailable"`)
- `ingest_local_folder(folder_path: Path | str, collection: str, recursive: bool, vault: Vault, auto_study: bool) -> list[dict[str, Any]]`
  - Scans for `.mp4`, `.mov`, `.webm`, `.mkv`
  - Hashes file stem or content to prevent duplicates
  - Enqueues into Vault queue or directly triggers study
- `study.py` adaptation:
  - Handle missing caption / author gracefully: generate study prompt emphasizing visual on-screen text, audio transcript, and detected branding.

- [x] **Step 1: Write unit tests in `tests/test_saved_processor.py` for local folder batch scanning and saved collection sync pipeline**
- [x] **Step 2: Implement `src/reel_watcher/saved_processor.py`**
- [x] **Step 3: Update `src/reel_watcher/study.py` for vision-first metadata fallback**
- [x] **Step 4: Run pytest on `tests/test_saved_processor.py` and `tests/test_study.py`**

---

### Task 6: CLI Subcommand Integration (`cli.py`)

**Files:**
- Modify: `src/reel_watcher/cli.py`
- Test: `tests/test_cli_creator.py`

**Subcommands Added:**
- `reel-watcher creator scan <handle> [--limit 50] [--platform instagram]`: Scan profile and show baseline stats & top outliers.
- `reel-watcher creator harvest <handle> [--top 10] [--min-multiplier 1.5] [--auto-study]`: Harvest and optionally download & study top outliers.
- `reel-watcher creator dossier <handle> [--out-file path]`: Generate complete dossier markdown & JSON report.
- `reel-watcher sync-saved [--collection name] [--max-scrolls 5] [--auto-study]`: Single-command end-to-end sync of Instagram saved posts.
- `reel-watcher ingest-folder <directory> [--collection name] [--recursive] [--auto-study]`: Batch process local videos.

- [x] **Step 1: Write CLI argument and execution tests in `tests/test_cli_creator.py`**
- [x] **Step 2: Wire subcommands in `src/reel_watcher/cli.py`**
- [x] **Step 3: Run pytest on CLI tests**

---

### Task 7: Full System Verification

- [x] **Step 1: Run complete pytest suite across all modules**
- [x] **Step 2: Verify `preflight` tool check passes**
- [x] **Step 3: Verify all CLI commands execute cleanly with proper ASCII bracket outputs (`[+]`, `[-]`, `[*]`, `[!]`)**
