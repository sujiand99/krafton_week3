"""Storage engine contract."""

from __future__ import annotations


class StorageEngine:
    """In-memory key-value storage with an optional TTL extension point."""

    def set(self, key: str, value: str) -> None:
        raise NotImplementedError(
            "Storage logic will be implemented in the storage feature branch."
        )

    def get(self, key: str) -> str | None:
        raise NotImplementedError(
            "Storage logic will be implemented in the storage feature branch."
        )

    def delete(self, key: str) -> bool:
        raise NotImplementedError(
            "Storage logic will be implemented in the storage feature branch."
        )

    def expire(self, key: str, seconds: int) -> bool:
        raise NotImplementedError(
            "TTL logic will be implemented if the team extends the MVP."
        )
