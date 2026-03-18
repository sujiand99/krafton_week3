"""Service layer that orchestrates Redis and the DB API."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from app_server.exceptions import ConflictError, NotFoundError, UpstreamError
from app_server.redis_client import (
    QueueFrontResult,
    QueueJoinResult,
    QueueLeaveResult,
    QueuePositionResult,
    SeatCommandResult,
    SeatStatus,
)

MOCK_PAYMENT_PROVIDER = "mock-pay"
REDIS_CONFIRM_RETRY_ATTEMPTS = 3


class RedisClientProtocol(Protocol):
    def seat_status(self, event_id: str, seat_id: str) -> SeatStatus: ...

    def reserve_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
        hold_seconds: int,
    ) -> SeatCommandResult: ...

    def confirm_seat(
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

    def release_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
    ) -> SeatCommandResult: ...

    def join_queue(self, event_id: str, user_id: str) -> QueueJoinResult: ...

    def queue_position(self, event_id: str, user_id: str) -> QueuePositionResult: ...

    def leave_queue(self, event_id: str, user_id: str) -> QueueLeaveResult: ...

    def peek_queue(self, event_id: str) -> QueueFrontResult: ...


class DBClientProtocol(Protocol):
    def list_events(self) -> list[dict[str, object]]: ...

    def list_event_seats(self, event_id: str) -> list[dict[str, object]]: ...

    def create_held_reservation(
        self,
        payload: dict[str, object],
    ) -> tuple[dict[str, object], bool]: ...

    def confirm_reservation(
        self,
        reservation_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]: ...

    def cancel_reservation(
        self,
        reservation_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]: ...

    def expire_reservation(self, reservation_id: str) -> dict[str, object]: ...

    def list_user_reservations(self, user_id: str) -> list[dict[str, object]]: ...


class TicketingOrchestratorService:
    """App-server orchestration for demo ticketing flows."""

    def __init__(
        self,
        redis_client: RedisClientProtocol,
        db_client: DBClientProtocol,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._redis = redis_client
        self._db = db_client
        self._now_provider = now_provider or (lambda: datetime.now(UTC))

    def list_events(self) -> list[dict[str, object]]:
        return self._db.list_events()

    def list_event_seats(self, event_id: str) -> list[dict[str, object]]:
        seats = self._db.list_event_seats(event_id)
        return [
            self._seat_view(seat, self._redis.seat_status(event_id, seat["seat_id"]))
            for seat in seats
        ]

    def get_event_seat(self, event_id: str, seat_id: str) -> dict[str, object]:
        seat = self._find_event_seat(event_id, seat_id)
        return self._seat_view(seat, self._redis.seat_status(event_id, seat_id))

    def list_user_reservations(self, user_id: str) -> list[dict[str, object]]:
        return self._db.list_user_reservations(user_id)

    def join_queue(self, event_id: str, user_id: str) -> dict[str, object]:
        result = self._redis.join_queue(event_id, user_id)
        return {
            "joined": result.joined,
            "position": result.position,
            "queue_length": result.queue_length,
        }

    def queue_position(self, event_id: str, user_id: str) -> dict[str, object]:
        result = self._redis.queue_position(event_id, user_id)
        return {
            "position": result.position,
            "queue_length": result.queue_length,
        }

    def leave_queue(self, event_id: str, user_id: str) -> dict[str, object]:
        result = self._redis.leave_queue(event_id, user_id)
        return {
            "removed": result.removed,
            "previous_position": result.previous_position,
            "queue_length": result.queue_length,
        }

    def peek_queue(self, event_id: str) -> dict[str, object]:
        result = self._redis.peek_queue(event_id)
        return {
            "user_id": result.user_id,
            "queue_length": result.queue_length,
        }

    def hold_reservation(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
        hold_seconds: int,
    ) -> tuple[dict[str, object], bool]:
        self._find_event_seat(event_id, seat_id)
        reserve_result = self._redis.reserve_seat(event_id, seat_id, user_id, hold_seconds)
        if not reserve_result.success:
            raise ConflictError(self._seat_conflict_message(reserve_result, user_id))

        reservation_id = f"res-{uuid4().hex}"
        hold_token = f"hold-{uuid4().hex}"
        expires_at = self._now_provider() + timedelta(seconds=hold_seconds)
        payload = {
            "reservation_id": reservation_id,
            "event_id": event_id,
            "seat_id": seat_id,
            "user_id": user_id,
            "hold_token": hold_token,
            "expires_at": expires_at.isoformat(),
        }

        try:
            reservation, created = self._db.create_held_reservation(payload)
        except Exception:
            self._safe_release(event_id, seat_id, user_id)
            raise

        return {
            "reservation": reservation,
            "seat": self.get_event_seat(event_id, seat_id),
            "created": created,
        }, created

    def confirm_reservation(
        self,
        reservation_id: str,
        event_id: str,
        seat_id: str,
        user_id: str,
    ) -> dict[str, object]:
        seat = self._find_event_seat(event_id, seat_id)
        status = self._redis.seat_status(event_id, seat_id)
        if status.state == "AVAILABLE":
            self._safe_expire(reservation_id)
            raise ConflictError("seat hold has already expired")
        if status.user_id != user_id:
            raise ConflictError("seat is held by another user")
        if status.state != "HELD":
            raise ConflictError(f"seat cannot be confirmed from state {status.state}")

        payment = self._build_mock_payment(int(seat["price"]))
        reservation = self._db.confirm_reservation(
            reservation_id,
            {
                "payment_id": payment["payment_id"],
                "amount": payment["amount"],
                "provider": payment["provider"],
                "provider_ref": payment["provider_ref"],
            },
        )

        redis_result = self._finalize_confirmed_seat(event_id, seat_id, user_id)
        if redis_result.state != "CONFIRMED" or redis_result.user_id != user_id:
            raise UpstreamError(
                "DB confirmed the reservation but Redis could not finalize the seat"
            )

        return {
            "reservation": reservation,
            "seat": self.get_event_seat(event_id, seat_id),
            "payment": payment,
        }

    def cancel_reservation(
        self,
        reservation_id: str,
        event_id: str,
        seat_id: str,
        user_id: str,
    ) -> dict[str, object]:
        reservation = self._db.cancel_reservation(reservation_id, {})
        self._safe_release(event_id, seat_id, user_id)
        return {
            "reservation": reservation,
            "seat": self.get_event_seat(event_id, seat_id),
        }

    def purchase_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
        hold_seconds: int,
    ) -> dict[str, object]:
        hold_payload, created = self.hold_reservation(event_id, seat_id, user_id, hold_seconds)
        reservation = hold_payload["reservation"]
        try:
            confirmed = self.confirm_reservation(
                reservation["reservation_id"],
                event_id,
                seat_id,
                user_id,
            )
        except Exception:
            self._safe_cancel(reservation["reservation_id"], event_id, seat_id, user_id)
            raise

        confirmed["created"] = created
        return confirmed

    def _find_event_seat(self, event_id: str, seat_id: str) -> dict[str, object]:
        seats = self._db.list_event_seats(event_id)
        for seat in seats:
            if seat["seat_id"] == seat_id:
                return seat
        raise NotFoundError(f"seat '{seat_id}' for event '{event_id}' was not found")

    @staticmethod
    def _seat_view(seat: dict[str, object], status: SeatStatus) -> dict[str, object]:
        merged = dict(seat)
        merged["held_by_user_id"] = None
        merged["hold_ttl"] = None

        if seat["status"] == "CONFIRMED" or status.state == "CONFIRMED":
            merged["status"] = "CONFIRMED"
            return merged

        if status.state == "HELD":
            merged["status"] = "HELD"
            merged["held_by_user_id"] = status.user_id
            merged["hold_ttl"] = status.ttl
            return merged

        merged["status"] = "AVAILABLE"
        return merged

    @staticmethod
    def _seat_conflict_message(result: SeatCommandResult, requested_user_id: str) -> str:
        if result.state == "CONFIRMED":
            return "seat is already confirmed"
        if result.state == "HELD" and result.user_id == requested_user_id:
            return "seat is already held by this user"
        if result.state == "HELD":
            return "seat is already held by another user"
        return "seat is not available"

    @staticmethod
    def _build_mock_payment(amount: int) -> dict[str, object]:
        payment_id = f"pay-{uuid4().hex}"
        return {
            "payment_id": payment_id,
            "status": "SUCCEEDED",
            "amount": amount,
            "provider": MOCK_PAYMENT_PROVIDER,
            "provider_ref": payment_id,
        }

    def _safe_release(self, event_id: str, seat_id: str, user_id: str) -> None:
        try:
            status = self._redis.seat_status(event_id, seat_id)
            if status.state == "HELD" and status.user_id == user_id:
                self._redis.release_seat(event_id, seat_id, user_id)
        except Exception:
            return

    def _safe_expire(self, reservation_id: str) -> None:
        try:
            self._db.expire_reservation(reservation_id)
        except Exception:
            return

    def _safe_cancel(self, reservation_id: str, event_id: str, seat_id: str, user_id: str) -> None:
        try:
            self._db.cancel_reservation(reservation_id, {})
        except Exception:
            pass
        self._safe_release(event_id, seat_id, user_id)

    def _finalize_confirmed_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
    ) -> SeatCommandResult:
        last_error: Exception | None = None

        for _ in range(REDIS_CONFIRM_RETRY_ATTEMPTS):
            try:
                result = self._redis.force_confirm_seat(event_id, seat_id, user_id)
            except UpstreamError as exc:
                last_error = exc
                continue

            if result.state == "CONFIRMED" and result.user_id == user_id:
                return result

            last_error = UpstreamError(
                "Redis returned an unexpected seat state during confirmation finalization"
            )

        if last_error is None:
            last_error = UpstreamError(
                "Redis did not finalize the confirmed seat"
            )
        raise last_error
