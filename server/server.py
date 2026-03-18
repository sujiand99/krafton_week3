"""TCP server entrypoint for the Mini Redis project."""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from commands.handler import handle_command
from protocol.resp_encoder import (
    encode_bulk_string,
    encode_error,
    encode_integer,
    encode_simple_string,
)
from protocol.resp_parser import IncompleteRESPError, ProtocolError, parse_resp_frame
from storage.engine import StorageEngine

HOST = "127.0.0.1"
PORT = 6379
BACKLOG = 5
BUFFER_SIZE = 4096


def _format_error_message(error: Exception) -> str:
    """Convert exceptions into a safe one-line RESP error message."""
    message = str(error).strip() or error.__class__.__name__
    return message.replace("\r", " ").replace("\n", " ")


def encode_command_result(command: list[str], result: Any) -> str:
    """Map a command result onto the RESP type agreed for that command."""
    if not command or not command[0]:
        raise ValueError("empty command")

    command_name = command[0].upper()
    if command_name == "SET":
        if not isinstance(result, str):
            raise TypeError("SET must return a string result")
        return encode_simple_string(result)

    if command_name == "GET":
        if result is not None and not isinstance(result, str):
            raise TypeError("GET must return a string or None")
        return encode_bulk_string(result)

    if command_name == "DEL":
        if isinstance(result, bool):
            result = int(result)
        if not isinstance(result, int):
            raise TypeError("DEL must return an integer result")
        return encode_integer(result)

    raise ValueError(f"unsupported command '{command_name}'")


def send_response(conn: socket.socket, addr: tuple[str, int], response: str) -> None:
    """Send a RESP response to the connected client and log it."""
    conn.sendall(response.encode("utf-8"))
    print(f"[sent] {addr[0]}:{addr[1]} <- {response!r}")


def handle_client(
    conn: socket.socket,
    addr: tuple[str, int],
    storage: StorageEngine,
) -> None:
    """Receive raw bytes, parse RESP commands, and send RESP responses."""
    print(f"[connected] {addr[0]}:{addr[1]}")
    buffer = b""

    with conn:
        while True:
            try:
                data = conn.recv(BUFFER_SIZE)
            except ConnectionResetError:
                print(f"[reset] {addr[0]}:{addr[1]}")
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


def serve_forever(host: str = HOST, port: int = PORT) -> None:
    """Start the TCP server and accept client connections forever."""
    storage = StorageEngine()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((host, port))
        server_socket.listen(BACKLOG)

        print(f"Mini Redis TCP server listening on {host}:{port}")

        while True:
            conn, addr = server_socket.accept()
            handle_client(conn, addr, storage)


def main() -> None:
    """Start the Mini Redis server."""
    try:
        serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
