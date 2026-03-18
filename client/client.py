"""HTTP demo dashboard for the Mini Redis ticketing presentation."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from client.demo_service import MiniRedisTcpClient, TicketingDemoService
from server.server import MiniRedisServer
from storage.engine import StorageEngine


STATIC_DIR = Path(__file__).resolve().parent / "static"


class DemoRequestHandler(BaseHTTPRequestHandler):
    """Serve the demo dashboard and bridge UI actions to the service layer."""

    server: "TicketingDemoHTTPServer"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self._send_json(HTTPStatus.OK, self.server.demo_service.dashboard_state())
            return

        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/reset":
            self.server.demo_service.bootstrap()
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "message": "데모 상태를 초기화했습니다.",
                },
            )
            return

        payload = self._read_json_body()

        if parsed.path == "/api/actions/reserve":
            result = self.server.demo_service.reserve_seat(
                seat_id=payload.get("seat_id", "S0001"),
                user_id=payload.get("user_id", "user0001"),
                ttl_seconds=int(payload.get("ttl_seconds") or 10),
            )
            self._send_json(HTTPStatus.OK, result)
            return

        if parsed.path == "/api/actions/confirm":
            result = self.server.demo_service.confirm_seat(
                seat_id=payload.get("seat_id", "S0001"),
                user_id=payload.get("user_id", "user0001"),
            )
            self._send_json(HTTPStatus.OK, result)
            return

        if parsed.path == "/api/actions/release":
            result = self.server.demo_service.release_seat(
                seat_id=payload.get("seat_id", "S0001"),
                user_id=payload.get("user_id", "user0001"),
            )
            self._send_json(HTTPStatus.OK, result)
            return

        if parsed.path == "/api/actions/simulate":
            result = self.server.demo_service.simulate_surge(
                contenders=int(payload.get("contenders") or 120),
                focus_seats=int(payload.get("focus_seats") or 12),
                ttl_seconds=int(payload.get("ttl_seconds") or 10),
            )
            self._send_json(HTTPStatus.OK, result)
            return

        self._send_json(
            HTTPStatus.NOT_FOUND,
            {"ok": False, "message": f"Unknown route: {parsed.path}"},
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}

        body = self.rfile.read(content_length)
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _serve_static(self, path: str) -> None:
        route = path if path not in {"", "/"} else "/index.html"
        file_path = STATIC_DIR / route.lstrip("/")

        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        media_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
        }.get(file_path.suffix, "application/octet-stream")

        payload = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class TicketingDemoHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server with a shared demo service instance."""

    def __init__(
        self,
        server_address: tuple[str, int],
        demo_service: TicketingDemoService,
    ) -> None:
        super().__init__(server_address, DemoRequestHandler)
        self.demo_service = demo_service


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mini Redis ticketing demo dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--redis-host", default="127.0.0.1")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument(
        "--embed-redis",
        action="store_true",
        help="Start an in-process Mini Redis server for the demo dashboard.",
    )
    parser.add_argument(
        "--db-path",
        default=str(PROJECT_ROOT / "client" / "data" / "ticketing_demo.sqlite3"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    embedded_redis: MiniRedisServer | None = None
    redis_thread: threading.Thread | None = None

    if args.embed_redis:
        embedded_redis = MiniRedisServer(
            host=args.redis_host,
            port=args.redis_port,
            storage=StorageEngine(),
        )
        redis_thread = threading.Thread(
            target=embedded_redis.serve_forever,
            daemon=True,
        )
        redis_thread.start()
        embedded_redis.wait_until_started()

    redis_client = MiniRedisTcpClient(args.redis_host, args.redis_port)
    demo_service = TicketingDemoService(
        redis_client=redis_client,
        db_path=Path(args.db_path),
    )
    demo_service.bootstrap()

    server = TicketingDemoHTTPServer((args.host, args.port), demo_service)
    address = server.server_address
    print(
        "Ticketing demo dashboard listening on "
        f"http://{address[0]}:{address[1]}"
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        demo_service.close()
        if embedded_redis is not None:
            embedded_redis.shutdown()
        if redis_thread is not None:
            redis_thread.join(timeout=1.0)


if __name__ == "__main__":
    main()
