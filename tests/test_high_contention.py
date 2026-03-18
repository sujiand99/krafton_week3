from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from random import Random
import socket
from threading import Lock, Thread, local
from time import perf_counter, sleep

from app_server.exceptions import ConflictError, UpstreamError
from app_server.redis_client import (
    IncompleteRESPReplyError,
    RESPReplyError,
    RedisRESPClient,
    parse_resp_reply,
)
from server.server import MiniRedisServer
from ticketing_api.demo_layout import DEMO_EVENT_ID, DEMO_SEAT_COUNT, iter_demo_seat_ids

REQUESTS_PER_SEAT = 30
TOTAL_REQUESTS = DEMO_SEAT_COUNT * REQUESTS_PER_SEAT
HOLD_SECONDS = 300
MAX_WORKERS = 32
CONNECT_RETRIES = 5


class PersistentRedisRESPClient(RedisRESPClient):
    def __init__(self, host: str, port: int, timeout: float = 10.0) -> None:
        super().__init__(host=host, port=port, timeout=timeout)
        self._connection = socket.create_connection((host, port), timeout=timeout)
        self._connection.settimeout(timeout)
        self._buffer = bytearray()

    def close(self) -> None:
        self._connection.close()

    def execute(self, *tokens: str):
        request = self._encode_command(tokens)

        try:
            self._connection.sendall(request)
            return self._read_reply_from_connection()
        except ConflictError:
            raise
        except OSError as exc:
            raise UpstreamError(f"Redis connection failed: {exc}") from exc
        except UnicodeDecodeError as exc:
            raise UpstreamError("Redis returned non-UTF8 data") from exc
        except RESPReplyError as exc:
            raise UpstreamError(f"Invalid Redis reply: {exc}") from exc

    def _read_reply_from_connection(self):
        while True:
            try:
                value, consumed = parse_resp_reply(self._buffer)
            except IncompleteRESPReplyError:
                chunk = self._connection.recv(4096)
                if not chunk:
                    raise UpstreamError("Redis closed the connection before replying")
                self._buffer.extend(chunk)
                continue

            del self._buffer[:consumed]
            return value


def build_reservation_attempts() -> list[tuple[str, str]]:
    attempts = [
        (seat_id, f"load-user-{seat_id}-{user_index:02d}")
        for seat_id in iter_demo_seat_ids()
        for user_index in range(1, REQUESTS_PER_SEAT + 1)
    ]
    Random(20260318).shuffle(attempts)
    return attempts


def test_high_contention_reserve_seat_allows_only_one_holder_per_seat() -> None:
    thread_local = local()
    client_lock = Lock()
    persistent_clients: list[PersistentRedisRESPClient] = []
    log_sink = StringIO()

    with redirect_stdout(log_sink):
        redis_server = MiniRedisServer(port=0, db_path=None)
        redis_thread = Thread(target=redis_server.serve_forever, daemon=True)
        redis_thread.start()
        host, port = redis_server.wait_until_started()

        def reserve_attempt(payload: tuple[str, str]) -> tuple[str, str, bool]:
            seat_id, user_id = payload
            client = getattr(thread_local, "client", None)
            if client is None:
                client = PersistentRedisRESPClient(host=host, port=port, timeout=10.0)
                thread_local.client = client
                with client_lock:
                    persistent_clients.append(client)

            for attempt in range(CONNECT_RETRIES):
                try:
                    result = client.reserve_seat(DEMO_EVENT_ID, seat_id, user_id, HOLD_SECONDS)
                    return seat_id, user_id, result.success
                except UpstreamError:
                    if attempt == CONNECT_RETRIES - 1:
                        raise

                    sleep(0.01 * (attempt + 1))

            raise AssertionError("unreachable")

        attempts = build_reservation_attempts()
        started_at = perf_counter()

        try:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                results = list(executor.map(reserve_attempt, attempts))

            elapsed = perf_counter() - started_at
            successes = [(seat_id, user_id) for seat_id, user_id, success in results if success]
            failures = [seat_id for seat_id, _, success in results if not success]

            assert len(results) == TOTAL_REQUESTS
            assert len(successes) == DEMO_SEAT_COUNT
            assert len(failures) == TOTAL_REQUESTS - DEMO_SEAT_COUNT

            winners_by_seat: dict[str, list[str]] = {}
            for seat_id, user_id in successes:
                winners_by_seat.setdefault(seat_id, []).append(user_id)

            assert len(winners_by_seat) == DEMO_SEAT_COUNT
            assert all(len(user_ids) == 1 for user_ids in winners_by_seat.values())

            verifier = PersistentRedisRESPClient(host=host, port=port, timeout=10.0)
            try:
                for seat_id, user_ids in winners_by_seat.items():
                    status = verifier.seat_status(DEMO_EVENT_ID, seat_id)
                    assert status.state == "HELD"
                    assert status.user_id == user_ids[0]
                    assert status.ttl > 0
            finally:
                verifier.close()

            print(
                f"high-contention reserve test: {TOTAL_REQUESTS} requests "
                f"across {DEMO_SEAT_COUNT} seats completed in {elapsed:.2f}s",
            )
        finally:
            for client in persistent_clients:
                client.close()
            redis_server.shutdown()
            redis_thread.join(timeout=5)
