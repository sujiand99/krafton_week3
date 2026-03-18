"""Command handler tests."""

from __future__ import annotations

import unittest

from commands.handler import (
    CommandError,
    UnknownCommandError,
    WrongNumberOfArgumentsError,
    handle_command,
)


class FakeStorage:
    """Minimal storage double for command handler tests."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.calls: list[tuple[str, object, object | None]] = []

    def set(self, key: str, value: str) -> None:
        self.calls.append(("set", key, value))
        self.data[key] = value

    def get(self, key: str) -> str | None:
        self.calls.append(("get", key, None))
        return self.data.get(key)

    def delete(self, key: str) -> bool:
        self.calls.append(("delete", key, None))
        return self.data.pop(key, None) is not None

    def expire(self, key: str, seconds: int) -> bool:
        self.calls.append(("expire", key, seconds))
        return key in self.data and seconds >= 0


class CommandHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.storage = FakeStorage()

    def test_set_returns_ok_and_stores_value(self) -> None:
        result = handle_command(["SET", "mykey", "123"], self.storage)

        self.assertEqual("OK", result)
        self.assertEqual("123", self.storage.get("mykey"))

    def test_get_returns_existing_value(self) -> None:
        self.storage.set("mykey", "123")

        result = handle_command(["GET", "mykey"], self.storage)

        self.assertEqual("123", result)
        self.assertEqual(("get", "mykey", None), self.storage.calls[-1])

    def test_get_returns_none_for_missing_key(self) -> None:
        result = handle_command(["GET", "missing"], self.storage)

        self.assertIsNone(result)
        self.assertEqual(("get", "missing", None), self.storage.calls[-1])

    def test_del_returns_one_for_existing_key(self) -> None:
        self.storage.set("mykey", "123")

        result = handle_command(["DEL", "mykey"], self.storage)

        self.assertEqual(1, result)
        self.assertIsNone(self.storage.get("mykey"))

    def test_del_returns_zero_for_missing_key(self) -> None:
        result = handle_command(["DEL", "missing"], self.storage)

        self.assertEqual(0, result)
        self.assertEqual(("delete", "missing", None), self.storage.calls[-1])

    def test_command_name_is_case_insensitive(self) -> None:
        result = handle_command(["set", "mykey", "123"], self.storage)

        self.assertEqual("OK", result)
        self.assertEqual("123", self.storage.get("mykey"))

    def test_set_overwrites_existing_value(self) -> None:
        handle_command(["SET", "mykey", "123"], self.storage)

        result = handle_command(["SET", "mykey", "456"], self.storage)

        self.assertEqual("OK", result)
        self.assertEqual("456", self.storage.data["mykey"])

    def test_set_preserves_value_spacing(self) -> None:
        result = handle_command(["SET", "message", "hello world"], self.storage)

        self.assertEqual("OK", result)
        self.assertEqual("hello world", self.storage.data["message"])

    def test_set_uses_storage_with_exact_key_and_value(self) -> None:
        handle_command(["SET", "mykey", "123"], self.storage)

        self.assertEqual(("set", "mykey", "123"), self.storage.calls[-1])

    def test_del_uses_storage_delete(self) -> None:
        self.storage.set("mykey", "123")

        handle_command(["DEL", "mykey"], self.storage)

        self.assertEqual(("delete", "mykey", None), self.storage.calls[-1])

    def test_unknown_command_raises_specific_error(self) -> None:
        with self.assertRaises(UnknownCommandError):
            handle_command(["PING"], self.storage)

    def test_unknown_command_message_uses_normalized_name(self) -> None:
        with self.assertRaisesRegex(UnknownCommandError, "unknown command 'PING'"):
            handle_command(["ping"], self.storage)

    def test_wrong_argument_count_raises_specific_error(self) -> None:
        with self.assertRaises(WrongNumberOfArgumentsError):
            handle_command(["GET"], self.storage)

    def test_set_with_missing_value_raises_argument_error(self) -> None:
        with self.assertRaisesRegex(
            WrongNumberOfArgumentsError,
            "wrong number of arguments for 'SET' command",
        ):
            handle_command(["SET", "mykey"], self.storage)

    def test_get_with_extra_argument_raises_argument_error(self) -> None:
        with self.assertRaisesRegex(
            WrongNumberOfArgumentsError,
            "wrong number of arguments for 'GET' command",
        ):
            handle_command(["GET", "mykey", "extra"], self.storage)

    def test_del_with_extra_argument_raises_argument_error(self) -> None:
        with self.assertRaisesRegex(
            WrongNumberOfArgumentsError,
            "wrong number of arguments for 'DEL' command",
        ):
            handle_command(["DEL", "mykey", "extra"], self.storage)

    def test_empty_command_raises_command_error(self) -> None:
        with self.assertRaises(CommandError):
            handle_command([], self.storage)

    def test_blank_command_name_raises_command_error(self) -> None:
        with self.assertRaisesRegex(CommandError, "empty command"):
            handle_command([""], self.storage)


if __name__ == "__main__":
    unittest.main()
