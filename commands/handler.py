"""Command dispatch contract."""

from __future__ import annotations

from typing import Protocol


class StorageProtocol(Protocol):
    """Shared storage interface used by the command layer."""

    def set(self, key: str, value: str) -> None: ...

    def get(self, key: str) -> str | None: ...

    def delete(self, key: str) -> bool: ...

    def expire(self, key: str, seconds: int) -> bool: ...


def handle_command(command: list[str], storage: StorageProtocol) -> str:
    """Dispatch a parsed command and return a RESP-encoded response string."""
    raise NotImplementedError(
        "Command dispatch will be implemented in the command feature branch."
    )
