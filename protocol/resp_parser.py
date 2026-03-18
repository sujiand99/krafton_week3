"""RESP request parser contract."""

from __future__ import annotations


def parse_resp(message: bytes) -> list[str]:
    """Parse a RESP request into a token list such as ['SET', 'key', 'value']."""
    raise NotImplementedError(
        "RESP parsing will be implemented in the server/RESP feature branch."
    )
