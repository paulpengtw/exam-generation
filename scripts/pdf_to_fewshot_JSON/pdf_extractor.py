"""Extract text and page images from a PDF exam file."""

from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path

import pdfplumber


def extract_pages(pdf_path: Path) -> list[dict]:
    """
    Extract text and render images for all pages in a PDF.

    Returns a list of dicts, one per page:
        {
            "page_number": int (1-indexed),
            "text": str,
            "image_b64": str | None  # base64-encoded PNG, or None if pdftoppm unavailable
        }
    """
    pages = []

    # Extract text with pdfplumber
    text_by_page: dict[int, str] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text_by_page[i + 1] = page.extract_text() or ""

    # Render pages to PNG images using pdftoppm
    images_by_page = _render_pages(pdf_path)

    for page_num in range(1, len(text_by_page) + 1):
        pages.append({
            "page_number": page_num,
            "text": text_by_page[page_num],
            "image_b64": images_by_page.get(page_num),
        })

    return pages


def _render_pages(pdf_path: Path) -> dict[int, str]:
    """
    Use pdftoppm to render each PDF page as a PNG image.
    Returns dict mapping page_number -> base64-encoded PNG string.
    Returns empty dict if pdftoppm is not available.
    """
    images: dict[int, str] = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        output_prefix = Path(tmpdir) / "page"
        try:
            result = subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-r", "150",  # 150 DPI — good balance of clarity vs. token cost
                    str(pdf_path),
                    str(output_prefix),
                ],
                capture_output=True,
                check=True,
            )
        except FileNotFoundError:
            # pdftoppm not installed; skip image rendering
            return {}
        except subprocess.CalledProcessError as e:
            print(f"Warning: pdftoppm failed: {e.stderr.decode()}")
            return {}

        # Collect rendered PNG files (named page-1.png, page-2.png, ... or page-01.png etc.)
        png_files = sorted(Path(tmpdir).glob("page-*.png"))
        for png_file in png_files:
            # Extract page number from filename like "page-001.png" or "page-1.png"
            stem = png_file.stem  # e.g. "page-001"
            page_num = int(stem.split("-")[-1])
            with open(png_file, "rb") as f:
                images[page_num] = base64.b64encode(f.read()).decode("utf-8")

    return images


def group_pages(pages: list[dict], batch_size: int = 2) -> list[list[dict]]:
    """Group pages into batches for LLM processing."""
    batches = []
    for i in range(0, len(pages), batch_size):
        batches.append(pages[i : i + batch_size])
    return batches
