"""RESP response encoder helpers."""

from __future__ import annotations


def encode_simple_string(message: str) -> str:
    """Encode a RESP simple string."""
    return f"+{message}\r\n"


def encode_bulk_string(message: str | None) -> str:
    """Encode a RESP bulk string or null bulk string."""
    if message is None:
        return "$-1\r\n"
    return f"${len(message.encode('utf-8'))}\r\n{message}\r\n"


def encode_integer(value: int) -> str:
    """Encode a RESP integer."""
    return f":{value}\r\n"


def encode_error(message: str) -> str:
    """Encode a RESP error."""
    return f"-ERR {message}\r\n"
