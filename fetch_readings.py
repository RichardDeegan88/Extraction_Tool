#!/usr/bin/env python3
"""Thin wrapper: re-exports from extraction_tool package for backward compatibility."""

from __future__ import annotations

import sys
from pathlib import Path

# Make the src package importable when running this wrapper directly.
try:
    import extraction_tool  # noqa: F401
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent / "src"))

from extraction_tool.adapters.cli import fetch_readings_main
from extraction_tool.contracts.readings import (
    PlannedReading,
    ReadingOccurrence,
    ReadingPlan,
    ReadingRequest,
    ReadingResult,
)
from extraction_tool.repositories.filesystem import FilesystemRepository
from extraction_tool.repositories.http import HttpReadingRepository
from extraction_tool.services.reading_service import ReadingService

__all__ = [
    "PlannedReading",
    "ReadingOccurrence",
    "ReadingPlan",
    "ReadingRequest",
    "ReadingResult",
    "_SafeRedirectHandler",
    "_TEXT_URL_RE",
    "_atomic_write_text",
    "_decode_body",
    "_is_public_host",
    "_trim_url",
    "acquire_readings",
    "categorise",
    "classify_failure",
    "fetch_readings_main",
    "fetch_url",
    "html_to_text_builtin",
    "looks_gated",
    "page_looks_gated",
    "plan_readings",
    "safe_filename",
    "strip_hidden",
]

_fs_repo = FilesystemRepository()
_http_repo = HttpReadingRepository()
_service = ReadingService(_http_repo, _fs_repo)

categorise = _http_repo.categorise
safe_filename = _http_repo.safe_filename
strip_hidden = _http_repo.strip_hidden
fetch_url = _http_repo.fetch_url
_is_public_host = _http_repo._is_public_host
_SafeRedirectHandler = _http_repo._SafeRedirectHandler
_OPENER = _http_repo._OPENER
classify_failure = _http_repo.classify_failure

looks_gated = ReadingService._looks_gated
page_looks_gated = ReadingService._page_looks_gated
html_to_text_builtin = ReadingService._html_to_text_builtin
_decode_body = ReadingService._decode_body
_trim_url = ReadingService._trim_url
_TEXT_URL_RE = ReadingService._TEXT_URL_RE
_atomic_write_text = _fs_repo.atomic_write_text

plan_readings = _service.plan_readings
acquire_readings = _service.acquire_readings


if __name__ == "__main__":
    try:
        fetch_readings_main()
    except BrokenPipeError:
        sys.exit(0)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
