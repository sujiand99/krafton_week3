"""Command dispatch contract."""

from __future__ import annotations

from typing import Protocol, TypeAlias

from commands.registry import COMMAND_ARITY, SUPPORTED_COMMANDS

RESPScalar: TypeAlias = str | int | None
CommandResult: TypeAlias = RESPScalar | list[RESPScalar]


class CommandError(Exception):
    """Base command-layer error."""


class UnknownCommandError(CommandError):
    """Raised when a command name is not supported."""


class WrongNumberOfArgumentsError(CommandError):
    """Raised when a command receives the wrong number of arguments."""


class StorageProtocol(Protocol):
    """Shared storage interface used by the command layer."""

    def set(self, key: str, value: str) -> None: ...

    def get(self, key: str) -> str | None: ...

    def delete(self, key: str) -> bool: ...

    def expire(self, key: str, seconds: int) -> bool: ...


def _validate_command(command: list[str]) -> tuple[str, list[str]]:
    if not command or not command[0]:
        raise CommandError("empty command")

    name = command[0].upper()
    if name not in SUPPORTED_COMMANDS:
        raise UnknownCommandError(f"unknown command '{name}'")

    expected_arity = COMMAND_ARITY[name]
    if len(command) != expected_arity:
        raise WrongNumberOfArgumentsError(
            f"wrong number of arguments for '{name}' command"
        )

    return name, command[1:]


def handle_command(command: list[str], storage: StorageProtocol) -> CommandResult:
    """Dispatch a parsed command and return a pure command result."""
    name, args = _validate_command(command)

    if name == "SET":
        key, value = args
        storage.set(key, value)
        return "OK"

    if name == "GET":
        key = args[0]
        return storage.get(key)

    if name == "DEL":
        key = args[0]
        return 1 if storage.delete(key) else 0

    raise UnknownCommandError(f"unknown command '{name}'")
