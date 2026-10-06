"""Cross-Platform OCR Extraction Engine (`ocr.py`)."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from PIL import Image


def ocr_image(path: Path | str) -> str:
    """Extract on-screen text from an image file using available OCR engines.

    Tries engines in fallback order:
    1. RapidOCR (`rapidocr_onnxruntime`)
    2. PyTesseract (`pytesseract`)
    3. System Tesseract CLI binary (`tesseract`)

    If no OCR engine is installed or if the engine fails, gracefully returns an empty string.

    Args:
        path: Path to the target image file.

    Returns:
        Extracted text as a clean string, or empty string if no text/engine.

    Raises:
        FileNotFoundError: If the specified image file does not exist.
    """
    img_path = Path(path)
    if not img_path.is_file():
        raise FileNotFoundError(f"Image not found: {img_path}")

    # 1. Try RapidOCR
    try:
        from rapidocr_onnxruntime import RapidOCR

        engine = RapidOCR()
        res, _ = engine(str(img_path))
        if res:
            extracted: list[str] = [
                str(item[1]).strip()
                for item in res
                if len(item) > 1 and item[1]
            ]
            if extracted:
                return " ".join(extracted).strip()
    except (ImportError, TypeError):
        pass
    except Exception:
        # Graceful fallback on unexpected engine execution failures
        pass

    # 2. Try PyTesseract
    try:
        import pytesseract

        with Image.open(img_path) as img:
            text = pytesseract.image_to_string(img)
            if text and text.strip():
                return text.strip()
    except (ImportError, TypeError):
        pass
    except Exception:
        pass

    # 3. Try System Tesseract CLI
    tess_bin = shutil.which("tesseract")
    if tess_bin:
        try:
            proc = subprocess.run(
                [tess_bin, str(img_path), "stdout"],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except Exception:
            pass

    return ""
