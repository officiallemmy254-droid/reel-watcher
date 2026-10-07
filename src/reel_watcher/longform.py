"""Additive Long-Form Video Intelligence Engine (`longform.py`).

Provides chapter segmentation, subtitle harvesting, keyframe sampling, and
long-form strategic deconstruction for YouTube videos (10 mins to 2 hours+)
without modifying or disrupting existing short-form reel processing pipelines.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

from reel_watcher.config import format_status
from reel_watcher.db import extract_shortcode
from reel_watcher.signal import extract_frame_jpg, make_contact_sheet
from reel_watcher.vision import VisionClient
from PIL import Image


LONGFORM_SYSTEM_PROMPT = """You are an elite research analyst, knowledge engineer, and executive content strategist.
Analyze the provided long-form video intelligence data (chapter breakdown, transcript text, and visual contact sheet).
Deconstruct the core ideas, frameworks, and actionable insights into valid JSON:
{
  "executive_summary": "3-4 sentence comprehensive overview of the video's core thesis and outcomes.",
  "core_thesis": "The fundamental argument or premise the creator is making.",
  "framework": "Primary methodology, model, or conceptual framework presented.",
  "score": 9.0,
  "chapters": [
    {
      "title": "Chapter name",
      "timestamp": "HH:MM:SS or MM:SS",
      "summary": "Key ideas discussed in this chapter",
      "insights": ["Key takeaway 1", "Key takeaway 2"]
    }
  ],
  "actionable_takeaways": [
    "Concrete action, tool, or SOP viewer can implement immediately",
    "Second concrete implementation step"
  ],
  "strengths": ["Clear visual diagrams", "High information density"],
  "weaknesses": ["Slow pacing in middle section"]
}

CRITICAL: Return valid JSON ONLY. Do not enclose in markdown explanation or conversational text."""


def _timestamp_to_seconds(ts_str: str) -> float:
    """Convert timestamp string (HH:MM:SS.mmm or MM:SS.mmm) to seconds."""
    parts = ts_str.strip().split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(ts_str)


def format_seconds(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS string."""
    s = int(seconds)
    hours = s // 3600
    minutes = (s % 3600) // 60
    secs = s % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _strip_overlap(prev: str, curr: str) -> str:
    """Strip overlapping prefix from curr that appeared as suffix of prev."""
    if not prev or not curr:
        return curr
    if curr.startswith(prev):
        return curr[len(prev):].strip()
    prev_words = prev.split()
    curr_words = curr.split()
    max_check = min(len(prev_words), len(curr_words), 30)
    for k in range(max_check, 0, -1):
        if prev_words[-k:] == curr_words[:k]:
            return " ".join(curr_words[k:]).strip()
    return curr


def parse_vtt(vtt_content: str) -> list[dict[str, Any]]:
    """Parse WebVTT subtitle text into ordered, deduplicated cue segments.

    Strips HTML/karaoke tags and filters redundant repeated lines from
    scrolling YouTube auto-captions.
    """
    if not vtt_content or not isinstance(vtt_content, str):
        return []

    lines = [line.strip() for line in vtt_content.splitlines()]
    cues: list[dict[str, Any]] = []

    time_pattern = re.compile(
        r"(\d{2}:(?:\d{2}:)?\d{2}[\.,]\d{3})\s+-->\s+(\d{2}:(?:\d{2}:)?\d{2}[\.,]\d{3})"
    )

    idx = 0
    total = len(lines)
    while idx < total:
        line = lines[idx]
        match = time_pattern.search(line)
        if match:
            start_sec = _timestamp_to_seconds(match.group(1).replace(",", "."))
            end_sec = _timestamp_to_seconds(match.group(2).replace(",", "."))
            idx += 1

            text_lines: list[str] = []
            while idx < total and lines[idx] and not time_pattern.search(lines[idx]):
                clean_line = re.sub(r"<[^>]+>", "", lines[idx]).strip()
                if clean_line and clean_line not in text_lines:
                    text_lines.append(clean_line)
                idx += 1

            raw_text = " ".join(text_lines).strip()
            if raw_text:
                if cues:
                    novel_text = _strip_overlap(cues[-1]["text"], raw_text)
                    if not novel_text:
                        cues[-1]["end"] = max(cues[-1]["end"], end_sec)
                    else:
                        cues.append({
                            "start": round(start_sec, 2),
                            "end": round(end_sec, 2),
                            "text": novel_text,
                        })
                else:
                    cues.append({
                        "start": round(start_sec, 2),
                        "end": round(end_sec, 2),
                        "text": raw_text,
                    })
        else:
            idx += 1

    return cues


def synthesize_chapters(duration: float, chunk_seconds: float = 300.0) -> list[dict[str, Any]]:
    """Synthesize logical chapters when official video chapters are not present.

    Args:
        duration: Total video length in seconds.
        chunk_seconds: Length of each chapter block (default: 5 minutes / 300s).

    Returns:
        List of chapter dictionaries with start_time, end_time, and title.
    """
    if duration <= 0.0:
        return [{"title": "Full Video", "start_time": 0.0, "end_time": 0.0}]

    if duration <= chunk_seconds:
        return [{
            "title": "Full Overview",
            "start_time": 0.0,
            "end_time": round(duration, 2),
        }]

    chapters: list[dict[str, Any]] = []
    current = 0.0
    part_idx = 1
    while current < duration:
        nxt = min(current + chunk_seconds, duration)
        chapters.append({
            "title": f"Part {part_idx} ({format_seconds(current)})",
            "start_time": round(current, 2),
            "end_time": round(nxt, 2),
        })
        current = nxt
        part_idx += 1

    return chapters


def align_transcript_to_chapters(
    chapters: list[dict[str, Any]],
    cues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Align timestamped subtitle cues into corresponding chapters."""
    aligned: list[dict[str, Any]] = []

    for ch in chapters:
        ch_copy = dict(ch)
        start_t = float(ch.get("start_time", 0.0))
        end_t = float(ch.get("end_time", sys.maxsize))

        matched = [
            c["text"]
            for c in cues
            if start_t <= c.get("start", 0.0) < end_t
        ]
        ch_copy["transcript"] = " ".join(matched).strip()
        aligned.append(ch_copy)

    return aligned


def get_longform_metadata(
    url: str,
    use_cookies: bool = True,
    browser: str = "chrome",
    timeout: int = 60,
) -> dict[str, Any]:
    """Retrieve YouTube video metadata and official chapters via yt-dlp."""
    cmd = [
        "yt-dlp",
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        "--no-warnings",
    ]
    if use_cookies:
        cmd.extend(["--cookies-from-browser", browser])
    cmd.append(url)

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )

    if proc.returncode != 0 and use_cookies:
        # Fallback without cookies
        cmd_no_cookies = [c for c in cmd if c not in ("--cookies-from-browser", browser)]
        proc = subprocess.run(
            cmd_no_cookies,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed to retrieve metadata: {proc.stderr.strip() or proc.stdout.strip()}")

    raw = json.loads(proc.stdout)
    vid_id = str(raw.get("id") or extract_shortcode(url) or "unknown")
    duration = float(raw.get("duration") or 0.0)

    # Parse official chapters if present
    raw_chapters = raw.get("chapters") or []
    parsed_chapters: list[dict[str, Any]] = []
    if raw_chapters:
        for c in raw_chapters:
            parsed_chapters.append({
                "title": str(c.get("title", f"Chapter at {c.get('start_time', 0)}s")),
                "start_time": float(c.get("start_time", 0.0)),
                "end_time": float(c.get("end_time", duration)),
            })
    else:
        parsed_chapters = synthesize_chapters(duration)

    return {
        "id": vid_id,
        "shortcode": vid_id,
        "url": raw.get("webpage_url") or url,
        "title": str(raw.get("title") or f"YouTube Video {vid_id}"),
        "author": str(raw.get("channel") or raw.get("uploader") or "Unknown Creator"),
        "duration": duration,
        "description": str(raw.get("description") or ""),
        "chapters": parsed_chapters,
        "thumbnail": str(raw.get("thumbnail") or ""),
        "views": raw.get("view_count"),
        "likes": raw.get("like_count"),
    }


def fetch_subtitles(
    url: str,
    work_dir: Path | str,
    use_cookies: bool = True,
    browser: str = "chrome",
    timeout: int = 60,
) -> list[dict[str, Any]]:
    """Download and parse English auto-captions/subtitles directly in WebVTT format."""
    w_dir = Path(work_dir)
    w_dir.mkdir(parents=True, exist_ok=True)

    out_tmpl = str(w_dir / "%(id)s.%(ext)s")
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", "en.*,en",
        "--sub-format", "vtt",
        "--no-playlist",
        "-o", out_tmpl,
    ]
    if use_cookies:
        cmd.extend(["--cookies-from-browser", browser])
    cmd.append(url)

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )

    if proc.returncode != 0 and use_cookies:
        cmd_no_cookies = [c for c in cmd if c not in ("--cookies-from-browser", browser)]
        proc = subprocess.run(
            cmd_no_cookies,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    # Search for written vtt files in work_dir
    vtt_files = list(w_dir.glob("*.vtt"))
    if not vtt_files:
        return []

    # Read latest vtt file
    latest_vtt = sorted(vtt_files, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    content = latest_vtt.read_text(encoding="utf-8", errors="replace")
    return parse_vtt(content)


def extract_chapter_keyframes(
    v_path_or_url: Path | str,
    chapters: list[dict[str, Any]],
    work_dir: Path | str,
    max_frames: int = 9,
) -> list[tuple[Path, str]]:
    """Extract keyframe images for each chapter milestone."""
    w_dir = Path(work_dir)
    w_dir.mkdir(parents=True, exist_ok=True)

    tiles: list[tuple[Path, str]] = []
    # Cap number of chapter frames for contact sheet layout
    sample_chapters = chapters[:max_frames]

    for idx, ch in enumerate(sample_chapters):
        ch_title = ch.get("title", f"Ch {idx + 1}")
        start_t = float(ch.get("start_time", 0.0))
        sample_t = max(0.0, start_t + 1.0)

        out_img = w_dir / f"ch_{idx:02d}_{sample_t:.1f}s.jpg"
        try:
            extract_frame_jpg(v_path_or_url, sample_t, out_img)
            if out_img.exists():
                tiles.append((out_img, ch_title[:24]))
        except Exception:
            pass

    return tiles


def generate_longform_markdown(study: dict[str, Any]) -> str:
    """Format structured long-form intelligence study into a readable Obsidian/Vault note."""
    analysis = study.get("longform_analysis", {})
    exec_summary = analysis.get("executive_summary") or study.get("summary", "")
    thesis = analysis.get("core_thesis", "N/A")
    framework = analysis.get("framework") or study.get("framework", "N/A")
    score = study.get("score", 0.0)
    author = study.get("author", "Unknown")
    title = study.get("title", "Untitled")
    url = study.get("url", "")
    duration_fmt = format_seconds(float(study.get("duration", 0.0)))
    chapters = study.get("chapters", [])
    takeaways = analysis.get("actionable_takeaways", [])

    md_lines = [
        f"# {title}",
        "",
        f"- **Creator:** {author}",
        f"- **URL:** {url}",
        f"- **Duration:** {duration_fmt}",
        f"- **Score:** {score}/10",
        f"- **Core Framework:** {framework}",
        f"- **Date Indexed:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Executive Summary",
        f"{exec_summary}",
        "",
        "## Core Thesis",
        f"> {thesis}",
        "",
        "## Actionable Takeaways & Implementation",
    ]

    if takeaways:
        for t in takeaways:
            md_lines.append(f"- [ ] {t}")
    else:
        md_lines.append("- No distinct action items extracted.")

    md_lines.extend(["", "## Chapter Breakdown"])

    for ch in chapters:
        ch_title = ch.get("title", "Chapter")
        ch_start = format_seconds(float(ch.get("start_time", 0.0)))
        ch_end = format_seconds(float(ch.get("end_time", 0.0)))
        md_lines.append(f"### {ch_title} ({ch_start} - {ch_end})")
        if ch.get("summary"):
            md_lines.append(f"{ch['summary']}")
        if ch.get("transcript"):
            snippet = ch["transcript"][:300] + ("..." if len(ch["transcript"]) > 300 else "")
            md_lines.append(f"*Transcript excerpt:* \"{snippet}\"")
        md_lines.append("")

    return "\n".join(md_lines)


def analyze_longform_study(
    url: str,
    work_dir: Path | str,
    vision: VisionClient,
    use_cookies: bool = True,
    browser: str = "chrome",
) -> dict[str, Any]:
    """Execute complete long-form YouTube video intelligence deconstruction."""
    w_dir = Path(work_dir)
    w_dir.mkdir(parents=True, exist_ok=True)

    print(format_status("info", f"Harvesting long-form metadata for {url}..."))
    meta = get_longform_metadata(url, use_cookies=use_cookies, browser=browser)
    shortcode = meta["shortcode"]
    title = meta["title"]
    author = meta["author"]
    duration = meta["duration"]
    chapters = meta["chapters"]

    print(format_status("info", f"Extracting captions & subtitles for {shortcode}..."))
    cues = fetch_subtitles(url, w_dir, use_cookies=use_cookies, browser=browser)
    aligned_chapters = align_transcript_to_chapters(chapters, cues)

    full_transcript_text = " ".join(c["text"] for c in cues).strip()

    # Extract chapter keyframes if video is locally present or via stream
    sheet_path = w_dir / f"{shortcode}_chapters_sheet.jpg"
    keyframes = extract_chapter_keyframes(url, aligned_chapters, w_dir)
    if keyframes:
        try:
            make_contact_sheet(keyframes, sheet_path, tile_px=512, cols=3)
        except Exception:
            pass

    if not sheet_path.exists():
        # Create lightweight placeholder image for Vision API compatibility
        placeholder = Image.new("RGB", (512, 512), color=(24, 24, 30))
        placeholder.save(sheet_path, "JPEG")

    # Prompt vision client with long-form context
    prompt = (
        f"{LONGFORM_SYSTEM_PROMPT}\n\n"
        f"Video Title: {title}\n"
        f"Creator: {author}\n"
        f"Duration: {duration} seconds\n"
        f"Chapters:\n"
        + "\n".join(f"- {c['title']}: {c.get('transcript', '')[:200]}" for c in aligned_chapters[:10])
    )

    vlm_res = vision.ask_contact_sheet(sheet_path, context_prompt=prompt)

    score_val = vlm_res.get("score", 8.5)
    try:
        score = float(score_val)
    except (ValueError, TypeError):
        score = 8.5

    study: dict[str, Any] = {
        "code": shortcode,
        "shortcode": shortcode,
        "url": meta.get("url") or url,
        "media_type": "longform",
        "title": title,
        "author": author,
        "duration": duration,
        "summary": str(vlm_res.get("executive_summary") or vlm_res.get("summary") or ""),
        "framework": str(vlm_res.get("framework") or ""),
        "score": score,
        "chapters": aligned_chapters,
        "transcript": {
            "text": full_transcript_text,
            "cues": cues,
            "backend": "youtube_subtitles",
        },
        "longform_analysis": vlm_res,
        "contact_sheet": str(sheet_path) if sheet_path and sheet_path.exists() else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Generate Vault Markdown
    study["markdown"] = generate_longform_markdown(study)

    print(format_status("success", f"Deconstructed long-form study for {shortcode} (score: {score})."))
    return study
