"""In-memory cache implementation."""

from typing import Any


class MemoryCache:
    """In-memory cache implementation."""

    def __init__(self) -> None:
        """Initialize the in-memory cache."""
        self._cache: dict[str, Any] = {}

    async def get(self, key: str) -> Any | None:
        """Retrieve a value from cache."""
        return self._cache.get(key)

    async def set(self, key: str, value: Any) -> None:
        """Store a value in cache."""
        self._cache[key] = value

    async def delete(self, key: str) -> None:
        """Delete a value from cache."""
        if key in self._cache:
            del self._cache[key]

    async def clear(self) -> None:
        """Clear all values from cache."""
        self._cache.clear()

    async def has(self, key: str) -> bool:
        """Check if a key exists in cache."""
        return key in self._cache
