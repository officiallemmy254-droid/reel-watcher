"""Vault State Storage and Persistence Engine for Reel-Watcher."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Generator
from urllib.parse import urlparse

from reel_watcher.config import format_status, get_status_indicator


def extract_shortcode(url: str) -> str:
    """Extract video shortcode/identifier from reel, tiktok, or shorts URLs.

    Supports:
    - Instagram: /reel/CODE, /reels/CODE, /p/CODE, /share/reel/CODE
    - YouTube Shorts: /shorts/CODE, youtu.be/CODE
    - TikTok: /@user/video/CODE, /v/CODE, vm.tiktok.com/CODE
    - Raw shortcode string fallback
    """
    cleaned = url.strip()
    if not cleaned:
        return ""

    # If already a simple shortcode (no url schema or path separator)
    if "://" not in cleaned and "/" not in cleaned:
        return cleaned

    # Instagram formats
    ig_match = re.search(
        r"(?:instagram\.com/(?:reel|reels|p|share/reel)/)([A-Za-z0-9_-]+)",
        cleaned,
    )
    if ig_match:
        return ig_match.group(1)

    # YouTube Shorts formats
    yt_match = re.search(
        r"(?:youtube\.com/shorts/|youtu\.be/)([A-Za-z0-9_-]+)",
        cleaned,
    )
    if yt_match:
        return yt_match.group(1)

    # TikTok formats
    tt_match = re.search(
        r"(?:tiktok\.com/@[^/]+/video/|tiktok\.com/v/|vm\.tiktok\.com/)([A-Za-z0-9_-]+)",
        cleaned,
    )
    if tt_match:
        return tt_match.group(1)

    # Generic URL path fallback: last non-empty segment before query params
    parsed = urlparse(cleaned)
    path_segments = [seg for seg in parsed.path.split("/") if seg]
    if path_segments:
        return path_segments[-1]

    return cleaned


class Vault:
    """SQLite vault and index persistence engine."""

    def __init__(self, db_path: Path | str, out_root: Path | str) -> None:
        """Initialize Vault instance with SQLite DB path and output root folder."""
        self.db_path = Path(db_path)
        self.out_root = Path(out_root)
        self.study_dir = self.out_root / "study"
        self.index_file = self.out_root / "study_index.jsonl"
        self.init_db()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provide a thread-safe SQLite connection context with WAL mode enabled."""
        if self.db_path.parent:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """Initialize SQLite database tables, indexes, and directory structure."""
        if self.db_path.parent:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.study_dir.mkdir(parents=True, exist_ok=True)

        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    shortcode TEXT NOT NULL UNIQUE,
                    collection TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_queue_status ON queue (status);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_queue_shortcode ON queue (shortcode);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS studies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shortcode TEXT NOT NULL UNIQUE,
                    url TEXT DEFAULT '',
                    collection TEXT DEFAULT '',
                    title TEXT DEFAULT '',
                    author TEXT DEFAULT '',
                    hook_text TEXT DEFAULT '',
                    summary TEXT DEFAULT '',
                    framework TEXT DEFAULT '',
                    score REAL DEFAULT 0.0,
                    data_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_studies_shortcode ON studies (shortcode);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_studies_title ON studies (title);
                """
            )

    def enqueue_url(self, url: str, collection: str = "") -> bool:
        """Enqueue a reel URL deduplicated by its extracted shortcode.

        Returns True if inserted into the queue, or False if already queued or studied.
        """
        shortcode = extract_shortcode(url)
        if not shortcode:
            return False

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM queue WHERE shortcode = ?", (shortcode,))
            if cursor.fetchone() is not None:
                return False

            cursor.execute("SELECT 1 FROM studies WHERE shortcode = ?", (shortcode,))
            if cursor.fetchone() is not None:
                return False

            cursor.execute(
                """
                INSERT INTO queue (url, shortcode, collection, status, added_at, updated_at)
                VALUES (?, ?, ?, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (url.strip(), shortcode, collection.strip()),
            )
            return True

    def get_pending_urls(self, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve pending items from the queue up to limit."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, url, shortcode, collection, status, added_at, updated_at
                FROM queue
                WHERE status = 'pending'
                ORDER BY id ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def update_queue_status(self, shortcode: str, status: str) -> bool:
        """Update queue status for a given shortcode (e.g. 'processing', 'completed', 'failed')."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE queue
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE shortcode = ?
                """,
                (status, shortcode),
            )
            return cursor.rowcount > 0

    def get_queue_item(self, shortcode: str) -> dict[str, Any] | None:
        """Get queue item metadata by shortcode."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, url, shortcode, collection, status, added_at, updated_at
                FROM queue
                WHERE shortcode = ?
                """,
                (shortcode,),
            )
            row = cursor.fetchone()
            return dict(row) if row is not None else None

    def save_study(self, data: dict[str, Any]) -> None:
        """Save a study record: writes to DB, saves study/<code>.json, appends to study_index.jsonl, and completes queue entry."""
        code = data.get("code") or data.get("shortcode")
        if not code and "url" in data:
            code = extract_shortcode(str(data["url"]))

        if not code:
            raise ValueError("Study data must contain 'code', 'shortcode', or a valid 'url'.")

        code = str(code)
        normalized = dict(data)
        normalized["code"] = code
        normalized["shortcode"] = code

        title = str(normalized.get("title", ""))
        author = str(normalized.get("author", ""))
        hook_text = str(normalized.get("hook_text", ""))
        summary = str(normalized.get("summary", ""))
        framework = str(normalized.get("framework", ""))
        raw_score = normalized.get("score", 0.0)
        try:
            score = float(raw_score) if raw_score is not None else 0.0
        except (ValueError, TypeError):
            score = 0.0
        url = str(normalized.get("url", ""))
        collection = str(normalized.get("collection", ""))

        json_blob = json.dumps(normalized, ensure_ascii=False)

        # 1. Database persistence and queue update
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO studies (
                    shortcode, url, collection, title, author, hook_text, summary, framework, score, data_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(shortcode) DO UPDATE SET
                    url = excluded.url,
                    collection = excluded.collection,
                    title = excluded.title,
                    author = excluded.author,
                    hook_text = excluded.hook_text,
                    summary = excluded.summary,
                    framework = excluded.framework,
                    score = excluded.score,
                    data_json = excluded.data_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (code, url, collection, title, author, hook_text, summary, framework, score, json_blob),
            )
            cursor.execute(
                """
                UPDATE queue
                SET status = 'completed', updated_at = CURRENT_TIMESTAMP
                WHERE shortcode = ?
                """,
                (code,),
            )

        # 2. File persistence: study/<code>.json
        self.study_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.study_dir / f"{code}.json"
        file_path.write_text(
            json.dumps(normalized, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # 3. File persistence: append to study_index.jsonl
        if self.index_file.parent:
            self.index_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.index_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(normalized, ensure_ascii=False) + "\n")

    def get_study(self, code: str) -> dict[str, Any] | None:
        """Retrieve a study by its shortcode from DB, with fallback to filesystem."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT data_json FROM studies WHERE shortcode = ?", (code,))
            row = cursor.fetchone()
            if row is not None:
                try:
                    return json.loads(row["data_json"])
                except Exception:
                    pass

        # Fallback to file on disk
        file_path = self.study_dir / f"{code}.json"
        if file_path.is_file():
            try:
                return json.loads(file_path.read_text(encoding="utf-8"))
            except Exception:
                return None

        return None

    def list_studies(self, limit: int = 100, query: str = "") -> list[dict[str, Any]]:
        """List studies matching optional search query, ordered by updated_at descending."""
        with self._connection() as conn:
            cursor = conn.cursor()
            if query.strip():
                param = f"%{query.strip()}%"
                cursor.execute(
                    """
                    SELECT data_json FROM studies
                    WHERE shortcode LIKE ?
                       OR title LIKE ?
                       OR author LIKE ?
                       OR hook_text LIKE ?
                       OR summary LIKE ?
                       OR framework LIKE ?
                       OR collection LIKE ?
                       OR data_json LIKE ?
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (param, param, param, param, param, param, param, param, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT data_json FROM studies
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )

            rows = cursor.fetchall()
            results: list[dict[str, Any]] = []
            for row in rows:
                try:
                    results.append(json.loads(row["data_json"]))
                except Exception:
                    continue
            return results
