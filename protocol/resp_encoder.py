"""RESP response encoder helpers."""

from __future__ import annotations

RESP_LINE_ENDING = "\r\n"


def _validate_single_line(message: str) -> None:
    """Reject RESP line values that would break the wire format."""
    if "\r" in message or "\n" in message:
        raise ValueError("RESP line values must not contain CR or LF characters.")


def encode_simple_string(message: str) -> str:
    """Encode a RESP simple string."""
    _validate_single_line(message)
    return f"+{message}{RESP_LINE_ENDING}"


def encode_bulk_string(message: str | None) -> str:
    """Encode a RESP bulk string or null bulk string."""
    if message is None:
        return f"$-1{RESP_LINE_ENDING}"

    length = len(message.encode("utf-8"))
    return f"${length}{RESP_LINE_ENDING}{message}{RESP_LINE_ENDING}"


def encode_integer(value: int) -> str:
    """Encode a RESP integer."""
    return f":{value}{RESP_LINE_ENDING}"


def encode_error(message: str) -> str:
    """Encode a RESP error."""
    _validate_single_line(message)
    return f"-ERR {message}{RESP_LINE_ENDING}"
