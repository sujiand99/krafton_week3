import pytest

from protocol.resp_encoder import (
    encode_bulk_string,
    encode_error,
    encode_integer,
    encode_simple_string,
)
from protocol.resp_parser import RespError, RespStreamParser, parse_resp


def test_parse_resp_returns_uppercase_command_tokens() -> None:
    command = parse_resp(b"*3\r\n$3\r\nset\r\n$1\r\na\r\n$1\r\n1\r\n")
    assert command == ["SET", "a", "1"]


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


def test_parse_resp_rejects_non_resp_input() -> None:
    with pytest.raises(RespError):
        parse_resp(b"SET a 1\r\n")


def test_resp_encoder_formats_expected_responses() -> None:
    assert encode_simple_string("OK") == "+OK\r\n"
    assert encode_bulk_string("123") == "$3\r\n123\r\n"
    assert encode_bulk_string(None) == "$-1\r\n"
    assert encode_integer(1) == ":1\r\n"
    assert encode_error("unknown command") == "-ERR unknown command\r\n"
