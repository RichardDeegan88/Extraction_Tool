"""Extraction service layer.

Bridges DataAccess operations to the actual PDF extraction pipeline.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from extraction_tool.contracts.extraction import ExtractionRequest, ExtractionResult
from extraction_tool.contracts.results import DocumentMetadata
from extraction_tool.extraction.normalization import (
    build_page_line_map,
    clean_and_mark_pages,
    compute_quality_report,
    find_headings,
    format_quality_header,
    sanitize,
)
from extraction_tool.extraction.ocr import ocr_page, page_needs_ocr
from extraction_tool.extraction.pdf import count_pages, extract_pages_any
from extraction_tool.repositories.filesystem import FilesystemRepository


class ExtractionService:
    """Service for PDF extraction operations."""

    def __init__(self, repo: FilesystemRepository) -> None:
        """Initialize with a filesystem repository."""
        self._repo = repo

    def extract_pdf(
        self,
        request: ExtractionRequest,
        out_path: Path | None = None,
        no_header: bool = False,
    ) -> ExtractionResult:
        """Extract text from a PDF.

        Args:
            request: Extraction parameters.
            out_path: Optional explicit output path.
            no_header: If True, omit quality header.

        Returns:
            ExtractionResult with extracted text and quality metrics.
        """
        pdf_path = os.path.abspath(request.pdf_path)
        if not Path(pdf_path).is_file():
            return ExtractionResult(
                success=False,
                errors=[f"PDF not found: {pdf_path}"],
            )

        total_pages = count_pages(pdf_path)
        pages, method = extract_pages_any(pdf_path, total_pages)

        method, ocr_needed = self._run_ocr(pages, pdf_path, request, method)

        cleaned = clean_and_mark_pages("\f".join(pages), ocr_pages=set(ocr_needed))
        sanitized, removed_count = sanitize(cleaned)
        if removed_count:
            print(f"  stripped {removed_count} invisible/bidi/tag characters "
                  f"(possible hidden content or PDF artifacts)", file=sys.stderr)

        report = compute_quality_report(sanitized, ocr_needed, total_pages)
        meta = self._repo.extract_pdf_metadata(pdf_path)
        for _k in ("title", "author"):
            if meta.get(_k):
                meta[_k] = sanitize(meta[_k])[0]

        header = ("" if no_header
                  else format_quality_header(report, Path(pdf_path).name,
                                             DocumentMetadata(**meta)))

        output_text = header + sanitized

        if out_path:
            self._repo.atomic_write_text(out_path, output_text)
            self._write_index(out_path, pdf_path, sanitized)

        return ExtractionResult(
            success=True,
            text=output_text,
            pages_found=report.pages_found,
            pages_expected=report.pages_expected,
            page_count_ok=report.page_count_ok,
            sequence_ok=report.sequence_ok,
            ocr_pages=report.ocr_pages,
            ocr_pct=report.ocr_pct,
            words=report.words,
            words_per_page=report.words_per_page,
            method=method,
            errors=[],
        )

    def _run_ocr(
        self,
        pages: list[str],
        pdf_path: str,
        request: ExtractionRequest,
        method: str,
    ) -> tuple[str, list[int]]:
        """OCR pages that need it; return (method, ocr_page_numbers)."""
        ocr_needed = [
            i + 1 for i, p in enumerate(pages)
            if request.force_ocr or page_needs_ocr(p, request.ocr_threshold)
        ]
        if not ocr_needed:
            return method, ocr_needed

        print(f"  {len(ocr_needed)} of {len(pages)} page(s) need OCR "
              f"(scanned/no text layer) — this is the slow part, ~1-3s/page",
              file=sys.stderr)
        ocr_failed: list[int] = []
        with tempfile.TemporaryDirectory(prefix="preprocess_pdf_ocr_") as workdir:
            for n, page_num in enumerate(ocr_needed, start=1):
                print(f"    OCR page {page_num} ({n}/{len(ocr_needed)})...",
                      file=sys.stderr, end="\r")
                try:
                    pages[page_num - 1] = ocr_page(
                        pdf_path, page_num, request.ocr_dpi,
                        request.ocr_lang, workdir,
                        deskew=not request.no_deskew,
                    )
                except Exception as e:
                    ocr_failed.append(page_num)
                    print(f"\n  [warn] OCR failed on page {page_num}: "
                          f"{type(e).__name__}: {e}", file=sys.stderr)
            print(file=sys.stderr)
        if ocr_failed:
            print(f"  [warn] OCR failed on {len(ocr_failed)} page(s): "
                  f"{', '.join(map(str, ocr_failed))}. Left as extracted text, "
                  f"not tagged [OCR]; check these pages against the PDF.",
                  file=sys.stderr)
            failed_set = set(ocr_failed)
            ocr_needed = [p for p in ocr_needed if p not in failed_set]
        method = f"{method} + tesseract OCR ({len(ocr_needed)} page(s))"
        return method, ocr_needed

    def _write_index(self, out_path: Path, pdf_path: str, sanitized: str) -> None:
        """Write the heading index file alongside the output text."""
        index_path = out_path.with_suffix(out_path.suffix + ".index")
        headings = find_headings(sanitized)
        page_line_map = build_page_line_map(sanitized)
        index_lines = []
        for h in headings:
            page = 0
            for p, ln in page_line_map.items():
                if ln <= h.line_number:
                    page = p
            index_lines.append(
                f"  line {h.line_number}, page {page}: {h.text} [{h.level}]"
            )
        self._repo.atomic_write_text(
            index_path,
            f"HEADING INDEX for {Path(pdf_path).name}\n\n"
            + "\n".join(index_lines) + "\n",
        )
