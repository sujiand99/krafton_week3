"""Storage engine contract."""

from __future__ import annotations


class StorageEngine:
    """In-memory key-value storage."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, key: str, value: str) -> None:
        self._store[key] = value

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def delete(self, key: str) -> bool:
        return self._store.pop(key, None) is not None

    def expire(self, key: str, seconds: int) -> bool:
        return False
