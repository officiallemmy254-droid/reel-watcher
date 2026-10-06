"""Perceptual Frame Deduplication, Contact-Sheet Generation & Signal Extraction (`signal.py`)."""

from __future__ import annotations

import difflib
import math
from pathlib import Path
import shutil
import subprocess
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from reel_watcher.config import format_status


def extract_frame_jpg(video: Path | str, time_sec: float, dest: Path | str) -> Path:
    """Extract a single frame from video at specified time into a JPEG file.

    Args:
        video: Path to input video file.
        time_sec: Frame timestamp in seconds.
        dest: Destination path for extracted JPEG.

    Returns:
        Path to the saved JPEG file.

    Raises:
        FileNotFoundError: If the video file does not exist.
        RuntimeError: If ffmpeg is missing or extraction fails.
    """
    v_path = Path(video)
    if not v_path.is_file():
        raise FileNotFoundError(f"Video file not found: {v_path}")

    d_path = Path(dest)
    d_path.parent.mkdir(parents=True, exist_ok=True)

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not found on PATH. Run preflight() for installation instructions.")

    ts_str = f"{max(0.0, float(time_sec)):.3f}"
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        ts_str,
        "-i",
        str(v_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(d_path),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as exc:
        raise RuntimeError(f"Failed to execute ffmpeg: {exc}") from exc

    if proc.returncode != 0 or not d_path.is_file():
        snippet = proc.stderr.strip()[-300:] if proc.stderr else "Unknown error"
        raise RuntimeError(
            f"ffmpeg frame extraction failed at {ts_str}s (exit code {proc.returncode}): {snippet}"
        )

    return d_path


def dhash_bits(path: Path | str, size: int = 8) -> int:
    """Compute perceptual difference hash (dHash) as an integer.

    Resizes image to (size + 1, size) in grayscale and evaluates whether each
    pixel is brighter than its adjacent horizontal neighbor.
    For size=8, this produces a 64-bit integer.

    Args:
        path: Path to the input image file.
        size: Grid dimension for hash calculation (default 8).

    Returns:
        dHash value as an integer.

    Raises:
        FileNotFoundError: If the image file does not exist.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Image file not found: {p}")

    with Image.open(p) as img:
        gray = img.convert("L")
        resized = gray.resize((size + 1, size), Image.Resampling.LANCZOS)
        arr = np.asarray(resized, dtype=np.int32)
        diff = arr[:, :-1] > arr[:, 1:]

        # Pack boolean array into an integer
        val = 0
        for bit in diff.flatten():
            val = (val << 1) | int(bit)
        return val


def text_changed(a: str, b: str, threshold: float = 0.8) -> bool:
    """Determine whether on-screen text changed significantly between two frames.

    Args:
        a: First text string.
        b: Second text string.
        threshold: SequenceMatcher similarity threshold (default 0.8).

    Returns:
        True if text has changed significantly or appeared/disappeared; False otherwise.
    """
    norm_a = " ".join(str(a or "").strip().lower().split())
    norm_b = " ".join(str(b or "").strip().lower().split())

    # Both empty -> no text change
    if not norm_a and not norm_b:
        return False

    # One empty, one populated -> text appeared or disappeared
    if not norm_a or not norm_b:
        return True

    # Exactly identical
    if norm_a == norm_b:
        return False

    ratio = difflib.SequenceMatcher(None, norm_a, norm_b).ratio()
    return ratio < threshold


def dedupe_frames(
    hashes: list[int],
    texts: list[str],
    thr: int = 9,
    cap: int = 9,
) -> tuple[list[int], list[int]]:
    """Deduplicate sequential frames using perceptual dHash and OCR text changes.

    Keeps the initial frame, then evaluates subsequent frames against the last
    kept frame. A frame is treated as duplicate only if its visual hamming
    distance <= thr AND its on-screen text has not changed.

    If the number of kept frames exceeds cap, uniformly downsamples to cap
    frames while guaranteeing the start and end frames are retained.

    Args:
        hashes: List of dHash integer values for candidate frames.
        texts: List of extracted OCR text strings for candidate frames.
        thr: Hamming distance similarity threshold (default 9).
        cap: Maximum number of frames to retain (default 9).

    Returns:
        tuple containing:
            - list[int]: Indices of kept frames.
            - list[int]: Indices of dropped/duplicate frames.
    """
    if not hashes:
        return [], []

    total = len(hashes)
    if cap <= 0:
        return [], list(range(total))

    # Normalize texts length
    normalized_texts = list(texts)
    if len(normalized_texts) < total:
        normalized_texts.extend([""] * (total - len(normalized_texts)))

    # Sequential deduplication against last kept frame
    kept: list[int] = [0]
    dropped: list[int] = []

    for i in range(1, total):
        last_idx = kept[-1]
        dist = (hashes[i] ^ hashes[last_idx]).bit_count()
        is_dup = (dist <= thr) and not text_changed(normalized_texts[last_idx], normalized_texts[i])

        if is_dup:
            dropped.append(i)
        else:
            kept.append(i)

    # Enforce capacity limit via uniform temporal subsampling
    if len(kept) > cap:
        if cap == 1:
            new_kept = [kept[0]]
            for k in kept[1:]:
                dropped.append(k)
            kept = new_kept
        else:
            step = (len(kept) - 1) / (cap - 1)
            sub_indices = sorted({round(j * step) for j in range(cap)})
            # Guarantee exactly cap items if rounding collisions occur
            while len(sub_indices) < cap:
                for cand in range(len(kept)):
                    if cand not in sub_indices:
                        sub_indices.append(cand)
                        sub_indices.sort()
                        if len(sub_indices) == cap:
                            break

            new_kept = [kept[idx] for idx in sub_indices]
            for idx, k in enumerate(kept):
                if idx not in sub_indices:
                    dropped.append(k)
            kept = sorted(new_kept)

    return kept, sorted(dropped)


def _load_label_font(size: int = 18) -> ImageFont.ImageFont:
    """Attempt to load a clean cross-platform TrueType font, falling back to default."""
    candidates = [
        "arial.ttf",
        "Arial.ttf",
        "DejaVuSans.ttf",
        "Helvetica.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for font_name in candidates:
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def make_contact_sheet(
    tiles: list[tuple[Path | str, str]],
    dest: Path | str,
    tile_px: int = 512,
    cols: int = 3,
) -> Path:
    """Generate a labeled contact-sheet grid of up to 9 tiles with yellow labels.

    Args:
        tiles: List of (image_path, label) pairs.
        dest: Destination path for saved contact sheet.
        tile_px: Maximum dimension in pixels for each tile (default 512).
        cols: Number of columns in grid (default 3).

    Returns:
        Path to the saved contact-sheet image.

    Raises:
        ValueError: If tiles list is empty.
        FileNotFoundError: If any tile image file does not exist.
    """
    if not tiles:
        raise ValueError("Cannot generate contact sheet from empty tiles list")

    # Enforce maximum of 9 tiles
    active_tiles = tiles[:9]

    # Validate and load tile images
    loaded_tiles: list[tuple[Image.Image, str]] = []
    max_w = 0
    max_h = 0

    for path, label in active_tiles:
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Tile image not found: {p}")

        img = Image.open(p).convert("RGB")
        orig_w, orig_h = img.size

        # Scale maintaining aspect ratio so max dimension is tile_px
        if orig_w >= orig_h:
            scale = tile_px / orig_w
        else:
            scale = tile_px / orig_h

        tw = max(1, int(round(orig_w * scale)))
        th = max(1, int(round(orig_h * scale)))

        scaled = img.resize((tw, th), Image.Resampling.LANCZOS)
        loaded_tiles.append((scaled, label))

        if tw > max_w:
            max_w = tw
        if th > max_h:
            max_h = th

    num_tiles = len(loaded_tiles)
    rows = (num_tiles + cols - 1) // cols

    canvas_w = cols * max_w
    canvas_h = rows * max_h

    canvas = Image.new("RGB", (canvas_w, canvas_h), color=(18, 18, 18))
    draw = ImageDraw.Draw(canvas)

    font_size = max(14, int(max_h * 0.05))
    font = _load_label_font(font_size)

    for i, (tile_img, raw_label) in enumerate(loaded_tiles):
        row = i // cols
        col = i % cols

        cell_x = col * max_w
        cell_y = row * max_h

        tw, th = tile_img.size
        paste_x = cell_x + (max_w - tw) // 2
        paste_y = cell_y + (max_h - th) // 2

        canvas.paste(tile_img, (paste_x, paste_y))

        # Format label "#n  <timestamp>"
        n = i + 1
        clean_lbl = str(raw_label).strip() if raw_label else ""
        if clean_lbl.startswith("#"):
            label_text = clean_lbl
        elif clean_lbl:
            label_text = f"#{n}  {clean_lbl}"
        else:
            label_text = f"#{n}"

        # Burn-in yellow label with dark badge background
        bbox = draw.textbbox((0, 0), label_text, font=font)
        txt_w = bbox[2] - bbox[0]
        txt_h = bbox[3] - bbox[1]

        pad_x, pad_y = 6, 4
        badge_x = paste_x + 8
        badge_y = paste_y + 8

        # Dark background badge
        draw.rectangle(
            [badge_x, badge_y, badge_x + txt_w + pad_x * 2, badge_y + txt_h + pad_y * 2],
            fill=(0, 0, 0),
        )

        # Yellow label text
        draw.text(
            (badge_x + pad_x, badge_y + pad_y),
            label_text,
            fill=(255, 255, 0),
            font=font,
        )

    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest_path, "JPEG", quality=90)

    return dest_path
