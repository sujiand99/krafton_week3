"""RESP request parser contract."""

from __future__ import annotations


class RespError(ValueError):
    """Raised when an incoming RESP message is invalid."""


class _IncompleteRESP(ValueError):
    """Internal signal used while buffering socket data."""


def parse_resp(message: bytes) -> list[str]:
    """Parse a RESP request into tokens such as ['SET', 'key', 'value']."""
    parser = RespStreamParser()
    commands = parser.feed_data(message)

    if parser.buffered:
        raise RespError("incomplete RESP message")

    if len(commands) != 1:
        raise RespError("expected exactly one command")

    return commands[0]


class RespStreamParser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    @property
    def buffered(self) -> bytes:
        return bytes(self._buffer)

    def feed_data(self, chunk: bytes) -> list[list[str]]:
        self._buffer.extend(chunk)
        commands: list[list[str]] = []

        while self._buffer:
            try:
                command, consumed = self._parse_one(self._buffer)
            except _IncompleteRESP:
                break

            commands.append(command)
            del self._buffer[:consumed]

        return commands

    def reset(self) -> None:
        self._buffer.clear()

    @staticmethod
    def _parse_one(buffer: bytearray) -> tuple[list[str], int]:
        if not buffer:
            raise _IncompleteRESP

        if buffer[0] != ord("*"):
            raise RespError("expected RESP array")

        item_count_raw, cursor = _read_line(buffer, 1)

        try:
            item_count = int(item_count_raw)
        except ValueError as exc:
            raise RespError("invalid array length") from exc

        if item_count < 0:
            raise RespError("invalid array length")

        parts: list[str] = []

        for _ in range(item_count):
            if cursor >= len(buffer):
                raise _IncompleteRESP

            if buffer[cursor] != ord("$"):
                raise RespError("expected bulk string")

            bulk_length_raw, cursor = _read_line(buffer, cursor + 1)

            try:
                bulk_length = int(bulk_length_raw)
            except ValueError as exc:
                raise RespError("invalid bulk string length") from exc

            if bulk_length < 0:
                raise RespError("null bulk string is not supported")

            bulk_end = cursor + bulk_length
            if len(buffer) < bulk_end + 2:
                raise _IncompleteRESP

            if bytes(buffer[bulk_end : bulk_end + 2]) != b"\r\n":
                raise RespError("invalid bulk string terminator")

            parts.append(bytes(buffer[cursor:bulk_end]).decode("utf-8"))
            cursor = bulk_end + 2

        if parts:
            parts[0] = parts[0].upper()

        return parts, cursor


def _read_line(buffer: bytearray, start: int) -> tuple[str, int]:
    terminator_index = bytes(buffer).find(b"\r\n", start)
    if terminator_index == -1:
        raise _IncompleteRESP

    return bytes(buffer[start:terminator_index]).decode("utf-8"), terminator_index + 2
