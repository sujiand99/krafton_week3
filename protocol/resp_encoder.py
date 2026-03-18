"""RESP response encoder helpers."""

from __future__ import annotations


def encode_simple_string(message: str) -> str:
    """Encode a RESP simple string."""
    raise NotImplementedError(
        "RESP encoding will be implemented in the server/RESP feature branch."
    )


def encode_bulk_string(message: str | None) -> str:
    """Encode a RESP bulk string or null bulk string."""
    raise NotImplementedError(
        "RESP encoding will be implemented in the server/RESP feature branch."
    )


def encode_integer(value: int) -> str:
    """Encode a RESP integer."""
    raise NotImplementedError(
        "RESP encoding will be implemented in the server/RESP feature branch."
    )


def encode_error(message: str) -> str:
    """Encode a RESP error."""
    raise NotImplementedError(
        "RESP encoding will be implemented in the server/RESP feature branch."
    )
