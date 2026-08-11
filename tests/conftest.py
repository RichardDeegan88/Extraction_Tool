"""Shared pytest fixtures for the ACSC Reading Toolkit test suite."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# Reuse the source-tree scripts as modules.
import preprocess_pdf
import fetch_readings


@pytest.fixture
def has_pdftotext() -> bool:
    return shutil.which("pdftotext") is not None


@pytest.fixture
def has_tesseract() -> bool:
    return shutil.which("tesseract") is not None


def _write_pdf(path: Path, page_drawers: list) -> Path:
    """Create a PDF at *path* by calling one drawing function per page."""
    c = canvas.Canvas(str(path), pagesize=letter)
    for drawer in page_drawers:
        drawer(c)
        c.showPage()
    c.save()
    return path


@pytest.fixture
def simple_pdf(tmp_path: Path) -> Path:
    """A 5-page typeset PDF with simple body text."""
    path = tmp_path / "simple.pdf"

    def page(n: int):
        def draw(c):
            c.drawString(72, 720, f"This is page {n} of the sample document.")
            c.drawString(72, 680, "Body paragraph one with several words.")
            c.drawString(72, 660, "Body paragraph two continues the text.")
        return draw

    return _write_pdf(path, [page(i) for i in range(1, 6)])


@pytest.fixture
def header_footer_pdf(tmp_path: Path) -> Path:
    """A 6-page PDF with a repeated running header and footer page numbers."""
    path = tmp_path / "headers.pdf"

    def page(n: int):
        def draw(c):
            c.drawString(72, 760, "Sample Treatise")          # running header
            c.drawString(72, 720, f"Real content on page {n}.")
            c.drawString(72, 680, "Additional body text here.")
            c.drawString(500, 50, str(n))                      # bare page number
        return draw

    return _write_pdf(path, [page(i) for i in range(1, 7)])


@pytest.fixture
def outline_pdf(tmp_path: Path) -> Path:
    """A PDF with an embedded outline (bookmarks)."""
    path = tmp_path / "outline.pdf"

    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:  # pragma: no cover
        pytest.skip("pypdf not installed")

    writer = PdfWriter()
    for i in range(1, 4):
        page = writer.add_blank_page(width=612, height=792)
        # pypdf does not make adding visible text trivial; the outline is the point.

    writer.add_outline_item("BOOK ONE", 0)
    writer.add_outline_item("Chapter 1: The Beginning", 0)
    writer.add_outline_item("Chapter 2: The Middle", 1)
    writer.add_outline_item("BOOK TWO", 2)

    with open(path, "wb") as f:
        writer.write(f)
    return path


@pytest.fixture
def junk_metadata_pdf(tmp_path: Path) -> Path:
    """A PDF whose /Title metadata is clearly an internal asset ID."""
    path = tmp_path / "junk_meta.pdf"

    try:
        from pypdf import PdfWriter
    except ImportError:  # pragma: no cover
        pytest.skip("pypdf not installed")

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": "imageItem8901132859708402734#_#9780190265687",
                         "/Author": "A. N. Author"})
    with open(path, "wb") as f:
        writer.write(f)
    return path
