"""FastAPI adapter for the Extraction Toolkit.

FastAPI is optional. This adapter translates HTTP requests into domain service
calls. Route handlers contain only transport logic: request reception,
Pydantic validation, rate limiting, service invocation, response serialization.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request  # type: ignore[import-not-found]
from slowapi import Limiter  # type: ignore[import-not-found]
from slowapi.util import get_remote_address  # type: ignore[import-not-found]

from extraction_tool.contracts.extraction import ExtractionRequest, ExtractionResult
from extraction_tool.contracts.readings import ReadingRequest, ReadingResult
from extraction_tool.services.extraction_service import ExtractionService
from extraction_tool.services.reading_service import ReadingService

limiter = Limiter(key_func=get_remote_address)


class ExtractionRouter:
    """FastAPI router builder for extraction operations.

    The adapter translates HTTP requests into domain service calls.
    It does not use DataAccess for domain operations; DataAccess is reserved
    for generic CRUD orchestration per theDAF pattern.
    """

    def __init__(
        self,
        extraction_service: ExtractionService,
        reading_service: ReadingService,
        limiter: Limiter | None = None,
    ) -> None:
        """Initialize with domain services.

        Args:
            extraction_service: Service for PDF extraction operations.
            reading_service: Service for reading acquisition operations.
            limiter: Optional rate limiter instance.
        """
        self._extraction_service = extraction_service
        self._reading_service = reading_service
        self._limiter = limiter
        self._router = APIRouter(prefix="/extraction", tags=["extraction"])
        self._setup_routes()

    def _limit(self, rate: str) -> Any:
        """Apply rate limiting if limiter is configured."""
        if self._limiter is not None:
            return self._limiter.limit(rate)
        def noop(func: Any) -> Any:
            return func
        return noop

    def _setup_routes(self) -> None:
        @self._router.post("/extract", response_model=ExtractionResult)
        @self._limit("10/minute")  # type: ignore[untyped-decorator]
        def extract_pdf(request: Request, info: ExtractionRequest) -> ExtractionResult:
            try:
                return self._extraction_service.extract_pdf(info)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e)) from None

        @self._router.post("/readings", response_model=ReadingResult)
        @self._limit("10/minute")  # type: ignore[untyped-decorator]
        def acquire_readings(request: Request, info: ReadingRequest) -> ReadingResult:
            try:
                return self._reading_service.acquire_readings(info)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e)) from None

    def get_router(self) -> APIRouter:
        """Return the configured FastAPI router."""
        return self._router
