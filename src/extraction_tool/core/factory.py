"""Factory for constructing DataAccess instances."""

from typing import Any

from extraction_tool.core.access import DataAccess
from extraction_tool.core.protocols import Algorithm, Authorizer, Cache, Repository


class DataAccessFactory:
    """Constructs DataAccess instances with explicit dependencies.

    The factory is responsible for composition only. It is NOT responsible
    for performing HTTP operations or implementing extraction algorithms.
    """

    def __init__(
        self,
        repository: Repository[Any],
        cache: Cache,
        algorithm: Algorithm | None = None,
        authorizer: Authorizer | None = None,
    ) -> None:
        """Initialize the factory with dependencies.

        Args:
            repository: The repository implementation to use.
            cache: The cache implementation to use.
            algorithm: Optional algorithm implementation.
            authorizer: Optional authorizer for access control.
        """
        self._repository = repository
        self._cache = cache
        self._algorithm = algorithm
        self._authorizer = authorizer

    def create(self) -> DataAccess:
        """Create and return a configured DataAccess instance."""
        return DataAccess(
            repository=self._repository,
            cache=self._cache,
            algorithm=self._algorithm,
            authorizer=self._authorizer,
        )
