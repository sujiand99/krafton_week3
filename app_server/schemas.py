"""Pydantic schemas for the orchestration app."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ticketing_api.schemas import EventResponse, ReservationResponse

TicketingSeatStatus = Literal["AVAILABLE", "HELD", "CONFIRMED"]
QueueUser = str | None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeatViewResponse(StrictModel):
    event_id: str
    seat_id: str
    seat_label: str
    section: str
    row_label: str
    seat_number: int
    price: int
    status: TicketingSeatStatus
    held_by_user_id: str | None = None
    hold_ttl: int | None = None
    created_at: datetime


class QueueJoinRequest(StrictModel):
    event_id: str
    user_id: str


class QueueLeaveRequest(StrictModel):
    event_id: str
    user_id: str


class QueueJoinResponse(StrictModel):
    joined: bool
    position: int
    queue_length: int


class QueuePositionResponse(StrictModel):
    position: int
    queue_length: int


class QueueFrontResponse(StrictModel):
    user_id: QueueUser
    queue_length: int


class QueueLeaveResponse(StrictModel):
    removed: bool
    previous_position: int
    queue_length: int


class HoldReservationRequest(StrictModel):
    event_id: str
    seat_id: str
    user_id: str
    hold_seconds: int = Field(default=30, gt=0)


class ConfirmReservationRequest(StrictModel):
    event_id: str
    seat_id: str
    user_id: str


class CancelReservationRequest(StrictModel):
    event_id: str
    seat_id: str
    user_id: str


class MockPaymentResponse(StrictModel):
    payment_id: str
    status: Literal["SUCCEEDED"]
    amount: int
    provider: str
    provider_ref: str


class HoldReservationResponse(StrictModel):
    reservation: ReservationResponse
    seat: SeatViewResponse
    created: bool


class ConfirmReservationResponse(StrictModel):
    reservation: ReservationResponse
    seat: SeatViewResponse
    payment: MockPaymentResponse


class CancelReservationResponse(StrictModel):
    reservation: ReservationResponse
    seat: SeatViewResponse


class PurchaseReservationRequest(StrictModel):
    event_id: str
    seat_id: str
    user_id: str
    hold_seconds: int = Field(default=30, gt=0)


class PurchaseReservationResponse(StrictModel):
    reservation: ReservationResponse
    seat: SeatViewResponse
    payment: MockPaymentResponse
    created: bool
