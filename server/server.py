"""TCP server entrypoint for the Mini Redis project."""

from __future__ import annotations

import socket

HOST = "127.0.0.1"
PORT = 6379
BACKLOG = 5
BUFFER_SIZE = 4096


def handle_client(conn: socket.socket, addr: tuple[str, int]) -> None:
    """Receive raw bytes from a connected client until it disconnects."""
    print(f"[connected] {addr[0]}:{addr[1]}")

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
            # TODO: parse RESP, call the command handler, encode the response.


def serve_forever(host: str = HOST, port: int = PORT) -> None:
    """Start the TCP server and accept client connections forever."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((host, port))
        server_socket.listen(BACKLOG)

        print(f"Mini Redis TCP server listening on {host}:{port}")

        while True:
            conn, addr = server_socket.accept()
            handle_client(conn, addr)


def main() -> None:
    """Start the Mini Redis server."""
    try:
        serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
