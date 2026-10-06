"""Tests for Frame Deduplication, Contact-Sheet Generation & Signal Extraction (`signal.py`, `ocr.py`)."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image, ImageDraw
import pytest

from reel_watcher import (
    dedupe_frames,
    dhash_bits,
    extract_frame_jpg,
    make_contact_sheet,
    ocr_image,
    text_changed,
)


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for test artifacts."""
    d = tmp_path / "signal_test"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_solid_image(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (100, 100)) -> Path:
    """Helper to create a solid color image."""
    img = Image.new("RGB", size, color=color)
    img.save(path, format="JPEG")
    return path


def create_gradient_image(path: Path, left_to_right: bool = True, size: tuple[int, int] = (64, 64)) -> Path:
    """Helper to create horizontal gradient image."""
    w, h = size
    arr = np.zeros((h, w), dtype=np.uint8)
    for x in range(w):
        val = int(255 * (x / (w - 1))) if left_to_right else int(255 * ((w - 1 - x) / (w - 1)))
        arr[:, x] = val
    img = Image.fromarray(arr, mode="L")
    img.save(path, format="JPEG")
    return path


# ---------------------------------------------------------------------------
# dhash_bits Tests
# ---------------------------------------------------------------------------

def test_dhash_bits_nonexistent_file():
    """Verify dhash_bits raises FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        dhash_bits("nonexistent_image_12345.jpg")


def test_dhash_bits_identical_images(temp_dir: Path):
    """Identical images must yield the exact same perceptual hash."""
    img1 = temp_dir / "img1.jpg"
    img2 = temp_dir / "img2.jpg"
    create_gradient_image(img1, left_to_right=True)
    create_gradient_image(img2, left_to_right=True)

    h1 = dhash_bits(img1)
    h2 = dhash_bits(img2)
    assert h1 == h2
    assert (h1 ^ h2).bit_count() == 0


def test_dhash_bits_distinct_images(temp_dir: Path):
    """Completely opposite gradient images must have very high hamming distance."""
    img_ltr = temp_dir / "ltr.jpg"
    img_rtl = temp_dir / "rtl.jpg"
    create_gradient_image(img_ltr, left_to_right=True)
    create_gradient_image(img_rtl, left_to_right=False)

    h_ltr = dhash_bits(img_ltr)
    h_rtl = dhash_bits(img_rtl)
    assert h_ltr != h_rtl
    distance = (h_ltr ^ h_rtl).bit_count()
    # Gradient in reverse direction should invert almost all bits
    assert distance >= 50


def test_dhash_bits_size_parameter(temp_dir: Path):
    """Custom size parameter changes bit length."""
    img = temp_dir / "size_test.jpg"
    create_gradient_image(img, left_to_right=True)

    h4 = dhash_bits(img, size=4)  # 4x4 = 16 bits
    assert isinstance(h4, int)
    assert h4 < (1 << 16)

    h8 = dhash_bits(img, size=8)  # 8x8 = 64 bits
    assert isinstance(h8, int)


# ---------------------------------------------------------------------------
# text_changed Tests
# ---------------------------------------------------------------------------

def test_text_changed_both_empty():
    """Empty or whitespace strings indicate no text change."""
    assert not text_changed("", "")
    assert not text_changed("   ", "")
    assert not text_changed("", "  \n  ")


def test_text_changed_identical_and_case_insensitive():
    """Identical or normalized identical strings indicate no text change."""
    assert not text_changed("Hello World", "Hello World")
    assert not text_changed("hello world", "HELLO WORLD")
    assert not text_changed("  Top 5 AI tools  ", "top 5 ai tools")


def test_text_changed_minor_typo_or_noise():
    """Minor OCR punctuation or tiny difference should not trigger text change."""
    assert not text_changed("Follow for more daily tips", "Follow for more daily tips!")
    assert not text_changed("How to code fast.", "How to code fast")


def test_text_changed_significant_difference():
    """Completely different text indicates meaningful on-screen text change."""
    assert text_changed("Step 1: Choose your niche", "Step 2: Record high hook video")
    assert text_changed("Stop scrolling right now", "Here is the big secret")


def test_text_changed_appearance_or_disappearance():
    """Text appearing from blank or disappearing indicates a change."""
    assert text_changed("", "Breaking News")
    assert text_changed("Viral Hook Formula", "")


# ---------------------------------------------------------------------------
# dedupe_frames Tests
# ---------------------------------------------------------------------------

def test_dedupe_frames_empty():
    """Empty frame list returns empty kept and dropped lists."""
    kept, dropped = dedupe_frames([], [])
    assert kept == []
    assert dropped == []


def test_dedupe_frames_single():
    """Single frame is always kept."""
    kept, dropped = dedupe_frames([100], ["text"])
    assert kept == [0]
    assert dropped == []


def test_dedupe_frames_visual_duplicates_dropped():
    """Frames with identical hashes and unchanged text are deduplicated."""
    # 4 frames: frame 0 and 1 are identical, frame 2 and 3 are identical but different from 0
    h_a = 0b1111000011110000
    h_b = 0b0000111100001111
    hashes = [h_a, h_a, h_b, h_b]
    texts = ["", "", "", ""]

    kept, dropped = dedupe_frames(hashes, texts, thr=9, cap=9)
    assert kept == [0, 2]
    assert dropped == [1, 3]


def test_dedupe_frames_visual_duplicate_kept_when_text_changes():
    """If visual scene is identical but text overlay changed, keep the frame."""
    h_static = 0b1010101010101010
    hashes = [h_static, h_static, h_static]
    texts = ["Tip 1: Wake up early", "Tip 2: Work on your craft", "Tip 3: Never give up"]

    kept, dropped = dedupe_frames(hashes, texts, thr=9, cap=9)
    assert kept == [0, 1, 2]
    assert dropped == []


def test_dedupe_frames_cap_enforcement():
    """Frames are capped to max capacity with even temporal distribution."""
    # 15 distinct frames
    hashes = [1 << i for i in range(15)]
    texts = [f"Frame {i}" for i in range(15)]

    kept, dropped = dedupe_frames(hashes, texts, thr=0, cap=9)
    assert len(kept) == 9
    assert len(dropped) == 6
    # Boundary frames must be preserved
    assert kept[0] == 0
    assert kept[-1] == 14
    # All indices accounted for without overlap
    assert set(kept) | set(dropped) == set(range(15))
    assert set(kept) & set(dropped) == set()


def test_dedupe_frames_cap_zero_and_one():
    """Handle edge case cap values of 0 and 1."""
    hashes = [10, 20, 30]
    texts = ["a", "b", "c"]

    kept_0, dropped_0 = dedupe_frames(hashes, texts, cap=0)
    assert kept_0 == []
    assert dropped_0 == [0, 1, 2]

    kept_1, dropped_1 = dedupe_frames(hashes, texts, cap=1)
    assert kept_1 == [0]
    assert dropped_1 == [1, 2]


def test_dedupe_frames_mismatched_text_length():
    """Handles texts shorter than hashes gracefully without crashing."""
    hashes = [10, 20, 30]
    texts = ["only one text"]

    kept, dropped = dedupe_frames(hashes, texts)
    assert len(kept) + len(dropped) == 3


# ---------------------------------------------------------------------------
# extract_frame_jpg Tests
# ---------------------------------------------------------------------------

def test_extract_frame_jpg_nonexistent_video(temp_dir: Path):
    """Nonexistent video raises FileNotFoundError."""
    dest = temp_dir / "out.jpg"
    with pytest.raises(FileNotFoundError):
        extract_frame_jpg("nonexistent_video_abc.mp4", 1.0, dest)


def test_extract_frame_jpg_missing_ffmpeg(temp_dir: Path):
    """Missing ffmpeg raises RuntimeError."""
    video = temp_dir / "fake.mp4"
    video.write_text("fake video content")
    dest = temp_dir / "out.jpg"

    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="ffmpeg is not found"):
            extract_frame_jpg(video, 0.5, dest)


def test_extract_frame_jpg_subprocess_failure(temp_dir: Path):
    """ffmpeg process failure raises RuntimeError with stderr snippet."""
    video = temp_dir / "fake.mp4"
    video.write_text("fake video")
    dest = temp_dir / "out.jpg"

    mock_proc = MagicMock(returncode=1, stderr="Invalid data found when processing input")
    with patch("shutil.which", return_value="ffmpeg"), patch("subprocess.run", return_value=mock_proc):
        with pytest.raises(RuntimeError, match="ffmpeg frame extraction failed"):
            extract_frame_jpg(video, 0.5, dest)


def test_extract_frame_jpg_mock_success(temp_dir: Path):
    """Successful extraction writes output and returns Path."""
    video = temp_dir / "fake.mp4"
    video.write_text("fake video")
    dest = temp_dir / "out.jpg"

    def side_effect(cmd, **kwargs):
        # Create output file to simulate ffmpeg producing frame
        dest.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        return MagicMock(returncode=0, stderr="")

    with patch("shutil.which", return_value="ffmpeg"), patch("subprocess.run", side_effect=side_effect):
        res = extract_frame_jpg(video, 1.25, dest)
        assert res == dest
        assert res.is_file()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed on system PATH")
def test_extract_frame_jpg_live_ffmpeg(temp_dir: Path):
    """Live ffmpeg synthetic video frame extraction test."""
    video = temp_dir / "synthetic.mp4"
    create_cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=1:size=320x240:rate=10",
        "-c:v", "libx264",
        str(video),
    ]
    proc = subprocess.run(create_cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        pytest.skip("Could not generate synthetic test video with ffmpeg")

    dest = temp_dir / "extracted_frame.jpg"
    extracted = extract_frame_jpg(video, 0.5, dest)
    assert extracted.is_file()
    assert extracted.stat().st_size > 0

    with Image.open(extracted) as img:
        assert img.width == 320
        assert img.height == 240


# ---------------------------------------------------------------------------
# make_contact_sheet Tests
# ---------------------------------------------------------------------------

def test_make_contact_sheet_empty_tiles(temp_dir: Path):
    """Empty tiles list raises ValueError."""
    dest = temp_dir / "sheet.jpg"
    with pytest.raises(ValueError, match="Cannot generate contact sheet"):
        make_contact_sheet([], dest)


def test_make_contact_sheet_missing_tile_file(temp_dir: Path):
    """Missing tile image raises FileNotFoundError."""
    dest = temp_dir / "sheet.jpg"
    with pytest.raises(FileNotFoundError):
        make_contact_sheet([("missing_tile.jpg", "0.5s")], dest)


def test_make_contact_sheet_generation_and_labels(temp_dir: Path):
    """Generates a multi-tile contact sheet with burned-in yellow labels."""
    tiles = []
    colors = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
    ]
    for i, col in enumerate(colors):
        p = temp_dir / f"tile_{i}.jpg"
        create_solid_image(p, color=col, size=(300, 400))
        tiles.append((p, f"0.{i * 5}s"))

    dest = temp_dir / "contact_sheet.jpg"
    result = make_contact_sheet(tiles, dest, tile_px=256, cols=2)

    assert result == dest
    assert dest.is_file()

    with Image.open(dest) as img:
        assert img.mode == "RGB"
        # 4 tiles in 2 cols -> 2 rows
        # Max dimension scaled to 256 (height 400 -> 256, width 300 -> 192)
        # cols=2, rows=2 -> canvas roughly 2 * 192 = 384w, 2 * 256 = 512h
        assert img.width > 0
        assert img.height > 0

        # Verify yellow burned-in text pixels exist in the image
        arr = np.asarray(img)
        # Yellow has high red (>= 200) and high green (>= 200) and low blue (< 100)
        yellow_mask = (arr[:, :, 0] >= 200) & (arr[:, :, 1] >= 200) & (arr[:, :, 2] < 100)
        assert np.any(yellow_mask), "Burned-in yellow labels must be present on the contact sheet"


def test_make_contact_sheet_caps_at_nine_tiles(temp_dir: Path):
    """Contact sheet caps at 9 tiles even if more are supplied."""
    tiles = []
    for i in range(12):
        p = temp_dir / f"t_{i}.jpg"
        create_solid_image(p, color=(i * 20, 50, 100), size=(100, 100))
        tiles.append((p, f"{i}s"))

    dest = temp_dir / "sheet_9.jpg"
    make_contact_sheet(tiles, dest, tile_px=100, cols=3)

    with Image.open(dest) as img:
        # 9 tiles with cols=3 means exactly 3 rows
        assert img.width == 3 * 100
        assert img.height == 3 * 100


# ---------------------------------------------------------------------------
# ocr_image Tests
# ---------------------------------------------------------------------------

def test_ocr_image_nonexistent_file():
    """Nonexistent image raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        ocr_image("missing_img.jpg")


def test_ocr_image_no_ocr_installed_returns_empty_string(temp_dir: Path):
    """When neither RapidOCR nor Tesseract is available, return empty string."""
    img_path = temp_dir / "blank.jpg"
    create_solid_image(img_path, color=(255, 255, 255))

    with patch.dict("sys.modules", {"rapidocr_onnxruntime": None, "pytesseract": None}), \
         patch("shutil.which", return_value=None):
        result = ocr_image(img_path)
        assert result == ""


def test_ocr_image_rapidocr_success(temp_dir: Path):
    """Extracts text using RapidOCR when available."""
    img_path = temp_dir / "text_img.jpg"
    create_solid_image(img_path, color=(255, 255, 255))

    mock_rapid = MagicMock()
    # RapidOCR returns tuple of (result_list, elapse_list)
    mock_rapid.return_value = ([
        [None, "HOOK: 3 Secrets", 0.98],
        [None, "To 10x Your Reach", 0.95],
    ], None)

    mock_mod = MagicMock()
    mock_mod.RapidOCR = MagicMock(return_value=mock_rapid)

    with patch.dict("sys.modules", {"rapidocr_onnxruntime": mock_mod}):
        result = ocr_image(img_path)
        assert result == "HOOK: 3 Secrets To 10x Your Reach"


def test_ocr_image_pytesseract_fallback(temp_dir: Path):
    """Extracts text using pytesseract when RapidOCR is unavailable."""
    img_path = temp_dir / "text_img.jpg"
    create_solid_image(img_path, color=(255, 255, 255))

    mock_pytess = MagicMock()
    mock_pytess.image_to_string.return_value = "Never Give Up\nOn Your Goals\n"

    with patch.dict("sys.modules", {"rapidocr_onnxruntime": None, "pytesseract": mock_pytess}):
        result = ocr_image(img_path)
        assert result == "Never Give Up\nOn Your Goals"


def test_ocr_image_handles_engine_exception_gracefully(temp_dir: Path):
    """If OCR engine throws runtime exception, returns empty string."""
    img_path = temp_dir / "err_img.jpg"
    create_solid_image(img_path, color=(255, 255, 255))

    mock_rapid = MagicMock()
    mock_rapid.side_effect = RuntimeError("ONNX model load failure")
    mock_mod = MagicMock()
    mock_mod.RapidOCR = MagicMock(return_value=mock_rapid)

    with patch.dict("sys.modules", {"rapidocr_onnxruntime": mock_mod, "pytesseract": None}), \
         patch("shutil.which", return_value=None):
        result = ocr_image(img_path)
        assert result == ""
