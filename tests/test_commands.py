from commands.handler import handle_command
from storage.engine import StorageEngine


def test_set_and_get_command_flow() -> None:
    storage = StorageEngine()

    assert handle_command(["SET", "a", "123"], storage) == "+OK\r\n"
    assert handle_command(["GET", "a"], storage) == "$3\r\n123\r\n"


def test_get_missing_key_returns_nil_bulk_string() -> None:
    storage = StorageEngine()

    assert handle_command(["GET", "missing"], storage) == "$-1\r\n"


def test_del_returns_integer_reply() -> None:
    storage = StorageEngine()
    handle_command(["SET", "a", "1"], storage)

    assert handle_command(["DEL", "a"], storage) == ":1\r\n"
    assert handle_command(["DEL", "a"], storage) == ":0\r\n"


def test_unknown_command_returns_error() -> None:
    storage = StorageEngine()

    assert handle_command(["HELLO"], storage) == "-ERR unknown command\r\n"


def test_wrong_number_of_arguments_returns_error() -> None:
    storage = StorageEngine()

    assert handle_command(["SET", "a"], storage) == "-ERR wrong number of arguments\r\n"
    assert handle_command(["GET"], storage) == "-ERR wrong number of arguments\r\n"
    assert (
        handle_command(["DEL", "a", "extra"], storage)
        == "-ERR wrong number of arguments\r\n"
    )
