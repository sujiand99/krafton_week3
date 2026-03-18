"""Shared demo layout constants for the ticketing stack."""

from __future__ import annotations

from string import ascii_uppercase

DEMO_EVENT_ID = "concert-seoul-2026"
DEMO_ROW_LABELS = tuple(ascii_uppercase[:20])
DEMO_SEATS_PER_ROW = 20
DEMO_SEAT_COUNT = len(DEMO_ROW_LABELS) * DEMO_SEATS_PER_ROW
DEMO_DEFAULT_PRICE = 120_000


def iter_demo_seat_ids() -> list[str]:
    return [
        f"{row_label}{seat_number}"
        for row_label in DEMO_ROW_LABELS
        for seat_number in range(1, DEMO_SEATS_PER_ROW + 1)
    ]


def build_demo_seat_rows(created_at: str) -> list[tuple[object, ...]]:
    seat_rows: list[tuple[object, ...]] = []
    for row_label in DEMO_ROW_LABELS:
        for seat_number in range(1, DEMO_SEATS_PER_ROW + 1):
            seat_id = f"{row_label}{seat_number}"
            seat_rows.append(
                (
                    DEMO_EVENT_ID,
                    seat_id,
                    seat_id,
                    "FLOOR",
                    row_label,
                    seat_number,
                    DEMO_DEFAULT_PRICE,
                    created_at,
                )
            )
    return seat_rows
