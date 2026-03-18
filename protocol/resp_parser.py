"""RESP request parser helpers."""

from __future__ import annotations

RESP_LINE_ENDING = b"\r\n"


class ProtocolError(ValueError):
    """Raised when a RESP request is malformed."""


class IncompleteRESPError(ProtocolError):
    """Raised when a RESP request is incomplete and needs more bytes."""


def _read_line(message: bytes, start: int) -> tuple[bytes, int]:
    """Read a CRLF-terminated RESP line starting at the given index."""
    end = message.find(RESP_LINE_ENDING, start)
    if end == -1:
        raise IncompleteRESPError("incomplete RESP line")

    return message[start:end], end + len(RESP_LINE_ENDING)


def _parse_array_header(message: bytes, start: int) -> tuple[int, int]:
    """Parse the leading RESP array header and return item count + next index."""
    if start >= len(message):
        raise IncompleteRESPError("missing RESP array header")
    if message[start : start + 1] != b"*":
        raise ProtocolError("expected RESP array")

    raw_count, next_index = _read_line(message, start + 1)
    try:
        count = int(raw_count)
    except ValueError as exc:
        raise ProtocolError("invalid RESP array length") from exc

    if count < 0:
        raise ProtocolError("negative RESP array length is not supported")

    return count, next_index


def _parse_bulk_string(message: bytes, start: int) -> tuple[str, int]:
    """Parse one RESP bulk string and return its text value + next index."""
    if start >= len(message):
        raise IncompleteRESPError("missing RESP bulk string header")
    if message[start : start + 1] != b"$":
        raise ProtocolError("expected RESP bulk string")

    raw_length, next_index = _read_line(message, start + 1)
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise ProtocolError("invalid RESP bulk string length") from exc

    if length < 0:
        raise ProtocolError("null bulk strings are not supported in requests")

    data_end = next_index + length
    trailer_end = data_end + len(RESP_LINE_ENDING)
    if trailer_end > len(message):
        raise IncompleteRESPError("incomplete RESP bulk string payload")
    if message[data_end:trailer_end] != RESP_LINE_ENDING:
        raise ProtocolError("RESP bulk string payload must end with CRLF")

    payload = message[next_index:data_end]
    try:
        token = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError("RESP bulk string must be valid UTF-8") from exc

    return token, trailer_end


def parse_resp_frame(message: bytes) -> tuple[list[str], int]:
    """Parse one RESP command from the start of a bytes buffer."""
    item_count, next_index = _parse_array_header(message, 0)
    command: list[str] = []

    for _ in range(item_count):
        token, next_index = _parse_bulk_string(message, next_index)
        command.append(token)

    return command, next_index


def parse_resp(message: bytes) -> list[str]:
    """Parse exactly one RESP command into a token list."""
    command, consumed = parse_resp_frame(message)
    if consumed != len(message):
        raise ProtocolError("unexpected trailing data after RESP request")
    return command
