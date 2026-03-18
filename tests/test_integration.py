import socket
import threading

from server.server import MiniRedisServer


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


def test_server_returns_errors_without_dropping_valid_connection_flow() -> None:
    server = MiniRedisServer(port=0)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    host, port = server.wait_until_started()

    try:
        with socket.create_connection((host, port), timeout=2) as client:
            client.sendall(b"*1\r\n$5\r\nHELLO\r\n")
            assert client.recv(1024).decode("utf-8") == "-ERR unknown command\r\n"

            client.sendall(b"*2\r\n$3\r\nSET\r\n$1\r\na\r\n")
            assert client.recv(1024).decode("utf-8") == "-ERR wrong number of arguments\r\n"

            client.sendall(b"*3\r\n$3\r\nSET\r\n$1\r\na\r\n$1\r\n2\r\n")
            assert client.recv(1024).decode("utf-8") == "+OK\r\n"
    finally:
        server.shutdown()
        server_thread.join(timeout=2)
