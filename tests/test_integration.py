"""Integration-style tests for the server/protocol flow."""

from __future__ import annotations

from typing import Any

import pytest

from server import server as server_module


class FakeConnection:
    """Minimal socket-like object for exercising the server loop."""

    def __init__(self, recv_chunks: list[bytes]) -> None:
        self._recv_chunks = list(recv_chunks)
        self.sent: list[bytes] = []
        self.closed = False

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.closed = True

    def recv(self, _: int) -> bytes:
        if self._recv_chunks:
            return self._recv_chunks.pop(0)
        return b""

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)


class DummyStorage:
    """Simple placeholder storage object for server tests."""



def test_encode_command_result_maps_command_types_to_resp() -> None:
    assert server_module.encode_command_result(["SET", "a", "1"], "OK") == "+OK\r\n"
    assert server_module.encode_command_result(["GET", "a"], "10") == "$2\r\n10\r\n"
    assert server_module.encode_command_result(["GET", "missing"], None) == "$-1\r\n"
    assert server_module.encode_command_result(["DEL", "a"], 1) == ":1\r\n"



def test_encode_command_result_rejects_unsupported_command() -> None:
    with pytest.raises(ValueError, match="unsupported command 'PING'"):
        server_module.encode_command_result(["PING"], "PONG")



def test_handle_client_sends_bulk_string_for_valid_get(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, "handle_command", lambda command, storage: "10")
    conn = FakeConnection([b"*2\r\n$3\r\nGET\r\n$1\r\na\r\n", b""])

    server_module.handle_client(conn, ("127.0.0.1", 9000), DummyStorage())

    assert conn.sent == [b"$2\r\n10\r\n"]
    assert conn.closed is True



def test_handle_client_converts_command_errors_to_resp_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_error(command: list[str], storage: Any) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(server_module, "handle_command", raise_error)
    conn = FakeConnection([b"*2\r\n$3\r\nGET\r\n$1\r\na\r\n", b""])

    server_module.handle_client(conn, ("127.0.0.1", 9001), DummyStorage())

    assert conn.sent == [b"-ERR boom\r\n"]



def test_handle_client_converts_protocol_errors_to_resp_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_handle(command: list[str], storage: Any) -> str:
        nonlocal called
        called = True
        return "10"

    monkeypatch.setattr(server_module, "handle_command", fake_handle)
    conn = FakeConnection([b"GET a", b""])

    server_module.handle_client(conn, ("127.0.0.1", 9002), DummyStorage())

    assert conn.sent == [b"-ERR expected RESP array\r\n"]
    assert called is False



def test_handle_client_buffers_incomplete_requests_until_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_module, "handle_command", lambda command, storage: "10")
    conn = FakeConnection([b"*2\r\n$3\r\nGET\r\n", b"$1\r\na\r\n", b""])

    server_module.handle_client(conn, ("127.0.0.1", 9003), DummyStorage())

    assert conn.sent == [b"$2\r\n10\r\n"]



def test_handle_client_processes_multiple_commands_from_one_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_handle(command: list[str], storage: Any) -> str | int | None:
        command_name = command[0].upper()
        if command_name == "GET":
            return "10"
        if command_name == "DEL":
            return 1
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(server_module, "handle_command", fake_handle)
    conn = FakeConnection(
        [
            (
                b"*2\r\n$3\r\nGET\r\n$1\r\na\r\n"
                b"*2\r\n$3\r\nDEL\r\n$1\r\na\r\n"
            ),
            b"",
        ]
    )

    server_module.handle_client(conn, ("127.0.0.1", 9004), DummyStorage())

    assert conn.sent == [b"$2\r\n10\r\n", b":1\r\n"]
