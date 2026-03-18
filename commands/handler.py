"""Command dispatch contract."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from commands.registry import COMMAND_ARITY, SUPPORTED_COMMANDS

CommandResult = str | int | None


class CommandError(Exception):
    """Base error raised by the command layer."""


class UnknownCommandError(CommandError):
    """Raised when a command name is not supported."""


class WrongNumberOfArgumentsError(CommandError):
    """Raised when a command receives an unexpected number of arguments."""


class StorageProtocol(Protocol):
    """Shared storage interface used by the command layer."""

    def set(self, key: str, value: str) -> None: ...

    def get(self, key: str) -> str | None: ...

    def delete(self, key: str) -> bool: ...

    def expire(self, key: str, seconds: int) -> bool: ...


DispatchHandler = Callable[[list[str], StorageProtocol], CommandResult]


def _validate_command(command: list[str]) -> tuple[str, list[str]]:
    """Validate the parsed command and return its normalized name and args."""
    if not command or not command[0]:
        raise CommandError("empty command")

    command_name = command[0].upper()
    if command_name not in SUPPORTED_COMMANDS:
        raise UnknownCommandError(f"unknown command '{command_name}'")

    if len(command) != COMMAND_ARITY[command_name]:
        raise WrongNumberOfArgumentsError(
            f"wrong number of arguments for '{command_name}' command"
        )

    return command_name, command[1:]


def _handle_set(args: list[str], storage: StorageProtocol) -> str:
    key, value = args
    storage.set(key, value)
    return "OK"


def _handle_get(args: list[str], storage: StorageProtocol) -> str | None:
    key = args[0]
    return storage.get(key)


def _handle_del(args: list[str], storage: StorageProtocol) -> int:
    key = args[0]
    return int(storage.delete(key))


DISPATCH_TABLE: dict[str, DispatchHandler] = {
    "SET": _handle_set,
    "GET": _handle_get,
    "DEL": _handle_del,
}


def handle_command(command: list[str], storage: StorageProtocol) -> CommandResult:
    """Dispatch a parsed command and return a plain command result."""
    command_name, args = _validate_command(command)
    handler = DISPATCH_TABLE[command_name]
    return handler(args, storage)
