"""Background reconciliation that keeps Redis seat state aligned with DB truth."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app_server.redis_client import SeatCommandResult, SeatStatus


@dataclass(slots=True)
class ReconciliationReport:
    expired_reservation_ids: list[str] = field(default_factory=list)
    repaired_reservation_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class RedisReconcilerProtocol(Protocol):
    def seat_status(self, event_id: str, seat_id: str) -> SeatStatus: ...

    def release_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
    ) -> SeatCommandResult: ...

    def force_confirm_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
    ) -> SeatCommandResult: ...


class DBReconcilerProtocol(Protocol):
    def expire_stale_reservations(self, limit: int = 100) -> list[dict[str, object]]: ...

    def list_confirmed_reservations(
        self,
        limit: int | None = None,
    ) -> list[dict[str, object]]: ...


class TicketingReconciler:
    """Periodic repair worker for TTL expiry and Redis seat finalization."""

    def __init__(
        self,
        redis_client: RedisReconcilerProtocol,
        db_service: DBReconcilerProtocol,
    ) -> None:
        self._redis = redis_client
        self._db = db_service

    def run_once(self, limit: int = 100) -> ReconciliationReport:
        report = ReconciliationReport()
        self._expire_stale_holds(limit, report)
        self._repair_confirmed_seats(limit, report)
        return report

    def _expire_stale_holds(self, limit: int, report: ReconciliationReport) -> None:
        expired = self._db.expire_stale_reservations(limit=limit)

        for reservation in expired:
            reservation_id = self._require_str(reservation, "reservation_id")
            event_id = self._require_str(reservation, "event_id")
            seat_id = self._require_str(reservation, "seat_id")
            user_id = self._require_str(reservation, "user_id")
            report.expired_reservation_ids.append(reservation_id)

            try:
                status = self._redis.seat_status(event_id, seat_id)
                if status.state == "HELD" and status.user_id == user_id:
                    self._redis.release_seat(event_id, seat_id, user_id)
            except Exception as exc:
                report.errors.append(
                    f"expire release failed for {reservation_id}: {exc}"
                )

    def _repair_confirmed_seats(self, limit: int, report: ReconciliationReport) -> None:
        confirmed = self._db.list_confirmed_reservations(limit=limit)

        for reservation in confirmed:
            reservation_id = self._require_str(reservation, "reservation_id")
            event_id = self._require_str(reservation, "event_id")
            seat_id = self._require_str(reservation, "seat_id")
            user_id = self._require_str(reservation, "user_id")

            try:
                status = self._redis.seat_status(event_id, seat_id)
                if status.state == "CONFIRMED" and status.user_id == user_id:
                    continue

                result = self._redis.force_confirm_seat(event_id, seat_id, user_id)
                if result.state == "CONFIRMED" and result.user_id == user_id:
                    report.repaired_reservation_ids.append(reservation_id)
                    continue

                report.errors.append(
                    f"confirm repair returned unexpected state for {reservation_id}"
                )
            except Exception as exc:
                report.errors.append(f"confirm repair failed for {reservation_id}: {exc}")

    @staticmethod
    def _require_str(reservation: dict[str, object], field_name: str) -> str:
        value = reservation.get(field_name)
        if not isinstance(value, str):
            raise TypeError(f"reservation field '{field_name}' must be a string")
        return value
