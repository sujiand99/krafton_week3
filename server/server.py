"""TCP server entrypoint for the Mini Redis project."""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from commands.handler import handle_command
from protocol.resp_encoder import (
    encode_array,
    encode_bulk_string,
    encode_error,
    encode_integer,
    encode_simple_string,
)
from protocol.resp_parser import IncompleteRESPError, ProtocolError, parse_resp_frame
from storage.engine import StorageEngine
from storage.sqlite_store import SQLiteSnapshotStore

HOST = "127.0.0.1"
PORT = 6379
BACKLOG = 5
BUFFER_SIZE = 4096
SIMPLE_STRING_COMMANDS = {"SET"}
DEFAULT_DB_PATH: Path | None = None
DEFAULT_SNAPSHOT_INTERVAL = 5.0


def _format_error_message(error: Exception) -> str:
    """Convert exceptions into a safe one-line RESP error message."""
    message = str(error).strip() or error.__class__.__name__
    return message.replace("\r", " ").replace("\n", " ")


def encode_result_value(result: Any) -> str:
    """Map a pure command result onto the matching RESP type."""
    if isinstance(result, tuple):
        result = list(result)

    if isinstance(result, list):
        return encode_array(result)

    if isinstance(result, bool):
        result = int(result)

    if isinstance(result, int):
        return encode_integer(result)

    if result is None or isinstance(result, str):
        return encode_bulk_string(result)

    raise TypeError(
        "Command results must be str, int, None, or a list/tuple of scalar values"
    )


def encode_command_result(command: list[str], result: Any) -> str:
    """Map a command result onto the RESP type agreed for that command."""
    if not command or not command[0]:
        raise ValueError("empty command")

    command_name = command[0].upper()
    if command_name in SIMPLE_STRING_COMMANDS:
        if not isinstance(result, str):
            raise TypeError(f"{command_name} must return a string result")
        return encode_simple_string(result)

    return encode_result_value(result)


def send_response(conn: socket.socket, addr: tuple[str, int], response: str) -> None:
    """Send a RESP response to the connected client and log it."""
    try:
        conn.sendall(response.encode("utf-8"))
    except OSError:
        return

    print(f"[sent] {addr[0]}:{addr[1]} <- {response!r}")


def handle_client(
    conn: socket.socket,
    addr: tuple[str, int],
    storage: StorageEngine,
    stop_event: threading.Event | None = None,
) -> None:
    """Receive raw bytes, parse RESP commands, and send RESP responses."""
    print(f"[connected] {addr[0]}:{addr[1]}")
    buffer = b""

    with conn:
        while True:
            if stop_event is not None and stop_event.is_set():
                print(f"[stopped] {addr[0]}:{addr[1]}")
                return

            try:
                data = conn.recv(BUFFER_SIZE)
            except ConnectionResetError:
                print(f"[reset] {addr[0]}:{addr[1]}")
                return
            except OSError:
                print(f"[socket-error] {addr[0]}:{addr[1]}")
                return

            if not data:
                print(f"[disconnected] {addr[0]}:{addr[1]}")
                return

            print(f"[received] {addr[0]}:{addr[1]} -> {data!r}")
            buffer += data

            while buffer:
                try:
                    command, consumed = parse_resp_frame(buffer)
                except IncompleteRESPError:
                    break
                except ProtocolError as exc:
                    response = encode_error(_format_error_message(exc))
                    send_response(conn, addr, response)
                    buffer = b""
                    break

                try:
                    result = handle_command(command, storage)
                    response = encode_command_result(command, result)
                except Exception as exc:
                    response = encode_error(_format_error_message(exc))

                send_response(conn, addr, response)
                buffer = buffer[consumed:]


class MiniRedisServer:
    def __init__(
        self,
        host: str = HOST,
        port: int = PORT,
        storage: StorageEngine | None = None,
        db_path: str | Path | None = DEFAULT_DB_PATH,
        snapshot_interval: float = DEFAULT_SNAPSHOT_INTERVAL,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if snapshot_interval <= 0:
            raise ValueError("snapshot interval must be greater than zero")

        self._host = host
        self._port = port
        self._clock = clock or getattr(storage, "_clock", time.time)
        self._storage = storage or StorageEngine(clock=self._clock)
        self._snapshot_store = (
            SQLiteSnapshotStore(db_path) if db_path is not None else None
        )
        self._snapshot_interval = snapshot_interval
        self._shutdown_event = threading.Event()
        self._started_event = threading.Event()
        self._server_socket: socket.socket | None = None
        self._client_threads: set[threading.Thread] = set()
        self._client_threads_lock = threading.Lock()
        self._snapshot_thread: threading.Thread | None = None
        self._bound_address = (host, port)

    @property
    def address(self) -> tuple[str, int]:
        return self._bound_address

    def serve_forever(self) -> None:
        if self._snapshot_store is not None:
            self._snapshot_store.initialize()
            self._storage.load_snapshot(
                self._snapshot_store.load_entries(),
                now=self._clock(),
            )
            self._snapshot_thread = threading.Thread(
                target=self._run_snapshot_loop,
                daemon=True,
            )
            self._snapshot_thread.start()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind((self._host, self._port))
            server_socket.listen(BACKLOG)
            server_socket.settimeout(0.2)
            self._server_socket = server_socket
            self._bound_address = server_socket.getsockname()
            self._started_event.set()
            print(
                "Mini Redis TCP server listening on "
                f"{self._bound_address[0]}:{self._bound_address[1]}"
            )

            try:
                while not self._shutdown_event.is_set():
                    try:
                        client_socket, client_address = server_socket.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        break

                    client_thread = threading.Thread(
                        target=self._run_client,
                        args=(client_socket, client_address),
                        daemon=True,
                    )
                    with self._client_threads_lock:
                        self._client_threads.add(client_thread)
                    client_thread.start()
            finally:
                self._shutdown_event.set()
                self._server_socket = None
                self._started_event.set()
                self._flush_snapshot()
                self._join_snapshot_thread()
                self._join_client_threads()

    def wait_until_started(self, timeout: float = 2.0) -> tuple[str, int]:
        if not self._started_event.wait(timeout):
            raise TimeoutError("server did not start in time")
        return self._bound_address

    def shutdown(self) -> None:
        self._shutdown_event.set()
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass

    def _run_client(self, client_socket: socket.socket, client_address: tuple[str, int]) -> None:
        try:
            handle_client(
                client_socket,
                client_address,
                self._storage,
                stop_event=self._shutdown_event,
            )
        finally:
            current_thread = threading.current_thread()
            with self._client_threads_lock:
                self._client_threads.discard(current_thread)

    def _join_client_threads(self) -> None:
        with self._client_threads_lock:
            client_threads = list(self._client_threads)

        for client_thread in client_threads:
            client_thread.join(timeout=0.5)

    def _run_snapshot_loop(self) -> None:
        while not self._shutdown_event.wait(self._snapshot_interval):
            self._flush_snapshot()

    def _flush_snapshot(self) -> None:
        if self._snapshot_store is None:
            return

        try:
            entries = self._storage.snapshot(now=self._clock())
            self._snapshot_store.save_entries(entries)
        except Exception as exc:
            print(f"[snapshot-error] {exc}")

    def _join_snapshot_thread(self) -> None:
        if self._snapshot_thread is not None:
            self._snapshot_thread.join(timeout=0.5)


def serve(host: str = HOST, port: int = PORT) -> None:
    MiniRedisServer(host=host, port=port).serve_forever()


def main() -> None:
    """Start the Mini Redis server."""
    parser = argparse.ArgumentParser(description="Mini Redis MVP server")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--snapshot-interval", type=float, default=DEFAULT_SNAPSHOT_INTERVAL)
    args = parser.parse_args()

    try:
        MiniRedisServer(
            host=args.host,
            port=args.port,
            db_path=args.db_path,
            snapshot_interval=args.snapshot_interval,
        ).serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
