"""TCP server entrypoint for the Mini Redis project."""

from __future__ import annotations

import argparse
import socket
import threading

from commands.handler import handle_command
from protocol.resp_encoder import encode_error
from protocol.resp_parser import RespError, RespStreamParser
from storage.engine import StorageEngine

HOST = "127.0.0.1"
PORT = 6379


class MiniRedisServer:
    def __init__(self, host: str = HOST, port: int = PORT) -> None:
        self._host = host
        self._port = port
        self._storage = StorageEngine()
        self._shutdown_event = threading.Event()
        self._started_event = threading.Event()
        self._server_socket: socket.socket | None = None
        self._client_threads: set[threading.Thread] = set()
        self._client_threads_lock = threading.Lock()
        self._bound_address = (host, port)

    @property
    def address(self) -> tuple[str, int]:
        return self._bound_address

    def serve_forever(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind((self._host, self._port))
            server_socket.listen()
            server_socket.settimeout(0.2)
            self._server_socket = server_socket
            self._bound_address = server_socket.getsockname()
            self._started_event.set()

            try:
                while not self._shutdown_event.is_set():
                    try:
                        client_socket, _ = server_socket.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        break

                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_socket,),
                        daemon=True,
                    )
                    with self._client_threads_lock:
                        self._client_threads.add(client_thread)
                    client_thread.start()
            finally:
                self._shutdown_event.set()
                self._server_socket = None
                self._started_event.set()
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

    def _handle_client(self, client_socket: socket.socket) -> None:
        parser = RespStreamParser()

        try:
            with client_socket:
                while not self._shutdown_event.is_set():
                    try:
                        chunk = client_socket.recv(4096)
                    except OSError:
                        break

                    if not chunk:
                        break

                    try:
                        commands = parser.feed_data(chunk)
                    except RespError:
                        self._send_response(client_socket, encode_error("protocol error"))
                        parser.reset()
                        break

                    for command in commands:
                        response = handle_command(command, self._storage)
                        self._send_response(client_socket, response)
        finally:
            current_thread = threading.current_thread()
            with self._client_threads_lock:
                self._client_threads.discard(current_thread)

    def _join_client_threads(self) -> None:
        with self._client_threads_lock:
            client_threads = list(self._client_threads)

        for client_thread in client_threads:
            client_thread.join(timeout=0.5)

    @staticmethod
    def _send_response(client_socket: socket.socket, response: str) -> None:
        try:
            client_socket.sendall(response.encode("utf-8"))
        except OSError:
            pass


def serve(host: str = HOST, port: int = PORT) -> None:
    MiniRedisServer(host=host, port=port).serve_forever()


def main() -> None:
    """Start the Mini Redis server."""
    parser = argparse.ArgumentParser(description="Mini Redis MVP server")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
