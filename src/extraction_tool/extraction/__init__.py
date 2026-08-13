"""Extraction module package."""

from extraction_tool.extraction.html import (
    extract_with_bs4,
)
from extraction_tool.extraction.normalization import (
    build_metadata_filename,
    build_page_line_map,
    clean_and_mark_pages,
    compute_quality_report,
    find_headings,
    format_quality_header,
    sanitize,
    suppress_running_headers,
)
from extraction_tool.extraction.ocr import (
    ocr_page,
    page_needs_ocr,
)
from extraction_tool.extraction.pdf import (
    count_pages,
    extract_pages_any,
    extract_pages_pdftotext,
    extract_pages_pypdf,
)
from extraction_tool.extraction.validation import (
    validate_page_sequence,
)

__all__ = [
    "extract_pages_any",
    "extract_pages_pypdf",
    "extract_pages_pdftotext",
    "count_pages",
    "sanitize",
    "clean_and_mark_pages",
    "build_metadata_filename",
    "find_headings",
    "build_page_line_map",
    "suppress_running_headers",
    "compute_quality_report",
    "format_quality_header",
    "page_needs_ocr",
    "ocr_page",
    "validate_page_sequence",
    "extract_with_bs4",
]
