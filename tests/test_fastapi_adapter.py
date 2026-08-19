"""Tests for the FastAPI adapter: transport behavior and rate limiting.

The adapter is a thin transport layer: it must receive requests, validate them
with Pydantic, enforce rate limits, invoke the domain service, and serialize the
response. It must not contain extraction, repository, cache, or algorithm logic.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("slowapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from extraction_tool.adapters.fastapi import ExtractionRouter
from extraction_tool.contracts.extraction import ExtractionRequest, ExtractionResult
from extraction_tool.contracts.readings import ReadingRequest, ReadingResult


class StubExtractionService:
    """Records delegation; returns a valid ExtractionResult."""

    def __init__(self) -> None:
        self.calls = 0

    def extract_pdf(self, request: ExtractionRequest) -> ExtractionResult:
        self.calls += 1
        return ExtractionResult(
            success=True,
            text="--- PAGE 1 ---\nHi",
            pages_found=1,
            pages_expected=1,
            page_count_ok=True,
            sequence_ok=True,
            ocr_pages=0,
            ocr_pct=0.0,
            words=2,
            words_per_page=2.0,
            method="pdftotext -layout",
            errors=[],
        )


class StubReadingService:
    """Records delegation; returns a valid ReadingResult."""

    def __init__(self) -> None:
        self.calls = 0

    def acquire_readings(self, request: ReadingRequest) -> ReadingResult:
        self.calls += 1
        return ReadingResult(
            success=True,
            fetched=["readings/a.txt"],
            manual_capture=[],
            downloaded_pdfs=[],
            skipped=[],
            errors=[],
        )


def _make_client(limiter: Limiter | None) -> TestClient:
    app = FastAPI()
    if limiter is not None:
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    router = ExtractionRouter(
        extraction_service=StubExtractionService(),
        reading_service=StubReadingService(),
        limiter=limiter,
    )
    app.include_router(router.get_router())
    return TestClient(app)


def test_extract_endpoint_delegates_to_service() -> None:
    client = _make_client(None)
    resp = client.post("/extraction/extract", json={"pdf_path": "/tmp/x.pdf"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["text"] == "--- PAGE 1 ---\nHi"


def test_readings_endpoint_delegates_to_service() -> None:
    client = _make_client(None)
    resp = client.post("/extraction/readings", json={"source": "syllabus.pdf"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["fetched"] == ["readings/a.txt"]


def test_invalid_body_is_rejected_by_pydantic() -> None:
    client = _make_client(None)
    # pdf_path is required; omitting it must fail boundary validation.
    resp = client.post("/extraction/extract", json={"ocr_lang": "eng"})
    assert resp.status_code == 422


def test_extract_endpoint_enforces_rate_limit() -> None:
    limiter = Limiter(key_func=get_remote_address)
    client = _make_client(limiter)
    payload = {"pdf_path": "/tmp/x.pdf"}
    # 10 requests allowed per minute, the 11th is throttled.
    for _ in range(10):
        assert client.post("/extraction/extract", json=payload).status_code == 200
    assert client.post("/extraction/extract", json=payload).status_code == 429
