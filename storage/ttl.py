"""TTL support helpers for the storage layer."""

from __future__ import annotations

VALID_EXPIRE_OPTIONS = frozenset({"NX", "XX", "GT", "LT"})
PERSISTENT_TTL = float("inf")


def normalize_expire_option(option: str | None) -> str | None:
    """Normalize EXPIRE option tokens to uppercase."""
    if option is None:
        return None

    normalized = option.upper()
    if normalized not in VALID_EXPIRE_OPTIONS:
        raise ValueError(f"unsupported EXPIRE option '{option}'")

    return normalized


def compute_deadline(now: float, seconds: int) -> float:
    """Return the absolute expiry deadline for a relative timeout."""
    return now + float(seconds)


def is_expired(deadline: float, now: float) -> bool:
    """Return whether the deadline has passed."""
    return deadline <= now


def should_apply_expiry(
    option: str | None,
    current_deadline: float | None,
    new_deadline: float,
) -> bool:
    """Apply Redis-style EXPIRE option rules for a new deadline."""
    option = normalize_expire_option(option)
    if option is None:
        return True

    if option == "NX":
        return current_deadline is None

    if option == "XX":
        return current_deadline is not None

    comparable_deadline = (
        current_deadline if current_deadline is not None else PERSISTENT_TTL
    )

    if option == "GT":
        return new_deadline > comparable_deadline

    return new_deadline < comparable_deadline
