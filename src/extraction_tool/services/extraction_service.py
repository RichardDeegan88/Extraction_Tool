"""Extraction service layer.

Bridges DataAccess operations to the actual PDF extraction pipeline.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from extraction_tool.contracts.extraction import ExtractionRequest, ExtractionResult
from extraction_tool.contracts.results import DocumentMetadata, QualityReport
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

    def _sanitize_metadata(self, meta: dict[str, str]) -> dict[str, str]:
        """Sanitize title/author metadata strings."""
        for key in ("title", "author"):
            if meta.get(key):
                meta[key] = sanitize(meta[key])[0]
        return meta

    def _build_output(
        self,
        sanitized: str,
        report: QualityReport,
        meta: dict[str, str],
        pdf_path: str,
        no_header: bool,
    ) -> tuple[str, str]:
        """Return (output_text, header) for the extraction result."""
        header = (
            ""
            if no_header
            else format_quality_header(
                report, Path(pdf_path).name, DocumentMetadata(**meta)
            )
        )
        return header + sanitized, header

    def _prepare_text(
        self, pages: list[str], ocr_needed: list[int]
    ) -> str:
        """Clean, mark, and sanitize extracted/ocr'd page text."""
        cleaned = clean_and_mark_pages("\f".join(pages), ocr_pages=set(ocr_needed))
        sanitized, removed_count = sanitize(cleaned)
        if removed_count:
            print(f"  stripped {removed_count} invisible/bidi/tag characters "
                  f"(possible hidden content or PDF artifacts)", file=sys.stderr)
        return sanitized

    def _persist_outputs(
        self,
        out_path: Path,
        output_text: str,
        pdf_path: str,
        sanitized: str,
        header: str,
    ) -> None:
        """Write the extracted text file and heading index."""
        self._repo.atomic_write_text(out_path, output_text)
        self._write_index(
            out_path, pdf_path, sanitized, line_offset=header.count("\n")
        )

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
        sanitized = self._prepare_text(pages, ocr_needed)

        report = compute_quality_report(sanitized, ocr_needed, total_pages)
        meta = self._sanitize_metadata(self._repo.extract_pdf_metadata(pdf_path))
        output_text, header = self._build_output(
            sanitized, report, meta, pdf_path, no_header
        )

        if out_path:
            self._persist_outputs(out_path, output_text, pdf_path, sanitized, header)

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

    def _format_outline_entries(
        self,
        outline: list[tuple[int, int, str]],
        page_line_map: dict[int, int],
        line_offset: int,
    ) -> list[str]:
        """Format embedded PDF outline entries as index lines."""
        lines: list[str] = []
        for page, depth, title in outline:
            clean_title = sanitize(title)[0]
            line_no = page_line_map.get(page)
            loc = (
                f"line {line_no + line_offset}"
                if line_no else f"page {page} (no marker)"
            )
            lines.append(f"{'  ' * depth}[p.{page}] {loc}: {clean_title}")
        return lines

    def _format_detected_headings(
        self,
        sanitized: str,
        page_line_map: dict[int, int],
        line_offset: int,
    ) -> list[str]:
        """Format text-pattern headings as index lines."""
        lines: list[str] = []
        for h in find_headings(sanitized):
            page = 0
            for p, ln in page_line_map.items():
                if ln <= h.line_number:
                    page = p
            lines.append(
                f"  line {h.line_number + line_offset}, page {page}: "
                f"{h.text} [{h.level}]"
            )
        return lines

    def _write_index(
        self,
        out_path: Path,
        pdf_path: str,
        sanitized: str,
        line_offset: int = 0,
    ) -> None:
        """Write the heading index file alongside the output text.

        Prefers the PDF's own embedded outline (bookmarks) when present,
        falling back to text-pattern heading detection. Line numbers are
        adjusted to match the final output file (including any quality
        header that was prepended).
        """
        index_path = out_path.with_suffix(out_path.suffix + ".index")
        page_line_map = build_page_line_map(sanitized)
        outline = self._repo.extract_pdf_outline(pdf_path)

        if outline:
            source_note = "SOURCE: the PDF's own embedded outline (bookmarks)."
            index_lines = self._format_outline_entries(
                outline, page_line_map, line_offset
            )
        else:
            source_note = (
                "SOURCE: text-pattern detection. This PDF has NO embedded "
                "outline, so headings were found by matching text patterns."
            )
            index_lines = self._format_detected_headings(
                sanitized, page_line_map, line_offset
            )

        self._repo.atomic_write_text(
            index_path,
            f"HEADING INDEX for {Path(pdf_path).name}\n\n"
            f"{source_note}\n\n"
            + "\n".join(index_lines) + "\n",
        )
