"""Pydantic contract models for data access operations."""

from extraction_tool.contracts.extraction import (
    ExtractionRequest,
    ExtractionResult,
    OcrDetectionResult,
    PageValidationResult,
)
from extraction_tool.contracts.query import (
    DeleteInfo,
    MutationResult,
    PostInfo,
    PutInfo,
    QueryInfo,
    QueryResult,
)
from extraction_tool.contracts.readings import (
    ReadingRequest,
    ReadingResult,
    UrlCategory,
)
from extraction_tool.contracts.results import (
    DependencyCheckResult,
    DocumentMetadata,
    HeadingEntry,
    QualityReport,
)

__all__ = [
    "QueryInfo",
    "PostInfo",
    "PutInfo",
    "DeleteInfo",
    "QueryResult",
    "MutationResult",
    "ExtractionRequest",
    "ExtractionResult",
    "PageValidationResult",
    "OcrDetectionResult",
    "ReadingRequest",
    "ReadingResult",
    "UrlCategory",
    "QualityReport",
    "DocumentMetadata",
    "HeadingEntry",
    "DependencyCheckResult",
]
