"""Command dispatch contract."""

from __future__ import annotations

from typing import Protocol, TypeAlias

from commands.registry import COMMAND_ARITY, SUPPORTED_COMMANDS

RESPScalar: TypeAlias = str | int | None
CommandResult: TypeAlias = RESPScalar | list[RESPScalar]
EXPIRE_OPTIONS = frozenset({"NX", "XX", "GT", "LT"})


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

    def expire(self, key: str, seconds: int, option: str | None = None) -> bool: ...

    def ttl(self, key: str) -> int: ...


def _validate_command(command: list[str]) -> tuple[str, list[str]]:
    if not command or not command[0]:
        raise CommandError("empty command")

    name = command[0].upper()
    if name not in SUPPORTED_COMMANDS:
        raise UnknownCommandError(f"unknown command '{name}'")

    expected_min_arity, expected_max_arity = COMMAND_ARITY[name]
    if not expected_min_arity <= len(command) <= expected_max_arity:
        raise WrongNumberOfArgumentsError(
            f"wrong number of arguments for '{name}' command"
        )

    return name, command[1:]


def _parse_expire_arguments(args: list[str]) -> tuple[str, int, str | None]:
    key, raw_seconds, *rest = args

    try:
        seconds = int(raw_seconds)
    except ValueError as exc:
        raise CommandError("EXPIRE seconds must be an integer") from exc

    option = None
    if rest:
        option = rest[0].upper()
        if option not in EXPIRE_OPTIONS:
            raise CommandError(f"unsupported EXPIRE option '{rest[0]}'")

    return key, seconds, option


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

    if name == "EXPIRE":
        key, seconds, option = _parse_expire_arguments(args)
        return 1 if storage.expire(key, seconds, option) else 0

    if name == "TTL":
        key = args[0]
        return storage.ttl(key)

    raise UnknownCommandError(f"unknown command '{name}'")
