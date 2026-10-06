"""Instagram Export Parser for Reel-Watcher (`ig_export.py`).

Parses Meta Accounts Center / Instagram data exports (JSON and HTML formats)
for saved posts and collections, extracting canonical URLs, shortcodes, and creator metadata.
"""

from __future__ import annotations

import csv
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from typing import Any

from reel_watcher.config import format_status
from reel_watcher.db import extract_shortcode


def _normalize_ig_url(raw_url: str) -> tuple[str, str] | None:
    """Extract canonical Instagram reel/post URL and shortcode.

    Returns:
        (canonical_url, shortcode) or None if not an Instagram post/reel URL.
    """
    if not raw_url or not isinstance(raw_url, str):
        return None

    cleaned = raw_url.strip()
    match = re.search(
        r"(?:instagram\.com/(?:reel|reels|p|share/reel|tv)/)([A-Za-z0-9_-]+)",
        cleaned,
        re.IGNORECASE,
    )
    if not match:
        return None

    shortcode = match.group(1)
    # Canonicalize to /reel/ format for reel-watcher
    canonical_url = f"https://www.instagram.com/reel/{shortcode}/"
    return canonical_url, shortcode


class _InstagramHTMLExportParser(HTMLParser):
    """HTML Parser for Instagram saved posts and saved collections exports."""

    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, Any]] = []
        self.current_collection = ""
        self.current_header_tag: str | None = None
        self.header_text = ""
        self.recent_texts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        tag_lower = tag.lower()

        if tag_lower in ("h1", "h2", "h3", "h4"):
            self.current_header_tag = tag_lower
            self.header_text = ""

        elif tag_lower == "a":
            href = attr_dict.get("href") or ""
            parsed = _normalize_ig_url(href)
            if parsed:
                canonical_url, shortcode = parsed
                # Find most recent potential creator username from preceding div/span text
                creator = ""
                for txt in reversed(self.recent_texts[-5:]):
                    clean_txt = txt.strip()
                    # Skip generic phrases
                    if clean_txt and not clean_txt.lower().startswith(("saved on", "instagram", "view")):
                        creator = clean_txt
                        break

                self.items.append({
                    "id": f"ig_{shortcode}",
                    "url": canonical_url,
                    "shortcode": shortcode,
                    "creator": creator,
                    "author": creator,
                    "collection": self.current_collection,
                    "timestamp": None,
                })

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower == self.current_header_tag:
            header_val = self.header_text.strip()
            if header_val and not header_val.lower().startswith("saved"):
                self.current_collection = header_val
            self.current_header_tag = None

    def handle_data(self, data: str) -> None:
        clean = data.strip()
        if clean:
            if self.current_header_tag is not None:
                self.header_text += " " + clean
            else:
                self.recent_texts.append(clean)
                if len(self.recent_texts) > 20:
                    self.recent_texts.pop(0)


def _parse_json_media_item(
    item: dict[str, Any],
    default_collection: str = "",
) -> dict[str, Any] | None:
    """Parse a single media entry from an Instagram JSON export structure."""
    if not isinstance(item, dict):
        return None

    # Title is usually creator username
    creator = str(item.get("title") or item.get("author") or item.get("creator") or "").strip()
    collection_name = str(item.get("collection") or default_collection).strip()
    timestamp = item.get("timestamp")
    url_candidate = ""

    # Check direct url / href keys
    if "url" in item and isinstance(item["url"], str):
        url_candidate = item["url"]
    elif "href" in item and isinstance(item["href"], str):
        url_candidate = item["href"]

    # Check string_map_data structure (standard Meta export)
    string_map = item.get("string_map_data")
    if isinstance(string_map, dict):
        for _, val_dict in string_map.items():
            if isinstance(val_dict, dict):
                if not url_candidate and "href" in val_dict and isinstance(val_dict["href"], str):
                    url_candidate = val_dict["href"]
                if timestamp is None and "timestamp" in val_dict:
                    timestamp = val_dict["timestamp"]

    parsed = _normalize_ig_url(url_candidate)
    if not parsed:
        return None

    canonical_url, shortcode = parsed
    return {
        "id": f"ig_{shortcode}",
        "url": canonical_url,
        "shortcode": shortcode,
        "creator": creator,
        "author": creator,
        "collection": collection_name,
        "timestamp": timestamp,
    }


def _parse_json_export(file_path: Path) -> list[dict[str, Any]]:
    """Parse Instagram JSON export file across various schema variations."""
    try:
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            return []
        data = json.loads(content)
    except Exception as exc:
        print(format_status("!", f"Failed to parse JSON in {file_path}: {exc}"), file=sys.stderr)
        return []

    items: list[dict[str, Any]] = []

    # Format 1: Root list of items
    if isinstance(data, list):
        for elem in data:
            if isinstance(elem, dict):
                # Could be a collection item or direct post
                if "media" in elem and isinstance(elem["media"], list):
                    coll_name = str(elem.get("title") or elem.get("name") or "")
                    for sub_elem in elem["media"]:
                        parsed = _parse_json_media_item(sub_elem, default_collection=coll_name)
                        if parsed:
                            items.append(parsed)
                else:
                    parsed = _parse_json_media_item(elem)
                    if parsed:
                        items.append(parsed)
        return items

    if not isinstance(data, dict):
        return []

    # Format 2: saved_saved_media (Standard Meta saved posts export)
    if "saved_saved_media" in data and isinstance(data["saved_saved_media"], list):
        for elem in data["saved_saved_media"]:
            parsed = _parse_json_media_item(elem)
            if parsed:
                items.append(parsed)

    # Format 3: saved_collections / saved_saved_collections (Saved collections export)
    for col_key in ("saved_collections", "saved_saved_collections"):
        if col_key in data and isinstance(data[col_key], list):
            for collection_block in data[col_key]:
                if isinstance(collection_block, dict):
                    coll_name = str(collection_block.get("title") or collection_block.get("name") or "")
                    media_list = collection_block.get("media") or collection_block.get("items") or []
                    if isinstance(media_list, list):
                        for sub_elem in media_list:
                            parsed = _parse_json_media_item(sub_elem, default_collection=coll_name)
                            if parsed:
                                items.append(parsed)

    # Format 4: saved_posts key
    if "saved_posts" in data and isinstance(data["saved_posts"], list):
        for elem in data["saved_posts"]:
            parsed = _parse_json_media_item(elem)
            if parsed:
                items.append(parsed)

    return items


def _parse_html_export(file_path: Path) -> list[dict[str, Any]]:
    """Parse Instagram HTML export file."""
    try:
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            return []
        parser = _InstagramHTMLExportParser()
        parser.feed(content)
        return parser.items
    except Exception as exc:
        print(format_status("!", f"Failed to parse HTML in {file_path}: {exc}"), file=sys.stderr)
        return []


def extract_urls_from_export(path: Path | str, collection: str = "") -> list[dict[str, Any]]:
    """Walk JSON or HTML export files extracting unique URLs with shortcodes and creator metadata.

    Args:
        path: File or directory path of the Instagram export.
        collection: Optional collection name filter (case-insensitive).

    Returns:
        List of dicts: [
            {
                "id": str,
                "url": str,
                "shortcode": str,
                "creator": str,
                "author": str,
                "collection": str,
                "timestamp": int | None,
            },
            ...
        ]
    """
    target = Path(path).resolve()
    if not target.exists():
        return []

    files_to_process: list[Path] = []
    if target.is_dir():
        for p in sorted(target.rglob("*")):
            if p.is_file() and p.suffix.lower() in (".json", ".html", ".htm"):
                files_to_process.append(p)
    elif target.is_file():
        files_to_process.append(target)

    all_items: list[dict[str, Any]] = []
    for fp in files_to_process:
        ext = fp.suffix.lower()
        if ext == ".json":
            all_items.extend(_parse_json_export(fp))
        elif ext in (".html", ".htm"):
            all_items.extend(_parse_html_export(fp))

    # Apply collection filter if specified
    filter_col = collection.strip().lower()
    if filter_col:
        all_items = [
            it for it in all_items
            if filter_col in it.get("collection", "").lower()
        ]

    # Deduplicate by shortcode
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for it in all_items:
        sc = it.get("shortcode", "")
        if sc and sc not in seen:
            seen.add(sc)
            deduped.append(it)

    return deduped


def export_to_tsv(
    input_files: list[Path | str],
    out_tsv: Path | str,
    collection: str = "",
) -> int:
    """Export extracted Instagram reel URLs and metadata from export files into a TSV file.

    Args:
        input_files: List of input export files or directories.
        out_tsv: Target TSV output path.
        collection: Optional collection filter string.

    Returns:
        Total count of unique rows exported (excluding header).
    """
    target_out = Path(out_tsv).resolve()
    target_out.parent.mkdir(parents=True, exist_ok=True)

    all_records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for inp in input_files:
        records = extract_urls_from_export(inp, collection=collection)
        for r in records:
            sc = r.get("shortcode", "")
            if sc and sc not in seen:
                seen.add(sc)
                all_records.append(r)

    with target_out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        # Header
        writer.writerow(["url", "shortcode", "creator", "collection", "timestamp"])
        for r in all_records:
            writer.writerow([
                r.get("url", ""),
                r.get("shortcode", ""),
                r.get("creator", ""),
                r.get("collection", ""),
                str(r.get("timestamp") or ""),
            ])

    count = len(all_records)
    print(format_status("+", f"Exported {count} unique URLs to {target_out}"), file=sys.stderr)
    return count
