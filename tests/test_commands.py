from __future__ import annotations

import pytest

from commands.handler import (
    CommandError,
    UnknownCommandError,
    WrongNumberOfArgumentsError,
    handle_command,
)
from storage.engine import StorageEngine


def test_set_and_get_command_flow() -> None:
    storage = StorageEngine()

    assert handle_command(["SET", "a", "123"], storage) == "OK"
    assert handle_command(["GET", "a"], storage) == "123"


def test_get_missing_key_returns_none() -> None:
    storage = StorageEngine()

    assert handle_command(["GET", "missing"], storage) is None


def test_del_returns_integer_result() -> None:
    storage = StorageEngine()
    handle_command(["SET", "a", "1"], storage)

    assert handle_command(["DEL", "a"], storage) == 1
    assert handle_command(["DEL", "a"], storage) == 0


def test_expire_returns_integer_result() -> None:
    storage = StorageEngine()
    handle_command(["SET", "a", "1"], storage)

    assert handle_command(["EXPIRE", "a", "10"], storage) == 1
    assert handle_command(["EXPIRE", "missing", "10"], storage) == 0


def test_ttl_returns_integer_result() -> None:
    storage = StorageEngine()
    handle_command(["SET", "a", "1"], storage)

    assert handle_command(["TTL", "a"], storage) == -1
    assert handle_command(["TTL", "missing"], storage) == -2


def test_handle_command_normalizes_command_case() -> None:
    storage = StorageEngine()

    assert handle_command(["set", "a", "123"], storage) == "OK"
    assert handle_command(["get", "a"], storage) == "123"
    assert handle_command(["ttl", "a"], storage) == -1


def test_expire_normalizes_command_and_option_case() -> None:
    storage = StorageEngine()
    handle_command(["SET", "a", "123"], storage)

    assert handle_command(["expire", "a", "10", "nx"], storage) == 1
    assert handle_command(["EXPIRE", "a", "20", "xx"], storage) == 1


def test_unknown_command_raises_error() -> None:
    storage = StorageEngine()

    with pytest.raises(UnknownCommandError, match="unknown command 'HELLO'"):
        handle_command(["HELLO"], storage)


@pytest.mark.parametrize(
    "command",
    [
        [],
        [""],
    ],
)
def test_empty_command_raises_error(command: list[str]) -> None:
    storage = StorageEngine()

    with pytest.raises(CommandError, match="empty command"):
        handle_command(command, storage)


def test_wrong_number_of_arguments_raises_error() -> None:
    storage = StorageEngine()

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'SET' command",
    ):
        handle_command(["SET", "a"], storage)

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'GET' command",
    ):
        handle_command(["GET"], storage)

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'DEL' command",
    ):
        handle_command(["DEL", "a", "extra"], storage)

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'EXPIRE' command",
    ):
        handle_command(["EXPIRE", "a"], storage)

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'EXPIRE' command",
    ):
        handle_command(["EXPIRE", "a", "10", "NX", "extra"], storage)

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'TTL' command",
    ):
        handle_command(["TTL"], storage)


def test_expire_requires_integer_seconds() -> None:
    storage = StorageEngine()

    with pytest.raises(CommandError, match="EXPIRE seconds must be an integer"):
        handle_command(["EXPIRE", "a", "ten"], storage)


def test_expire_rejects_unknown_option() -> None:
    storage = StorageEngine()

    with pytest.raises(CommandError, match="unsupported EXPIRE option 'BAD'"):
        handle_command(["EXPIRE", "a", "10", "BAD"], storage)


def test_reserve_seat_returns_success_and_status_array() -> None:
    storage = StorageEngine()

    assert handle_command(["RESERVE_SEAT", "concert", "A-1", "user-1", "30"], storage) == [
        1,
        "HELD",
        "user-1",
        30,
    ]
    assert handle_command(["SEAT_STATUS", "concert", "A-1"], storage) == [
        "HELD",
        "user-1",
        30,
    ]


def test_reserve_seat_returns_current_holder_for_conflict() -> None:
    storage = StorageEngine()
    handle_command(["RESERVE_SEAT", "concert", "A-1", "user-1", "30"], storage)

    assert handle_command(["RESERVE_SEAT", "concert", "A-1", "user-2", "30"], storage) == [
        0,
        "HELD",
        "user-1",
        30,
    ]


def test_confirm_and_release_seat_return_status_arrays() -> None:
    storage = StorageEngine()
    handle_command(["RESERVE_SEAT", "concert", "A-1", "user-1", "30"], storage)

    assert handle_command(["CONFIRM_SEAT", "concert", "A-1", "user-1"], storage) == [
        1,
        "CONFIRMED",
        "user-1",
        -1,
    ]
    assert handle_command(["RELEASE_SEAT", "concert", "A-1", "user-1"], storage) == [
        0,
        "CONFIRMED",
        "user-1",
        -1,
    ]


def test_force_confirm_seat_overrides_current_redis_state() -> None:
    storage = StorageEngine()

    assert handle_command(["FORCE_CONFIRM_SEAT", "concert", "A-1", "user-2"], storage) == [
        1,
        "CONFIRMED",
        "user-2",
        -1,
    ]
    assert handle_command(["SEAT_STATUS", "concert", "A-1"], storage) == [
        "CONFIRMED",
        "user-2",
        -1,
    ]


def test_release_seat_returns_available_on_success() -> None:
    storage = StorageEngine()
    handle_command(["RESERVE_SEAT", "concert", "A-1", "user-1", "30"], storage)

    assert handle_command(["RELEASE_SEAT", "concert", "A-1", "user-1"], storage) == [
        1,
        "AVAILABLE",
        None,
        -1,
    ]


def test_reserve_seat_requires_integer_and_positive_ttl() -> None:
    storage = StorageEngine()

    with pytest.raises(CommandError, match="RESERVE_SEAT ttl_seconds must be an integer"):
        handle_command(["RESERVE_SEAT", "concert", "A-1", "user-1", "abc"], storage)

    with pytest.raises(
        CommandError,
        match="RESERVE_SEAT ttl_seconds must be a positive integer",
    ):
        handle_command(["RESERVE_SEAT", "concert", "A-1", "user-1", "0"], storage)


def test_seat_commands_validate_arity() -> None:
    storage = StorageEngine()

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'RESERVE_SEAT' command",
    ):
        handle_command(["RESERVE_SEAT", "concert", "A-1", "user-1"], storage)

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'CONFIRM_SEAT' command",
    ):
        handle_command(["CONFIRM_SEAT", "concert", "A-1"], storage)

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'FORCE_CONFIRM_SEAT' command",
    ):
        handle_command(["FORCE_CONFIRM_SEAT", "concert", "A-1"], storage)

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'RELEASE_SEAT' command",
    ):
        handle_command(["RELEASE_SEAT", "concert", "A-1"], storage)

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'SEAT_STATUS' command",
    ):
        handle_command(["SEAT_STATUS", "concert"], storage)


def test_join_queue_and_queue_position_return_arrays() -> None:
    storage = StorageEngine()

    assert handle_command(["JOIN_QUEUE", "concert", "user-1"], storage) == [1, 1, 1]
    assert handle_command(["JOIN_QUEUE", "concert", "user-2"], storage) == [1, 2, 2]
    assert handle_command(["JOIN_QUEUE", "concert", "user-1"], storage) == [0, 1, 2]
    assert handle_command(["QUEUE_POSITION", "concert", "user-2"], storage) == [2, 2]
    assert handle_command(["QUEUE_POSITION", "concert", "user-3"], storage) == [-1, 2]


def test_pop_queue_returns_user_and_remaining_length() -> None:
    storage = StorageEngine()
    handle_command(["JOIN_QUEUE", "concert", "user-1"], storage)
    handle_command(["JOIN_QUEUE", "concert", "user-2"], storage)

    assert handle_command(["POP_QUEUE", "concert"], storage) == ["user-1", 1]
    assert handle_command(["POP_QUEUE", "concert"], storage) == ["user-2", 0]
    assert handle_command(["POP_QUEUE", "concert"], storage) == [None, 0]


def test_queue_commands_validate_arity() -> None:
    storage = StorageEngine()

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'JOIN_QUEUE' command",
    ):
        handle_command(["JOIN_QUEUE", "concert"], storage)

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'QUEUE_POSITION' command",
    ):
        handle_command(["QUEUE_POSITION", "concert"], storage)

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'POP_QUEUE' command",
    ):
        handle_command(["POP_QUEUE", "concert", "extra"], storage)

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'LEAVE_QUEUE' command",
    ):
        handle_command(["LEAVE_QUEUE", "concert"], storage)

    with pytest.raises(
        WrongNumberOfArgumentsError,
        match="wrong number of arguments for 'PEEK_QUEUE' command",
    ):
        handle_command(["PEEK_QUEUE", "concert", "extra"], storage)


def test_leave_queue_and_peek_queue_return_arrays() -> None:
    storage = StorageEngine()
    handle_command(["JOIN_QUEUE", "concert", "user-1"], storage)
    handle_command(["JOIN_QUEUE", "concert", "user-2"], storage)
    handle_command(["JOIN_QUEUE", "concert", "user-3"], storage)

    assert handle_command(["PEEK_QUEUE", "concert"], storage) == ["user-1", 3]
    assert handle_command(["LEAVE_QUEUE", "concert", "user-2"], storage) == [1, 2, 2]
    assert handle_command(["LEAVE_QUEUE", "concert", "missing"], storage) == [0, -1, 2]
    assert handle_command(["PEEK_QUEUE", "concert"], storage) == ["user-1", 2]
