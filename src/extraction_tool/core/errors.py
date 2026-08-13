"""Core error types for the Extraction Toolkit."""


class DataAccessError(Exception):
    """Base exception for data access operations."""
    pass


class ExtractionError(DataAccessError):
    """Raised when an extraction operation fails."""
    pass


class NotFoundError(DataAccessError):
    """Raised when a requested resource is not found."""
    pass


class ValidationError(DataAccessError):
    """Raised when input validation fails."""
    pass


class RepositoryError(DataAccessError):
    """Raised when a repository operation fails."""
    pass


class CacheError(DataAccessError):
    """Raised when a cache operation fails."""
    pass


class AlgorithmError(DataAccessError):
    """Raised when an algorithm execution fails."""
    pass


class AuthorizationError(DataAccessError):
    """Raised when a user is not authorized to access a resource."""
    pass
