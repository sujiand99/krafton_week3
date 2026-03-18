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

    class SeatStatusProtocol(Protocol):
        state: str
        user_id: str | None
        ttl: int

    def set(self, key: str, value: str) -> None: ...

    def get(self, key: str) -> str | None: ...

    def delete(self, key: str) -> bool: ...

    def expire(self, key: str, seconds: int, option: str | None = None) -> bool: ...

    def ttl(self, key: str) -> int: ...

    def reserve_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
        hold_seconds: int,
    ) -> tuple[bool, SeatStatusProtocol]: ...

    def confirm_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
    ) -> tuple[bool, SeatStatusProtocol]: ...

    def release_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
    ) -> tuple[bool, SeatStatusProtocol]: ...

    def seat_status(self, event_id: str, seat_id: str) -> SeatStatusProtocol: ...

    def join_queue(self, event_id: str, user_id: str) -> tuple[bool, int, int]: ...

    def queue_position(self, event_id: str, user_id: str) -> tuple[int, int]: ...

    def pop_queue(self, event_id: str) -> tuple[str | None, int]: ...

    def leave_queue(self, event_id: str, user_id: str) -> tuple[bool, int, int]: ...

    def peek_queue(self, event_id: str) -> tuple[str | None, int]: ...


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


def _parse_reserve_arguments(args: list[str]) -> tuple[str, str, str, int]:
    event_id, seat_id, user_id, raw_hold_seconds = args

    try:
        hold_seconds = int(raw_hold_seconds)
    except ValueError as exc:
        raise CommandError("RESERVE_SEAT ttl_seconds must be an integer") from exc

    if hold_seconds <= 0:
        raise CommandError("RESERVE_SEAT ttl_seconds must be a positive integer")

    return event_id, seat_id, user_id, hold_seconds


def _seat_operation_result(
    success: bool,
    status: StorageProtocol.SeatStatusProtocol,
) -> list[RESPScalar]:
    return [1 if success else 0, status.state, status.user_id, status.ttl]


def _seat_status_result(status: StorageProtocol.SeatStatusProtocol) -> list[RESPScalar]:
    return [status.state, status.user_id, status.ttl]


def _queue_join_result(joined: bool, position: int, queue_length: int) -> list[RESPScalar]:
    return [1 if joined else 0, position, queue_length]


def _queue_position_result(position: int, queue_length: int) -> list[RESPScalar]:
    return [position, queue_length]


def _queue_pop_result(user_id: str | None, queue_length: int) -> list[RESPScalar]:
    return [user_id, queue_length]


def _queue_leave_result(removed: bool, position: int, queue_length: int) -> list[RESPScalar]:
    return [1 if removed else 0, position, queue_length]


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

    if name == "RESERVE_SEAT":
        event_id, seat_id, user_id, hold_seconds = _parse_reserve_arguments(args)
        success, status = storage.reserve_seat(event_id, seat_id, user_id, hold_seconds)
        return _seat_operation_result(success, status)

    if name == "CONFIRM_SEAT":
        event_id, seat_id, user_id = args
        success, status = storage.confirm_seat(event_id, seat_id, user_id)
        return _seat_operation_result(success, status)

    if name == "RELEASE_SEAT":
        event_id, seat_id, user_id = args
        success, status = storage.release_seat(event_id, seat_id, user_id)
        return _seat_operation_result(success, status)

    if name == "SEAT_STATUS":
        event_id, seat_id = args
        return _seat_status_result(storage.seat_status(event_id, seat_id))

    if name == "JOIN_QUEUE":
        event_id, user_id = args
        joined, position, queue_length = storage.join_queue(event_id, user_id)
        return _queue_join_result(joined, position, queue_length)

    if name == "QUEUE_POSITION":
        event_id, user_id = args
        position, queue_length = storage.queue_position(event_id, user_id)
        return _queue_position_result(position, queue_length)

    if name == "POP_QUEUE":
        event_id = args[0]
        user_id, queue_length = storage.pop_queue(event_id)
        return _queue_pop_result(user_id, queue_length)

    if name == "LEAVE_QUEUE":
        event_id, user_id = args
        removed, position, queue_length = storage.leave_queue(event_id, user_id)
        return _queue_leave_result(removed, position, queue_length)

    if name == "PEEK_QUEUE":
        event_id = args[0]
        user_id, queue_length = storage.peek_queue(event_id)
        return _queue_pop_result(user_id, queue_length)

    raise UnknownCommandError(f"unknown command '{name}'")
