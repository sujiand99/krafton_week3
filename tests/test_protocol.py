"""Tests for RESP parsing and encoding helpers."""

from __future__ import annotations

import pytest

from protocol.resp_encoder import (
    encode_bulk_string,
    encode_error,
    encode_integer,
    encode_simple_string,
)
from protocol.resp_parser import (
    IncompleteRESPError,
    ProtocolError,
    RespStreamParser,
    parse_resp,
    parse_resp_frame,
)


def test_parse_resp_parses_get_request() -> None:
    payload = b"*2\r\n$3\r\nGET\r\n$1\r\na\r\n"
    assert parse_resp(payload) == ["GET", "a"]


def test_parse_resp_parses_set_request() -> None:
    payload = b"*3\r\n$3\r\nSET\r\n$1\r\na\r\n$2\r\n10\r\n"
    assert parse_resp(payload) == ["SET", "a", "10"]


def test_parse_resp_preserves_original_command_case() -> None:
    payload = b"*3\r\n$3\r\nset\r\n$1\r\na\r\n$1\r\n1\r\n"
    assert parse_resp(payload) == ["set", "a", "1"]


def test_parse_resp_frame_returns_consumed_length_for_buffered_requests() -> None:
    payload = (
        b"*2\r\n$3\r\nGET\r\n$1\r\na\r\n"
        b"*2\r\n$3\r\nDEL\r\n$1\r\na\r\n"
    )
    command, consumed = parse_resp_frame(payload)

    assert command == ["GET", "a"]
    assert consumed == len(b"*2\r\n$3\r\nGET\r\n$1\r\na\r\n")


def test_stream_parser_buffers_partial_payloads() -> None:
    parser = RespStreamParser()

    assert parser.feed_data(b"*2\r\n$3\r\nGET\r\n$1\r") == []
    assert parser.feed_data(b"\na\r\n") == [["GET", "a"]]


def test_stream_parser_reads_multiple_commands_from_one_chunk() -> None:
    parser = RespStreamParser()

    commands = parser.feed_data(
        b"*2\r\n$3\r\nGET\r\n$1\r\na\r\n*2\r\n$3\r\nDEL\r\n$1\r\na\r\n"
    )

    assert commands == [["GET", "a"], ["DEL", "a"]]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"GET a", "expected RESP array"),
        (b"*2\r\n3\r\nGET\r\n$1\r\na\r\n", "expected RESP bulk string"),
        (b"*2\r\n$X\r\nGET\r\n$1\r\na\r\n", "invalid RESP bulk string length"),
        (b"*2\r\n$3\r\nGET\r\n$2\r\na\r\n", "incomplete RESP bulk string payload"),
    ],
)
def test_parse_resp_rejects_malformed_requests(payload: bytes, message: str) -> None:
    with pytest.raises(ProtocolError, match=message):
        parse_resp(payload)


def test_parse_resp_rejects_trailing_data() -> None:
    payload = (
        b"*2\r\n$3\r\nGET\r\n$1\r\na\r\n"
        b"*2\r\n$3\r\nDEL\r\n$1\r\na\r\n"
    )
    with pytest.raises(ProtocolError, match="unexpected trailing data"):
        parse_resp(payload)


def test_parse_resp_frame_reports_incomplete_request() -> None:
    with pytest.raises(IncompleteRESPError, match="missing RESP bulk string header"):
        parse_resp_frame(b"*2\r\n$3\r\nGET\r\n")


def test_encode_simple_string_returns_resp_simple_string() -> None:
    assert encode_simple_string("OK") == "+OK\r\n"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("123", "$3\r\n123\r\n"),
        ("", "$0\r\n\r\n"),
        ("ga", "$2\r\nga\r\n"),
        (None, "$-1\r\n"),
    ],
)
def test_encode_bulk_string_handles_text_and_null(
    message: str | None,
    expected: str,
) -> None:
    assert encode_bulk_string(message) == expected


def test_encode_bulk_string_counts_utf8_bytes() -> None:
    message = "\uac00"
    assert encode_bulk_string(message) == "$3\r\n\uac00\r\n"


def test_encode_integer_returns_resp_integer() -> None:
    assert encode_integer(1) == ":1\r\n"
    assert encode_integer(0) == ":0\r\n"


def test_encode_error_returns_resp_error() -> None:
    assert encode_error("unknown command") == "-ERR unknown command\r\n"


@pytest.mark.parametrize("bad_message", ["bad\r\nvalue", "bad\nvalue"])
def test_single_line_resp_values_reject_newlines(bad_message: str) -> None:
    with pytest.raises(ValueError, match="must not contain CR or LF"):
        encode_simple_string(bad_message)

    with pytest.raises(ValueError, match="must not contain CR or LF"):
        encode_error(bad_message)
