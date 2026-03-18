from __future__ import annotations

from pathlib import Path
import threading
from uuid import uuid4

from app_server.reconciler import TicketingReconciler
from app_server.redis_client import RedisRESPClient
from server.server import MiniRedisServer
from ticketing_api.database import SQLiteDatabase
from ticketing_api.repository import TicketingRepository
from ticketing_api.schemas import ConfirmReservationRequest, HeldReservationCreate
from ticketing_api.seed_demo import seed_demo_data
from ticketing_api.service import TicketingService


def make_db_path() -> Path:
    return Path(".test_tmp") / f"{uuid4().hex}.db"


def test_reconciler_expires_stale_holds_and_releases_matching_redis_hold() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)
    db_service = TicketingService(TicketingRepository(SQLiteDatabase(db_path)))
    db_service.initialize()

    redis_server = MiniRedisServer(port=0, db_path=None)
    redis_thread = threading.Thread(target=redis_server.serve_forever, daemon=True)
    redis_thread.start()
    host, port = redis_server.wait_until_started()
    redis_client = RedisRESPClient(host=host, port=port)

    try:
        db_service.create_held_reservation(
            HeldReservationCreate(
                reservation_id="res-stale-worker",
                event_id="concert-seoul-2026",
                seat_id="B4",
                user_id="user-1",
                hold_token="hold-stale-worker",
                expires_at="2020-01-01T00:00:00+00:00",
            )
        )
        redis_client.reserve_seat("concert-seoul-2026", "B4", "user-1", 30)

        report = TicketingReconciler(redis_client, db_service).run_once(limit=10)

        reservation = db_service.list_user_reservations("user-1")[0]
        seat_status = redis_client.seat_status("concert-seoul-2026", "B4")

        assert report.expired_reservation_ids == ["res-stale-worker"]
        assert report.repaired_reservation_ids == []
        assert reservation["status"] == "EXPIRED"
        assert seat_status.state == "AVAILABLE"
        assert seat_status.user_id is None
    finally:
        redis_server.shutdown()
        redis_thread.join(timeout=2)
        db_path.unlink(missing_ok=True)


def test_reconciler_repairs_confirmed_seats_from_db_truth() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)
    db_service = TicketingService(TicketingRepository(SQLiteDatabase(db_path)))
    db_service.initialize()

    redis_server = MiniRedisServer(port=0, db_path=None)
    redis_thread = threading.Thread(target=redis_server.serve_forever, daemon=True)
    redis_thread.start()
    host, port = redis_server.wait_until_started()
    redis_client = RedisRESPClient(host=host, port=port)

    try:
        db_service.create_held_reservation(
            HeldReservationCreate(
                reservation_id="res-confirm-worker",
                event_id="concert-seoul-2026",
                seat_id="B5",
                user_id="user-2",
                hold_token="hold-confirm-worker",
                expires_at="2026-03-19T12:00:00+00:00",
            )
        )
        db_service.confirm_reservation(
            "res-confirm-worker",
            ConfirmReservationRequest(
                payment_id="pay-confirm-worker",
                amount=120000,
                provider="demo-pay",
                provider_ref="demo-pay-confirm-worker",
            ),
        )

        report = TicketingReconciler(redis_client, db_service).run_once(limit=10)
        seat_status = redis_client.seat_status("concert-seoul-2026", "B5")

        assert report.expired_reservation_ids == []
        assert report.repaired_reservation_ids == ["res-confirm-worker"]
        assert seat_status.state == "CONFIRMED"
        assert seat_status.user_id == "user-2"
    finally:
        redis_server.shutdown()
        redis_thread.join(timeout=2)
        db_path.unlink(missing_ok=True)
