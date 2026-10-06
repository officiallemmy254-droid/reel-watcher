# Reel-Watcher Project Invariants (Tier 1)

## 1. Project Purpose & Scope
Reel-Watcher is a universal short-form video intelligence engine. It harvests, archives, deconstructs scene transitions, extracts OCR signals and audio transcripts, and synthesizes viral hook playbooks from Instagram Reels, TikTok, and YouTube Shorts.

## 2. Technical Invariants
1. **ASCII Output Safety:** On Windows and all CLI environments, console output must strictly use ASCII bracket indicators:
   - `[+]` Success / Completed
   - `[-]` Failure / Error
   - `[*]` Information / Progress
   - `[!]` Warning / Alert
   Never emit raw Unicode emojis or non-ASCII characters to standard output.
2. **Environment & Secrets:**
   - Secrets are loaded via `reel_watcher.config.load_config()` from `.env` or system environment variables.
   - Core API keys: `OPENROUTER_API_KEY` and `GEMINI_API_KEY`.
3. **Storage & Vault Architecture:**
   - All raw downloads, scene cuts, contact sheets, and metadata reside under `vault_dir` (default: `vault/`).
   - SQLite state storage (`db_path`, default: `vault/reels.db`) manages reel records, processing statuses, and synthesis reports.
4. **Testing & Code Quality:**
   - All modules must be tested via pytest under `tests/`.
   - Python 3.11+ type annotations and dataclasses/pydantic models across all boundaries.
