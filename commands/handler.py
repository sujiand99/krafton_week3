"""Command dispatch contract."""

from __future__ import annotations

from typing import Protocol

from commands.registry import SUPPORTED_COMMANDS
from protocol.resp_encoder import (
    encode_bulk_string,
    encode_error,
    encode_integer,
    encode_simple_string,
)


class StorageProtocol(Protocol):
    """Shared storage interface used by the command layer."""

    def set(self, key: str, value: str) -> None: ...

    def get(self, key: str) -> str | None: ...

    def delete(self, key: str) -> bool: ...

    def expire(self, key: str, seconds: int) -> bool: ...


def handle_command(command: list[str], storage: StorageProtocol) -> str:
    """Dispatch a parsed command and return a RESP-encoded response string."""
    if not command:
        return encode_error("unknown command")

    name = command[0].upper()
    if name not in SUPPORTED_COMMANDS:
        return encode_error("unknown command")

    if name == "SET":
        if len(command) != 3:
            return encode_error("wrong number of arguments")

        storage.set(command[1], command[2])
        return encode_simple_string("OK")

    if name == "GET":
        if len(command) != 2:
            return encode_error("wrong number of arguments")

        return encode_bulk_string(storage.get(command[1]))

    if name == "DEL":
        if len(command) != 2:
            return encode_error("wrong number of arguments")

        return encode_integer(1 if storage.delete(command[1]) else 0)

    return encode_error("unknown command")
