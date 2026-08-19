#!/usr/bin/env python3
"""
preprocess_pdf.py — turn large/scanned PDF books into clean, grep-able .txt
files so they never have to be re-ingested whole.

Compatibility wrapper: re-exports from extraction_tool package.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the src package importable when running this wrapper directly.
try:
    import extraction_tool  # noqa: F401
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent / "src"))

from extraction_tool.adapters.cli import preprocess_pdf_main
from extraction_tool.extraction.normalization import (  # noqa: F401
    _normalize_author_for_filename,
    _numeral_value,
    _roman_to_int,
    build_metadata_filename,
    clean_and_mark_pages,
    compute_quality_report,
    find_headings,
    sanitize,
)
from extraction_tool.extraction.ocr import (  # noqa: F401
    _installed_tesseract_langs,
)
from extraction_tool.extraction.ocr import (
    _validate_ocr_lang as _ocr_validate_ocr_lang,
)
from extraction_tool.repositories.filesystem import FilesystemRepository
from extraction_tool.services.extraction_service import ExtractionService


def _validate_ocr_lang(lang: str) -> tuple[bool, list[str]]:
    return _ocr_validate_ocr_lang(lang, installed_langs_fn=_installed_tesseract_langs)


def extract_pdf_metadata(pdf_path: str) -> dict:
    repo = FilesystemRepository()
    return repo.extract_pdf_metadata(pdf_path)


def extract_pdf_outline(pdf_path: str) -> list:
    repo = FilesystemRepository()
    return repo.extract_pdf_outline(pdf_path)


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    repo = FilesystemRepository()
    repo.atomic_write_text(path, text, encoding)


def process_one_pdf(pdf_path: Path, out_path: Path, args) -> dict:
    """Run the full pipeline on one PDF. Returns a stats dict."""
    repo = FilesystemRepository()
    service = ExtractionService(repo)
    from extraction_tool.contracts.extraction import ExtractionRequest
    request = ExtractionRequest(
        pdf_path=str(pdf_path),
        ocr_lang=getattr(args, "ocr_lang", "eng"),
        ocr_dpi=getattr(args, "ocr_dpi", 300),
        ocr_threshold=getattr(args, "ocr_threshold", 8),
        force_ocr=getattr(args, "force_ocr", False),
        no_deskew=getattr(args, "no_deskew", False),
    )
    result = service.extract_pdf(
        request, out_path=out_path, no_header=getattr(args, "no_header", False)
    )
    return {
        "pages": result.pages_found,
        "page_count_ok": result.page_count_ok,
        "sequence_ok": result.sequence_ok,
        "ocr_pages": result.ocr_pages,
        "ocr_pct": result.ocr_pct,
        "text": result.text,
        "method": result.method,
    }


def _version() -> str:
    version_file = Path(__file__).with_name("VERSION")
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    return "unknown"


if __name__ == "__main__":
    try:
        preprocess_pdf_main()
    except BrokenPipeError:
        sys.exit(0)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
