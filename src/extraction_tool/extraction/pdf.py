"""PDF extraction module.

Handles PDF acquisition, text extraction, OCR fallback, metadata, and outline.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys

_PDF_PAGE_NUM = re.compile(
    r"^\s*(?:\d{1,4}|"
    r"(?=[ivxlcdm])m{0,4}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3}))"
    r"\s*$",
    re.IGNORECASE)
_PDF_HYPHEN_WRAP = re.compile(r"([^\W\d_])-\n([^\W\d_])")
_WORD_RE = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


def count_pages(pdf_path: str) -> int:
    """Count pages in a PDF using pdfinfo or pypdf."""
    if shutil.which("pdfinfo"):
        try:
            result = subprocess.run(
                ["pdfinfo", pdf_path], capture_output=True, text=True, timeout=30,
            )
            for line in result.stdout.splitlines():
                    if line.startswith("Pages:"):
                        return int(line.split(":")[1].strip())
        except Exception as e:
            print(f"  [debug] pdfinfo failed for {pdf_path}, falling back to pypdf: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
    try:
        import pypdf
        with open(pdf_path, "rb") as f:
            return len(pypdf.PdfReader(f).pages)
    except Exception:
        return 0


def extract_pages_pdftotext(pdf_path: str, total_pages: int) -> list[str] | None:
    """Preferred: preserves per-page layout via form-feed separators."""
    if not shutil.which("pdftotext"):
        return None
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0 and result.stdout:
            pages = result.stdout.split("\f")
            if total_pages:
                while len(pages) > total_pages and not pages[-1].strip():
                    pages.pop()
            else:
                while pages and not pages[-1].strip():
                    pages.pop()
            return pages
    except Exception as e:
        print(f"  [warn] pdftotext failed: {type(e).__name__}: {e}", file=sys.stderr)
    return None


def extract_pages_pypdf(pdf_path: str) -> list[str] | None:
    """Fallback: extract text per page via pypdf."""
    try:
        import pypdf
    except ImportError:
        return None
    try:
        pages = []
        with open(pdf_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    pages.append("")
        return pages
    except Exception as e:
        print(f"  [warn] pypdf failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def extract_pages_any(pdf_path: str, total_pages: int) -> tuple[list[str], str]:
    """Try each non-OCR extractor in order."""
    pages = extract_pages_pdftotext(pdf_path, total_pages)
    if pages:
        return pages, "pdftotext -layout"
    pages = extract_pages_pypdf(pdf_path)
    if pages:
        return pages, "pypdf"
    print("  [warn] no text-layer extractor available or succeeded — "
          "every page will need OCR", file=sys.stderr)
    return [""] * max(total_pages, 1), "none (OCR required for all pages)"
