"""Integration-style tests for the server/protocol flow."""

from __future__ import annotations

import socket
import threading
from typing import Any

import pytest

from server import server as server_module
from server.server import MiniRedisServer
from storage.engine import StorageEngine


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


class FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class TrackingStorage(StorageEngine):
    def __init__(self) -> None:
        super().__init__()
        self._tracking_lock = threading.Lock()
        self.active_calls = 0
        self.max_active_calls = 0

    def set(self, key: str, value: str) -> None:
        self._enter_operation()
        try:
            super().set(key, value)
        finally:
            self._exit_operation()

    def get(self, key: str) -> str | None:
        self._enter_operation()
        try:
            return super().get(key)
        finally:
            self._exit_operation()

    def delete(self, key: str) -> bool:
        self._enter_operation()
        try:
            return super().delete(key)
        finally:
            self._exit_operation()

    def expire(self, key: str, seconds: int, option: str | None = None) -> bool:
        self._enter_operation()
        try:
            return super().expire(key, seconds, option)
        finally:
            self._exit_operation()

    def ttl(self, key: str) -> int:
        self._enter_operation()
        try:
            return super().ttl(key)
        finally:
            self._exit_operation()

    def _enter_operation(self) -> None:
        with self._tracking_lock:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)

    def _exit_operation(self) -> None:
        with self._tracking_lock:
            self.active_calls -= 1


def encode_command(*tokens: str) -> bytes:
    parts = [f"*{len(tokens)}\r\n".encode("utf-8")]
    for token in tokens:
        encoded = token.encode("utf-8")
        parts.append(f"${len(encoded)}\r\n".encode("utf-8"))
        parts.append(encoded + b"\r\n")
    return b"".join(parts)


def send_command(client: socket.socket, *tokens: str) -> str:
    client.sendall(encode_command(*tokens))
    return client.recv(1024).decode("utf-8")


def test_encode_command_result_maps_command_types_to_resp() -> None:
    assert server_module.encode_command_result(["SET", "a", "1"], "OK") == "+OK\r\n"
    assert server_module.encode_command_result(["GET", "a"], "10") == "$2\r\n10\r\n"
    assert server_module.encode_command_result(["GET", "missing"], None) == "$-1\r\n"
    assert server_module.encode_command_result(["DEL", "a"], 1) == ":1\r\n"
    assert server_module.encode_command_result(["EXPIRE", "a", "10"], 1) == ":1\r\n"
    assert server_module.encode_command_result(["TTL", "a"], -1) == ":-1\r\n"


def test_encode_command_result_supports_array_results_for_collection_reads() -> None:
    assert (
        server_module.encode_command_result(["LRANGE", "items", "0", "-1"], ["a", "b"])
        == "*2\r\n$1\r\na\r\n$1\r\nb\r\n"
    )
    assert (
        server_module.encode_command_result(["SMEMBERS", "myset"], ["x", "y"])
        == "*2\r\n$1\r\nx\r\n$1\r\ny\r\n"
    )


def test_encode_command_result_supports_tuple_collection_results() -> None:
    assert (
        server_module.encode_command_result(["LRANGE", "items", "0", "-1"], ("a", "b"))
        == "*2\r\n$1\r\na\r\n$1\r\nb\r\n"
    )


def test_encode_command_result_supports_empty_collection_results() -> None:
    assert server_module.encode_command_result(["SMEMBERS", "myset"], []) == "*0\r\n"


def test_encode_command_result_requires_string_for_simple_string_commands() -> None:
    with pytest.raises(TypeError, match="SET must return a string result"):
        server_module.encode_command_result(["SET", "a", "1"], 1)


def test_encode_command_result_rejects_unsupported_result_type() -> None:
    with pytest.raises(TypeError, match="Command results must be"):
        server_module.encode_command_result(["HGETALL", "myhash"], {"field": "value"})


def test_encode_result_value_rejects_unsupported_collection_items() -> None:
    with pytest.raises(TypeError, match="RESP array items must be"):
        server_module.encode_result_value(["ok", {"bad": "item"}])


def test_handle_client_sends_bulk_string_for_valid_get(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, "handle_command", lambda command, storage: "10")
    conn = FakeConnection([b"*2\r\n$3\r\nGET\r\n$1\r\na\r\n", b""])

    server_module.handle_client(conn, ("127.0.0.1", 9000), DummyStorage())

    assert conn.sent == [b"$2\r\n10\r\n"]
    assert conn.closed is True


def test_handle_client_sends_resp_array_for_collection_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_module, "handle_command", lambda command, storage: ["a", "b"])
    conn = FakeConnection([b"*4\r\n$6\r\nLRANGE\r\n$5\r\nitems\r\n$1\r\n0\r\n$2\r\n-1\r\n", b""])

    server_module.handle_client(conn, ("127.0.0.1", 9005), DummyStorage())

    assert conn.sent == [b"*2\r\n$1\r\na\r\n$1\r\nb\r\n"]


def test_handle_client_sends_mixed_scalar_resp_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_module, "handle_command", lambda command, storage: ["a", None, 2])
    conn = FakeConnection([b"*2\r\n$8\r\nSMEMBERS\r\n$5\r\nmyset\r\n", b""])

    server_module.handle_client(conn, ("127.0.0.1", 9006), DummyStorage())

    assert conn.sent == [b"*3\r\n$1\r\na\r\n$-1\r\n:2\r\n"]


def test_handle_client_converts_result_mapping_failures_to_resp_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_module, "handle_command", lambda command, storage: ["ok", {"bad": "item"}])
    conn = FakeConnection([b"*2\r\n$8\r\nSMEMBERS\r\n$5\r\nmyset\r\n", b""])

    server_module.handle_client(conn, ("127.0.0.1", 9007), DummyStorage())

    assert conn.sent == [b"-ERR RESP array items must be str, int, or None\r\n"]


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


def test_server_processes_multiple_requests_on_one_connection() -> None:
    server = MiniRedisServer(port=0)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    host, port = server.wait_until_started()

    try:
        with socket.create_connection((host, port), timeout=2) as client:
            client.sendall(b"*3\r\n$3\r\nSET\r\n$1\r\na\r\n$1\r\n1\r\n")
            assert client.recv(1024).decode("utf-8") == "+OK\r\n"

            client.sendall(b"*2\r\n$3\r\nGET\r\n$1\r\na\r\n")
            assert client.recv(1024).decode("utf-8") == "$1\r\n1\r\n"

            client.sendall(b"*2\r\n$3\r\nDEL\r\n$1\r\na\r\n")
            assert client.recv(1024).decode("utf-8") == ":1\r\n"

            client.sendall(b"*2\r\n$3\r\nGET\r\n$1\r\na\r\n")
            assert client.recv(1024).decode("utf-8") == "$-1\r\n"
    finally:
        server.shutdown()
        server_thread.join(timeout=2)


def test_server_expires_keys_after_deadline_using_injected_clock() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)
    server = MiniRedisServer(port=0, storage=storage)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    host, port = server.wait_until_started()

    try:
        with socket.create_connection((host, port), timeout=2) as client:
            assert send_command(client, "SET", "a", "1") == "+OK\r\n"
            assert send_command(client, "EXPIRE", "a", "10") == ":1\r\n"
            assert send_command(client, "GET", "a") == "$1\r\n1\r\n"

            clock.advance(10)

            assert send_command(client, "GET", "a") == "$-1\r\n"
    finally:
        server.shutdown()
        server_thread.join(timeout=2)


def test_server_applies_expire_options_over_resp() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)
    server = MiniRedisServer(port=0, storage=storage)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    host, port = server.wait_until_started()

    try:
        with socket.create_connection((host, port), timeout=2) as client:
            assert send_command(client, "SET", "a", "1") == "+OK\r\n"
            assert send_command(client, "EXPIRE", "a", "10", "NX") == ":1\r\n"
            assert send_command(client, "EXPIRE", "a", "20", "NX") == ":0\r\n"
            assert send_command(client, "EXPIRE", "a", "20", "XX") == ":1\r\n"
            assert send_command(client, "EXPIRE", "a", "15", "GT") == ":0\r\n"
            assert send_command(client, "EXPIRE", "a", "25", "GT") == ":1\r\n"
            assert send_command(client, "EXPIRE", "a", "30", "LT") == ":0\r\n"
            assert send_command(client, "EXPIRE", "a", "5", "LT") == ":1\r\n"
            assert send_command(client, "SET", "b", "1") == "+OK\r\n"
            assert send_command(client, "EXPIRE", "b", "5", "GT") == ":0\r\n"
            assert send_command(client, "EXPIRE", "b", "5", "LT") == ":1\r\n"
    finally:
        server.shutdown()
        server_thread.join(timeout=2)


def test_server_deletes_key_immediately_for_non_positive_expire() -> None:
    storage = StorageEngine(clock=FakeClock())
    server = MiniRedisServer(port=0, storage=storage)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    host, port = server.wait_until_started()

    try:
        with socket.create_connection((host, port), timeout=2) as client:
            assert send_command(client, "SET", "a", "1") == "+OK\r\n"
            assert send_command(client, "EXPIRE", "a", "0") == ":1\r\n"
            assert send_command(client, "GET", "a") == "$-1\r\n"
    finally:
        server.shutdown()
        server_thread.join(timeout=2)


def test_server_returns_ttl_over_resp() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)
    server = MiniRedisServer(port=0, storage=storage)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    host, port = server.wait_until_started()

    try:
        with socket.create_connection((host, port), timeout=2) as client:
            assert send_command(client, "TTL", "missing") == ":-2\r\n"
            assert send_command(client, "SET", "a", "1") == "+OK\r\n"
            assert send_command(client, "TTL", "a") == ":-1\r\n"
            assert send_command(client, "EXPIRE", "a", "10") == ":1\r\n"
            assert send_command(client, "TTL", "a") == ":10\r\n"

            clock.advance(4)

            assert send_command(client, "TTL", "a") == ":6\r\n"

            clock.advance(6)

            assert send_command(client, "TTL", "a") == ":-2\r\n"
    finally:
        server.shutdown()
        server_thread.join(timeout=2)
def test_server_returns_errors_without_dropping_valid_connection_flow() -> None:
    server = MiniRedisServer(port=0)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    host, port = server.wait_until_started()

    try:
        with socket.create_connection((host, port), timeout=2) as client:
            client.sendall(b"*1\r\n$5\r\nHELLO\r\n")
            assert (
                client.recv(1024).decode("utf-8")
                == "-ERR unknown command 'HELLO'\r\n"
            )

            client.sendall(b"*2\r\n$3\r\nSET\r\n$1\r\na\r\n")
            assert (
                client.recv(1024).decode("utf-8")
                == "-ERR wrong number of arguments for 'SET' command\r\n"
            )

            client.sendall(b"*3\r\n$3\r\nSET\r\n$1\r\na\r\n$1\r\n2\r\n")
            assert client.recv(1024).decode("utf-8") == "+OK\r\n"
    finally:
        server.shutdown()
        server_thread.join(timeout=2)


def test_server_serializes_commands_from_multiple_clients() -> None:
    storage = TrackingStorage()
    server = MiniRedisServer(port=0, storage=storage)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    host, port = server.wait_until_started()
    barrier = threading.Barrier(4)
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def client_session(client_id: int) -> None:
        key = f"client-{client_id}"
        value = f"value-{client_id}"

        try:
            barrier.wait(timeout=1)
            with socket.create_connection((host, port), timeout=2) as client:
                assert send_command(client, "SET", key, value) == "+OK\r\n"
                assert send_command(client, "GET", key) == f"${len(value)}\r\n{value}\r\n"
                assert send_command(client, "DEL", key) == ":1\r\n"
        except BaseException as exc:
            with errors_lock:
                errors.append(exc)

    clients = [threading.Thread(target=client_session, args=(index,)) for index in range(4)]

    try:
        for client in clients:
            client.start()

        for client in clients:
            client.join(timeout=3)
            assert not client.is_alive()

        assert not errors
        assert storage.max_active_calls == 1
    finally:
        server.shutdown()
        server_thread.join(timeout=2)


def test_server_supports_ticketing_seat_flow() -> None:
    server = MiniRedisServer(port=0)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    host, port = server.wait_until_started()

    try:
        with socket.create_connection((host, port), timeout=2) as client:
            assert (
                send_command(client, "SEAT_STATUS", "concert", "A-1")
                == "*3\r\n$9\r\nAVAILABLE\r\n$-1\r\n:-1\r\n"
            )
            assert (
                send_command(client, "RESERVE_SEAT", "concert", "A-1", "user-1", "30")
                == "*4\r\n:1\r\n$4\r\nHELD\r\n$6\r\nuser-1\r\n:30\r\n"
            )
            assert (
                send_command(client, "RESERVE_SEAT", "concert", "A-1", "user-2", "30")
                == "*4\r\n:0\r\n$4\r\nHELD\r\n$6\r\nuser-1\r\n:30\r\n"
            )
            assert (
                send_command(client, "CONFIRM_SEAT", "concert", "A-1", "user-1")
                == "*4\r\n:1\r\n$9\r\nCONFIRMED\r\n$6\r\nuser-1\r\n:-1\r\n"
            )
            assert (
                send_command(client, "SEAT_STATUS", "concert", "A-1")
                == "*3\r\n$9\r\nCONFIRMED\r\n$6\r\nuser-1\r\n:-1\r\n"
            )
    finally:
        server.shutdown()
        server_thread.join(timeout=2)


def test_server_releases_hold_after_ticketing_seat_ttl_expires() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)
    server = MiniRedisServer(port=0, storage=storage)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    host, port = server.wait_until_started()

    try:
        with socket.create_connection((host, port), timeout=2) as client:
            assert (
                send_command(client, "RESERVE_SEAT", "concert", "A-1", "user-1", "5")
                == "*4\r\n:1\r\n$4\r\nHELD\r\n$6\r\nuser-1\r\n:5\r\n"
            )

            clock.advance(5)

            assert (
                send_command(client, "SEAT_STATUS", "concert", "A-1")
                == "*3\r\n$9\r\nAVAILABLE\r\n$-1\r\n:-1\r\n"
            )
    finally:
        server.shutdown()
        server_thread.join(timeout=2)


def test_server_supports_ticketing_queue_flow() -> None:
    server = MiniRedisServer(port=0)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    host, port = server.wait_until_started()

    try:
        with socket.create_connection((host, port), timeout=2) as client:
            assert send_command(client, "JOIN_QUEUE", "concert", "user-1") == "*3\r\n:1\r\n:1\r\n:1\r\n"
            assert send_command(client, "JOIN_QUEUE", "concert", "user-2") == "*3\r\n:1\r\n:2\r\n:2\r\n"
            assert send_command(client, "JOIN_QUEUE", "concert", "user-1") == "*3\r\n:0\r\n:1\r\n:2\r\n"
            assert send_command(client, "QUEUE_POSITION", "concert", "user-2") == "*2\r\n:2\r\n:2\r\n"
            assert send_command(client, "POP_QUEUE", "concert") == "*2\r\n$6\r\nuser-1\r\n:1\r\n"
            assert send_command(client, "QUEUE_POSITION", "concert", "user-1") == "*2\r\n:-1\r\n:1\r\n"
            assert send_command(client, "POP_QUEUE", "concert") == "*2\r\n$6\r\nuser-2\r\n:0\r\n"
            assert send_command(client, "POP_QUEUE", "concert") == "*2\r\n$-1\r\n:0\r\n"
    finally:
        server.shutdown()
        server_thread.join(timeout=2)


def test_server_supports_queue_leave_and_peek_flow() -> None:
    server = MiniRedisServer(port=0)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    host, port = server.wait_until_started()

    try:
        with socket.create_connection((host, port), timeout=2) as client:
            assert send_command(client, "JOIN_QUEUE", "concert", "user-1") == "*3\r\n:1\r\n:1\r\n:1\r\n"
            assert send_command(client, "JOIN_QUEUE", "concert", "user-2") == "*3\r\n:1\r\n:2\r\n:2\r\n"
            assert send_command(client, "JOIN_QUEUE", "concert", "user-3") == "*3\r\n:1\r\n:3\r\n:3\r\n"
            assert send_command(client, "PEEK_QUEUE", "concert") == "*2\r\n$6\r\nuser-1\r\n:3\r\n"
            assert send_command(client, "LEAVE_QUEUE", "concert", "user-2") == "*3\r\n:1\r\n:2\r\n:2\r\n"
            assert send_command(client, "LEAVE_QUEUE", "concert", "missing") == "*3\r\n:0\r\n:-1\r\n:2\r\n"
            assert send_command(client, "QUEUE_POSITION", "concert", "user-3") == "*2\r\n:2\r\n:2\r\n"
            assert send_command(client, "PEEK_QUEUE", "concert") == "*2\r\n$6\r\nuser-1\r\n:2\r\n"
    finally:
        server.shutdown()
        server_thread.join(timeout=2)
