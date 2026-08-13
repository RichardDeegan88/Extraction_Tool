"""Extraction Toolkit — deterministic document extraction and reading acquisition."""

from extraction_tool.core.access import DataAccess
from extraction_tool.core.errors import (
    AlgorithmError,
    AuthorizationError,
    CacheError,
    DataAccessError,
    ExtractionError,
    NotFoundError,
    RepositoryError,
    ValidationError,
)
from extraction_tool.core.factory import DataAccessFactory

__version__ = "0.2.0"

__all__ = [
    "DataAccess",
    "DataAccessFactory",
    "DataAccessError",
    "ExtractionError",
    "NotFoundError",
    "ValidationError",
    "RepositoryError",
    "CacheError",
    "AlgorithmError",
    "AuthorizationError",
]
