"""Background worker that reconciles Redis seat state against DB truth."""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime
from pathlib import Path

from app_server.reconciler import TicketingReconciler
from app_server.redis_client import RedisRESPClient
from ticketing_api.database import DEFAULT_DB_PATH, SQLiteDatabase
from ticketing_api.repository import TicketingRepository
from ticketing_api.service import TicketingService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconcile stale holds and confirmed seats between DB and Redis.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="SQLite database path for the ticketing DB service.",
    )
    parser.add_argument(
        "--redis-host",
        default="127.0.0.1",
        help="Redis host.",
    )
    parser.add_argument(
        "--redis-port",
        type=int,
        default=6379,
        help="Redis port.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=2.0,
        help="Polling interval when running continuously.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum stale or confirmed reservations to scan per pass.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single reconciliation pass and exit.",
    )
    return parser


def log_line(message: str) -> None:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp} UTC] {message}", flush=True)


def main() -> int:
    args = build_parser().parse_args()

    db_service = TicketingService(TicketingRepository(SQLiteDatabase(args.db_path)))
    db_service.initialize()

    reconciler = TicketingReconciler(
        redis_client=RedisRESPClient(host=args.redis_host, port=args.redis_port),
        db_service=db_service,
    )

    while True:
        report = reconciler.run_once(limit=args.limit)
        if (
            report.expired_reservation_ids
            or report.repaired_reservation_ids
            or report.errors
        ):
            log_line(
                "reconcile "
                f"expired={len(report.expired_reservation_ids)} "
                f"repaired={len(report.repaired_reservation_ids)} "
                f"errors={len(report.errors)}"
            )
            for error in report.errors:
                log_line(f"error: {error}")

        if args.once:
            return 0

        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
