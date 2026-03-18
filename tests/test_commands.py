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
