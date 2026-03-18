"""Pydantic schemas for the ticketing DB service."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ReservationStatus = Literal["HELD", "CONFIRMED", "CANCELLED", "EXPIRED"]
SeatStatus = Literal["AVAILABLE", "CONFIRMED"]
PaymentStatus = Literal["SUCCEEDED", "FAILED", "CANCELLED"]
CancelablePaymentStatus = Literal["FAILED", "CANCELLED"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventResponse(StrictModel):
    event_id: str
    title: str
    venue: str
    starts_at: datetime
    booking_opens_at: datetime
    created_at: datetime


class SeatResponse(StrictModel):
    event_id: str
    seat_id: str
    seat_label: str
    section: str
    row_label: str
    seat_number: int
    price: int
    status: SeatStatus
    created_at: datetime


class ReservationResponse(StrictModel):
    reservation_id: str
    event_id: str
    seat_id: str
    user_id: str
    status: ReservationStatus
    hold_token: str | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    payment_id: str | None = None
    payment_status: PaymentStatus | None = None
    payment_amount: int | None = None
    payment_provider: str | None = None
    payment_provider_ref: str | None = None


class ConfirmedSeatResponse(StrictModel):
    event_id: str
    seat_id: str
    reservation_id: str
    user_id: str
    confirmed_at: datetime


class HeldReservationCreate(StrictModel):
    reservation_id: str
    event_id: str
    seat_id: str
    user_id: str
    hold_token: str
    expires_at: datetime


class ConfirmReservationRequest(StrictModel):
    payment_id: str
    amount: int
    provider: str
    provider_ref: str


class CancelReservationRequest(StrictModel):
    payment_id: str | None = None
    payment_status: CancelablePaymentStatus | None = None
    amount: int | None = None
    provider: str | None = None
    provider_ref: str | None = None
