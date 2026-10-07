"""Study & Synthesis Pipeline for Short-Form Video and Carousels (`study.py`).

Provides:
- Deterministic regex and NLP giveaway/comment-word extraction
- Full multimodal study synthesis combining audio, cuts, OCR, perceptual frames, and VLM
- Dedicated video and carousel analysis pipelines
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from reel_watcher.audio import non_speech_energy_heuristic, transcribe
from reel_watcher.config import format_status
from reel_watcher.db import extract_shortcode
from reel_watcher.media import detect_cuts, id_from_url, pick_frame_times, probe
from reel_watcher.ocr import ocr_image
from reel_watcher.signal import (
    dedupe_frames,
    dhash_bits,
    extract_frame_jpg,
    make_contact_sheet,
)
from reel_watcher.vision import VisionClient

STOP_WORDS = {
    "A",
    "AN",
    "THE",
    "IN",
    "ON",
    "AT",
    "TO",
    "FOR",
    "OF",
    "WITH",
    "BY",
    "AND",
    "OR",
    "BUT",
    "IF",
    "IS",
    "IT",
    "ARE",
    "WAS",
    "BE",
    "ME",
    "YOU",
    "MY",
    "YOUR",
    "WE",
    "US",
    "THEY",
    "THEM",
    "HE",
    "SHE",
    "HIM",
    "HER",
    "BELOW",
    "DOWN",
    "COMMENT",
    "COMMENTS",
    "DROP",
    "DM",
    "TYPE",
    "TEXT",
    "REPLY",
    "SAY",
    "SEND",
    "LINK",
    "BIO",
    "GET",
    "WILL",
    "HERE",
    "NOW",
    "FREE",
    "THIS",
    "THAT",
    "WORD",
    "WORDS",
    "POST",
    "VIDEO",
    "REEL",
    "STORY",
    "OUT",
    "SOME",
    "MORE",
    "HOW",
    "WHAT",
    "WHO",
    "WHY",
    "WHEN",
    "WHERE",
    "THOUGHTS",
    "FEEDBACK",
    "IDEAS",
    "QUESTIONS",
    "ALL",
    "NEW",
    "SO",
    "JUST",
}

OFFER_KEYWORDS = [
    "guide",
    "template",
    "cheatsheet",
    "playbook",
    "blueprint",
    "sop",
    "framework",
    "checklist",
    "prompt",
    "prompts",
    "course",
    "system",
    "workflow",
    "training",
    "masterclass",
    "ebook",
    "pdf",
    "resource",
    "swipe file",
    "tool",
    "script",
    "code",
    "database",
    "deck",
]


def parse_comment_words(*texts: str) -> list[str]:
    """Extract comment trigger keywords from one or more text sources.

    Finds quoted and explicit trigger words (e.g. Comment 'SCALE' below, Drop 'AI',
    DM me SCALE, Type TEMPLATE). Filters common stop words and returns normalized
    uppercase words without duplicates.

    Args:
        *texts: String arguments (e.g. caption, OCR text, transcript).

    Returns:
        List of unique uppercase trigger keywords in order of discovery.
    """
    found: list[str] = []

    for raw in texts:
        if not raw or not isinstance(raw, str):
            continue
        text = raw.strip()
        if not text:
            continue

        # 1. Quoted words following trigger verbs (comment, dm, drop, type, text, reply, say, send)
        # Matches: comment 'WORD', drop "WORD", comment “WORD”, DM 'WORD'
        quoted_after_verb = re.findall(
            r"(?i)\b(?:comment(?:ing|s|ed)?|dm|drop|type|text|reply|say|send)\b[^\n.!?]{0,50}?['\"“‘]([A-Za-z0-9_-]{2,30})['\"”’]",
            text,
        )
        for w in quoted_after_verb:
            word = w.strip().upper()
            if word and word not in STOP_WORDS and word not in found:
                found.append(word)

        # 2. Quoted words in proximity to comment/DM funnel markers
        # Matches: comments below 'WORD', dm me 'WORD'
        quoted_markers = re.findall(
            r"(?i)\b(?:comments?|dm|inbox|giveaway|below|👇)\b[^\n.!?]{0,50}?['\"“‘]([A-Za-z0-9_-]{2,30})['\"”’]",
            text,
        )
        for w in quoted_markers:
            word = w.strip().upper()
            if word and word not in STOP_WORDS and word not in found:
                found.append(word)

        # 3. Unquoted trigger words directly after trigger phrases
        # Matches: Comment GUIDE below, Type TEMPLATE to get, DM me SCALE for
        unquoted = re.findall(
            r"(?i)\b(?:comment|drop|type|text|dm|send)\s+(?:me\s+|below\s+|the\s+word\s+|with\s+)?([A-Za-z0-9_-]{2,25})\b",
            text,
        )
        for w in unquoted:
            word = w.strip().upper()
            if word and word not in STOP_WORDS and word not in found:
                # To prevent matching random lower-case conversational words, check if either:
                # - Originally uppercase in text
                # - Or followed by funnel words in text
                raw_match = re.search(
                    rf"(?i)\b(?:comment|drop|type|text|dm|send)\s+(?:me\s+|below\s+|the\s+word\s+|with\s+)?({re.escape(w)})\b(?:\s+(?:below|to\s+get|for\b|and\s+i|in\s+the|👇))?",
                    text,
                )
                if raw_match:
                    orig_token = raw_match.group(1)
                    if orig_token.isupper() or "below" in text.lower() or "to get" in text.lower():
                        found.append(word)

    return found


def parse_giveaway(
    sources: list[tuple[str, str]],
    vlm_cta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse lead magnet, giveaway, and CTA mechanics across media signals.

    Combines deterministic regex heuristics across caption, OCR, and transcript
    with visual language model CTA output.

    Args:
        sources: List of (source_name, text) pairs.
        vlm_cta: Optional CTA dictionary returned from VisionClient deconstruction.

    Returns:
        dict with keys:
            - has_giveaway: bool
            - action: 'comment', 'dm', 'link_in_bio', or 'none'
            - comment_words: list[str]
            - offer: str
            - sources: list[str]
            - confidence: float (0.0 to 1.0)
            - details: str
    """
    valid_sources = [(str(name), str(t or "")) for name, t in sources if t]
    all_texts = [t for _, t in valid_sources]

    # 1. Extract comment keywords
    comment_words = parse_comment_words(*all_texts)

    # Corroborate with VLM CTA keyword if present
    if vlm_cta and isinstance(vlm_cta, dict):
        vlm_kw = str(vlm_cta.get("keyword") or "").strip().upper()
        if (
            vlm_kw
            and vlm_kw not in ("NONE", "N/A", "NULL")
            and vlm_kw not in comment_words
            and vlm_kw not in STOP_WORDS
        ):
            comment_words.append(vlm_kw)

    # 2. Extract offer / lead magnet
    offer_found = ""
    contributing_sources: list[str] = []

    offer_pattern = (
        r"(?i)\b(?:free\s+)?(?:ai\s+)?("
        + "|".join(re.escape(kw) for kw in OFFER_KEYWORDS)
        + r")\b"
    )

    for src_name, text in valid_sources:
        m = re.search(offer_pattern, text)
        if m:
            if not offer_found:
                # Capture slightly wider context if available
                snippet_m = re.search(
                    rf"(?i)(?:free\s+)?(?:ai\s+)?(?:[a-zA-Z0-9_-]+\s+){{0,2}}{re.escape(m.group(1))}",
                    text,
                )
                offer_found = snippet_m.group(0).strip().title() if snippet_m else m.group(0).strip().title()
            if src_name not in contributing_sources:
                contributing_sources.append(src_name)

    # Corroborate offer with VLM
    if not offer_found and vlm_cta and isinstance(vlm_cta, dict):
        vlm_offer = str(vlm_cta.get("offer") or "").strip()
        if vlm_offer and vlm_offer.lower() not in ("none", "n/a"):
            offer_found = vlm_offer
            if "vlm" not in contributing_sources:
                contributing_sources.append("vlm")

    # 3. Detect conversion action
    action = "none"
    combined_lower = " ".join(all_texts).lower()

    if comment_words:
        action = "comment"
    elif re.search(r"\b(?:link\s+in\s+bio|check\s+(?:the\s+)?bio|bio\s+link|link\s+in\s+description)\b", combined_lower):
        action = "link_in_bio"
    elif re.search(r"\b(?:dm\s+me|send\s+(?:me\s+)?a\s+dm|direct\s+message)\b", combined_lower):
        action = "dm"
    elif vlm_cta and isinstance(vlm_cta, dict):
        vlm_action = str(vlm_cta.get("action") or "").strip().lower()
        if vlm_action in ("comment", "dm", "link_in_bio"):
            action = vlm_action

    # 4. Determine overall giveaway status and confidence
    has_giveaway = False
    confidence = 0.0

    if comment_words:
        has_giveaway = True
        confidence = 1.0 if (offer_found and len(contributing_sources) > 1) else 0.85
    elif action in ("link_in_bio", "dm") and offer_found:
        has_giveaway = True
        confidence = 0.80
    elif action in ("link_in_bio", "dm"):
        has_giveaway = True
        confidence = 0.65
    elif vlm_cta and vlm_cta.get("offer") and vlm_cta.get("action") not in (None, "", "none"):
        has_giveaway = True
        confidence = 0.60

    # 5. Build details description
    if has_giveaway:
        if action == "comment" and comment_words:
            details = f"Comment '{comment_words[0]}' to receive {offer_found or 'the offer'}."
        elif action == "link_in_bio":
            details = f"Directs viewer to link in bio for {offer_found or 'resources'}."
        elif action == "dm":
            details = f"Directs viewer to send a DM for {offer_found or 'resources'}."
        else:
            details = f"Giveaway detected: {offer_found or 'lead magnet'}."
    else:
        details = "No lead magnet or giveaway detected."

    return {
        "has_giveaway": has_giveaway,
        "action": action,
        "comment_words": comment_words,
        "offer": offer_found,
        "sources": contributing_sources,
        "confidence": round(confidence, 2),
        "details": details,
    }


def analyze_video_study(
    video_path: Path | str,
    item: dict[str, Any],
    meta: dict[str, Any],
    work_dir: Path | str,
    vision: VisionClient,
    fast: bool = False,
) -> dict[str, Any]:
    """Execute complete multimodal study deconstruction on a video file.

    Orchestrates:
    1. Media probing and cut detection
    2. Frame candidate extraction and OCR
    3. Perceptual dHash frame deduplication
    4. 3x3 labeled contact-sheet generation
    5. Audio speech transcription and energy heuristics
    6. Vision LLM multimodal content deconstruction
    7. Giveaway and CTA funnel parsing
    8. Structured intelligence study aggregation

    Args:
        video_path: Path to target video media.
        item: Queue item or identifier dictionary.
        meta: Video metadata (title, author, caption, etc.).
        work_dir: Intermediate workspace directory.
        vision: VisionClient instance.
        fast: Whether to use sparse frame sampling.

    Returns:
        Structured study dictionary ready for Vault persistence.

    Raises:
        FileNotFoundError: If video_path does not exist.
    """
    v_path = Path(video_path)
    if not v_path.is_file():
        raise FileNotFoundError(f"Target video not found: {v_path}")

    w_dir = Path(work_dir)
    w_dir.mkdir(parents=True, exist_ok=True)

    # 1. Resolve shortcode and identifiers
    raw_url = str(item.get("url") or meta.get("url") or "")
    code = (
        item.get("shortcode")
        or item.get("code")
        or extract_shortcode(raw_url)
        or id_from_url(raw_url)
        or v_path.stem
    )
    code = str(code)

    print(format_status("info", f"Analyzing video study for {code}..."))

    # 2. Probe media & detect scene cuts
    probe_info = probe(v_path)
    duration = float(probe_info.get("duration", 0.0))
    has_audio = bool(probe_info.get("has_audio", False))

    cuts = detect_cuts(v_path, duration) if duration > 0.0 else []
    frame_times = pick_frame_times(cuts, duration, fast=fast)
    if not frame_times and duration > 0.0:
        frame_times = [0.0]

    # 3. Extract frames, OCR & perceptual hashes
    frames_dir = w_dir / f"{code}_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    extracted_frames: list[Path] = []
    ocr_texts: list[str] = []
    hashes: list[int] = []

    for idx, t in enumerate(frame_times):
        f_path = frames_dir / f"frame_{idx:03d}_{t:.3f}s.jpg"
        extract_frame_jpg(v_path, t, f_path)
        extracted_frames.append(f_path)
        ocr_texts.append(ocr_image(f_path))
        hashes.append(dhash_bits(f_path))

    # 4. Deduplicate frames & generate contact sheet
    kept_indices, _ = dedupe_frames(hashes, ocr_texts, thr=9, cap=9)
    if not kept_indices and extracted_frames:
        kept_indices = [0]

    tiles: list[tuple[Path | str, str]] = [
        (extracted_frames[i], f"{frame_times[i]:.2f}s") for i in kept_indices
    ]
    sheet_path = w_dir / f"{code}_contact_sheet.jpg"
    make_contact_sheet(tiles, sheet_path, tile_px=512, cols=3)

    # 5. Speech transcription & energy heuristics
    if has_audio:
        audio_info = transcribe(v_path)
        words = audio_info.get("words", [])
        energy_info = non_speech_energy_heuristic(v_path, words, duration)
    else:
        audio_info = {
            "text": "",
            "language": "en",
            "segments": [],
            "words": [],
            "backend": "none",
        }
        energy_info = non_speech_energy_heuristic("", [], duration)

    # 6. Vision deconstruction via VisionClient
    caption = str(
        meta.get("caption")
        or meta.get("description")
        or item.get("caption")
        or ""
    )
    title = str(meta.get("title") or item.get("title") or f"Reel {code}")
    author = str(
        meta.get("author")
        or meta.get("uploader")
        or item.get("author")
        or ""
    )

    context_lines = [
        f"Title: {title}",
        f"Duration: {duration:.2f}s",
        f"Scene Cuts: {len(cuts)}",
    ]
    if author and author not in ("unknown", "local_import"):
        context_lines.append(f"Author: {author}")
    if caption:
        context_lines.append(f"Caption: {caption}")
    else:
        context_lines.append("Note: No social caption available. Deconstruct purely from visual contact sheet and audio transcript.")
    if audio_info.get("text"):
        context_lines.append(f"Transcript: {audio_info.get('text', '')}")

    context_prompt = "\n".join(context_lines)

    vlm_result = vision.ask_contact_sheet(sheet_path, context_prompt=context_prompt)

    # 7. Giveaway & CTA Funnel Analysis
    combined_ocr = " ".join(t for t in ocr_texts if t)
    sources = [
        ("caption", caption),
        ("ocr", combined_ocr),
        ("transcript", audio_info.get("text", "")),
    ]
    giveaway = parse_giveaway(sources, vlm_cta=vlm_result.get("cta"))

    # 8. Hook text synthesis
    vlm_hook = vlm_result.get("hook", {})
    hook_text = ""
    if isinstance(vlm_hook, dict):
        hook_text = str(vlm_hook.get("text") or "").strip()
    if not hook_text and ocr_texts:
        hook_text = ocr_texts[0].strip()
    if not hook_text and audio_info.get("words"):
        hook_text = " ".join(w["w"] for w in audio_info["words"][:6])

    # 9. Synthesize complete study dictionary
    score_val = vlm_result.get("score", 0.0)
    try:
        score = float(score_val)
    except (ValueError, TypeError):
        score = 0.0

    study: dict[str, Any] = {
        "code": code,
        "shortcode": code,
        "url": raw_url,
        "collection": str(item.get("collection") or ""),
        "title": title,
        "author": author,
        "duration": duration,
        "width": int(probe_info.get("width", 0)),
        "height": int(probe_info.get("height", 0)),
        "fps": float(probe_info.get("fps", 0.0)),
        "hook_text": hook_text,
        "summary": str(vlm_result.get("summary") or ""),
        "framework": str(vlm_result.get("framework") or ""),
        "score": score,
        "cuts": cuts,
        "cuts_count": len(cuts),
        "frame_count": len(kept_indices),
        "transcript": audio_info,
        "audio_analysis": energy_info,
        "giveaway": giveaway,
        "visual_analysis": vlm_result,
        "contact_sheet": str(sheet_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    print(format_status("success", f"Deconstructed video study for {code} (score: {score})."))
    return study


def analyze_carousel_study(
    slides: list[Path | str],
    item: dict[str, Any],
    meta: dict[str, Any],
    work_dir: Path | str,
    vision: VisionClient,
) -> dict[str, Any]:
    """Execute multimodal study deconstruction on an Instagram or LinkedIn carousel.

    Args:
        slides: Ordered list of slide image paths.
        item: Queue item or identifier dictionary.
        meta: Carousel metadata (title, author, caption, etc.).
        work_dir: Intermediate workspace directory.
        vision: VisionClient instance.

    Returns:
        Structured study dictionary ready for Vault persistence.

    Raises:
        ValueError: If slides list is empty.
        FileNotFoundError: If any slide image file does not exist.
    """
    if not slides:
        raise ValueError("slides list cannot be empty.")

    slide_paths: list[Path] = []
    for s in slides:
        p = Path(s)
        if not p.is_file():
            raise FileNotFoundError(f"Carousel slide not found: {p}")
        slide_paths.append(p)

    w_dir = Path(work_dir)
    w_dir.mkdir(parents=True, exist_ok=True)

    raw_url = str(item.get("url") or meta.get("url") or "")
    code = (
        item.get("shortcode")
        or item.get("code")
        or extract_shortcode(raw_url)
        or id_from_url(raw_url)
        or slide_paths[0].stem
    )
    code = str(code)

    print(format_status("info", f"Analyzing carousel study for {code} ({len(slide_paths)} slides)..."))

    # 1. OCR each slide
    ocr_texts = [ocr_image(p) for p in slide_paths]

    # 2. Build contact sheet (up to 9 slides)
    tiles: list[tuple[Path | str, str]] = [
        (slide_paths[i], f"Slide {i + 1}")
        for i in range(min(9, len(slide_paths)))
    ]
    sheet_path = w_dir / f"{code}_contact_sheet.jpg"
    make_contact_sheet(tiles, sheet_path, tile_px=512, cols=3)

    # 3. Vision deconstruction via VisionClient
    caption = str(
        meta.get("caption")
        or meta.get("description")
        or item.get("caption")
        or ""
    )
    title = str(meta.get("title") or item.get("title") or f"Carousel {code}")
    author = str(
        meta.get("author")
        or meta.get("uploader")
        or item.get("author")
        or ""
    )

    context_prompt = (
        f"Title: {title}\n"
        f"Author: {author}\n"
        f"Caption: {caption}\n"
        f"Carousel slides: {len(slide_paths)}"
    )

    vlm_result = vision.ask_contact_sheet(sheet_path, context_prompt=context_prompt)

    # 4. Giveaway & CTA Funnel Analysis
    combined_ocr = " ".join(t for t in ocr_texts if t)
    sources = [
        ("caption", caption),
        ("ocr", combined_ocr),
    ]
    giveaway = parse_giveaway(sources, vlm_cta=vlm_result.get("cta"))

    # 5. Hook text synthesis
    vlm_hook = vlm_result.get("hook", {})
    hook_text = ""
    if isinstance(vlm_hook, dict):
        hook_text = str(vlm_hook.get("text") or "").strip()
    if not hook_text and ocr_texts:
        hook_text = ocr_texts[0].strip()

    score_val = vlm_result.get("score", 0.0)
    try:
        score = float(score_val)
    except (ValueError, TypeError):
        score = 0.0

    study: dict[str, Any] = {
        "code": code,
        "shortcode": code,
        "url": raw_url,
        "collection": str(item.get("collection") or ""),
        "title": title,
        "author": author,
        "media_type": "carousel",
        "slides_count": len(slide_paths),
        "slides": [str(p) for p in slide_paths],
        "hook_text": hook_text,
        "summary": str(vlm_result.get("summary") or ""),
        "framework": str(vlm_result.get("framework") or ""),
        "score": score,
        "giveaway": giveaway,
        "visual_analysis": vlm_result,
        "contact_sheet": str(sheet_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    print(format_status("success", f"Deconstructed carousel study for {code} (score: {score})."))
    return study
