"""Auto ticketing stress demo for the Mini Redis TCP server.

This script uses only Python's standard library. It talks to the Mini Redis
server over raw TCP sockets and manually encodes every command in RESP.

Demo flow
---------
- Reset 100 seat keys: seat:1 ~ seat:100
- Spawn 1,000 user threads
- Each user picks one random seat and races to reserve it
- Reservation protocol per user:
  1. GET seat:{n}
  2. If empty, SET seat:{n} User_x
  3. Read back once more to verify the winner before printing success

Notes
-----
Because the current Mini Redis only exposes GET/SET/DEL, there is no atomic
compare-and-set command yet. To keep the presentation deterministic and avoid
false double-success messages, the demo serializes each individual seat race
with a client-side seat mutex while still running 1,000 user threads overall.
This preserves loud multi-threaded contention across the full 100-seat map
without lying about the final seat count on screen.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import random
import socket
import threading
import time
from typing import Any, BinaryIO

HOST = "127.0.0.1"
PORT = 6379
TOTAL_SEATS = 100
TOTAL_USERS = 1000
SOCKET_TIMEOUT = 3.0

RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
DIM = "\033[2m"

print_lock = threading.Lock()
seat_locks = [threading.Lock() for _ in range(TOTAL_SEATS + 1)]


class RespError(RuntimeError):
    """Raised when the Mini Redis server returns a RESP error."""


class RespSocketClient:
    """Tiny RESP-over-TCP client implemented with socket only."""

    def __init__(self, host: str, port: int, timeout: float = SOCKET_TIMEOUT) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._reader: BinaryIO | None = None

    def __enter__(self) -> "RespSocketClient":
        self._sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._reader = self._sock.makefile("rb")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._reader is not None:
            self._reader.close()
        if self._sock is not None:
            self._sock.close()

    def execute(self, *tokens: str) -> Any:
        if self._sock is None or self._reader is None:
            raise RuntimeError("RESP client is not connected")

        self._sock.sendall(encode_resp_command(list(tokens)))
        return read_resp_value(self._reader)


def encode_resp_command(tokens: list[str]) -> bytes:
    chunks: list[bytes] = [f"*{len(tokens)}\r\n".encode("utf-8")]
    for token in tokens:
        encoded = token.encode("utf-8")
        chunks.append(f"${len(encoded)}\r\n".encode("utf-8"))
        chunks.append(encoded + b"\r\n")
    return b"".join(chunks)


def read_resp_value(reader: BinaryIO) -> Any:
    prefix = reader.read(1)
    if not prefix:
        raise ConnectionError("Server closed the connection unexpectedly")

    if prefix == b"+":
        return _readline(reader).decode("utf-8")
    if prefix == b"-":
        raise RespError(_readline(reader).decode("utf-8"))
    if prefix == b":":
        return int(_readline(reader))
    if prefix == b"$":
        length = int(_readline(reader))
        if length == -1:
            return None
        payload = reader.read(length)
        line_end = reader.read(2)
        if line_end != b"\r\n":
            raise RespError("Malformed RESP bulk string from server")
        return payload.decode("utf-8")
    if prefix == b"*":
        item_count = int(_readline(reader))
        if item_count == -1:
            return None
        return [read_resp_value(reader) for _ in range(item_count)]

    raise RespError(f"Unsupported RESP prefix: {prefix!r}")


def _readline(reader: BinaryIO) -> bytes:
    line = reader.readline()
    if not line.endswith(b"\r\n"):
        raise RespError("Malformed RESP line from server")
    return line[:-2]


@dataclass
class DemoStats:
    total_seats: int
    sold_seats: set[int] = field(default_factory=set)
    success_count: int = 0
    fail_count: int = 0
    connection_failures: int = 0
    started_at: float = field(default_factory=time.perf_counter)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_success(self, seat_no: int) -> int:
        with self.lock:
            self.sold_seats.add(seat_no)
            self.success_count += 1
            return self.remaining_seats

    def record_failure(self) -> None:
        with self.lock:
            self.fail_count += 1

    def record_connection_failure(self) -> None:
        with self.lock:
            self.connection_failures += 1
            self.fail_count += 1

    @property
    def remaining_seats(self) -> int:
        return self.total_seats - len(self.sold_seats)

    def snapshot(self) -> tuple[int, int, int, float]:
        with self.lock:
            elapsed = time.perf_counter() - self.started_at
            return (
                self.success_count,
                self.fail_count,
                self.remaining_seats,
                elapsed,
            )


def log_line(message: str) -> None:
    with print_lock:
        print(message, flush=True)


def reset_seats(host: str, port: int, total_seats: int) -> None:
    log_line(f"{DIM}[*] Resetting {total_seats} seats before the demo...{RESET}")
    with RespSocketClient(host, port) as client:
        for seat_no in range(1, total_seats + 1):
            client.execute("DEL", f"seat:{seat_no}")
    log_line(f"{DIM}[*] Seat reset completed.{RESET}")


def attempt_ticketing(
    *,
    host: str,
    port: int,
    user_index: int,
    seat_no: int,
    start_barrier: threading.Barrier,
    stats: DemoStats,
) -> None:
    user_id = f"User_{user_index}"
    seat_key = f"seat:{seat_no}"

    try:
        start_barrier.wait()
    except threading.BrokenBarrierError:
        return

    seat_lock = seat_locks[seat_no]
    with seat_lock:
        try:
            with RespSocketClient(host, port) as client:
                current_owner = client.execute("GET", seat_key)
                if current_owner is None:
                    client.execute("SET", seat_key, user_id)
                    verified_owner = client.execute("GET", seat_key)
                    if verified_owner == user_id:
                        remaining = stats.record_success(seat_no)
                        log_line(
                            f"{GREEN}✅ [{user_id}] {YELLOW}{seat_no}번 좌석{GREEN} 예매 성공! "
                            f"{MAGENTA}(현재 남은 좌석: {remaining}/{stats.total_seats}){RESET}"
                        )
                        return

                    stats.record_failure()
                    log_line(
                        f"{RED}❌ [{user_id}] {YELLOW}{seat_no}번 좌석{RED}은 이미 선택된 좌석입니다! "
                        f"{DIM}(경합 중 소유권 변경 감지){RESET}"
                    )
                    return

                stats.record_failure()
                log_line(
                    f"{RED}❌ [{user_id}] {YELLOW}{seat_no}번 좌석{RED}은 이미 선택된 좌석입니다! "
                    f"{DIM}(현재 소유자: {current_owner}){RESET}"
                )
        except (OSError, ConnectionError, RespError) as exc:
            stats.record_connection_failure()
            log_line(
                f"{RED}❌ [{user_id}] 서버 통신 실패: {exc}{RESET}"
            )


def build_threads(
    *,
    host: str,
    port: int,
    total_users: int,
    total_seats: int,
    stats: DemoStats,
    seed: int,
) -> tuple[list[threading.Thread], threading.Barrier]:
    rng = random.Random(seed)
    start_barrier = threading.Barrier(total_users + 1)
    threads: list[threading.Thread] = []

    for user_index in range(1, total_users + 1):
        seat_no = rng.randint(1, total_seats)
        thread = threading.Thread(
            target=attempt_ticketing,
            kwargs={
                "host": host,
                "port": port,
                "user_index": user_index,
                "seat_no": seat_no,
                "start_barrier": start_barrier,
                "stats": stats,
            },
            name=f"ticket-user-{user_index}",
            daemon=True,
        )
        threads.append(thread)

    return threads, start_barrier


def print_banner(host: str, port: int, total_users: int, total_seats: int) -> None:
    lines = [
        f"{BOLD}{CYAN}=== Mini Redis Auto Ticketing Demo ==={RESET}",
        f"{DIM}Server: {host}:{port}{RESET}",
        f"{DIM}Seats : {total_seats} (seat:1 ~ seat:{total_seats}){RESET}",
        f"{DIM}Users : {total_users} virtual users / threads{RESET}",
        f"{BOLD}{MAGENTA}1,000개의 스레드가 동시에 랜덤 좌석을 향해 돌진합니다...{RESET}",
    ]
    for line in lines:
        log_line(line)


def print_summary(stats: DemoStats, total_seats: int) -> None:
    success_count, fail_count, remaining, elapsed = stats.snapshot()
    sold_count = total_seats - remaining
    log_line("")
    log_line(f"{BOLD}{CYAN}=== Ticketing Summary ==={RESET}")
    log_line(f"{GREEN}성공: {success_count}{RESET}")
    log_line(f"{RED}실패: {fail_count}{RESET}")
    log_line(f"{YELLOW}판매된 좌석 수: {sold_count}/{total_seats}{RESET}")
    log_line(f"{MAGENTA}남은 좌석 수: {remaining}/{total_seats}{RESET}")
    log_line(f"{CYAN}총 소요 시간: {elapsed:.3f}초{RESET}")
    if stats.connection_failures:
        log_line(f"{RED}통신 실패: {stats.connection_failures}{RESET}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mini Redis auto ticketing demo")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--users", type=int, default=TOTAL_USERS)
    parser.add_argument("--seats", type=int, default=TOTAL_SEATS)
    parser.add_argument("--seed", type=int, default=20260318)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    global seat_locks
    seat_locks = [threading.Lock() for _ in range(args.seats + 1)]

    print_banner(args.host, args.port, args.users, args.seats)
    reset_seats(args.host, args.port, args.seats)

    stats = DemoStats(total_seats=args.seats)
    threads, start_barrier = build_threads(
        host=args.host,
        port=args.port,
        total_users=args.users,
        total_seats=args.seats,
        stats=stats,
        seed=args.seed,
    )

    for thread in threads:
        thread.start()

    log_line(f"{BOLD}{YELLOW}[*] All users ready. Releasing the barrier now!{RESET}")
    release_started = time.perf_counter()
    start_barrier.wait()

    for thread in threads:
        thread.join()

    release_elapsed = time.perf_counter() - release_started
    log_line(f"{DIM}[*] All ticketing threads finished in {release_elapsed:.3f}s after release.{RESET}")
    print_summary(stats, args.seats)


if __name__ == "__main__":
    main()
