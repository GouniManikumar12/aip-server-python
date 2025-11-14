"""Timestamp helpers enforcing canonical ISO-8601 formatting and skew checks."""

from __future__ import annotations

from datetime import datetime, timezone


class TimestampError(ValueError):
    """Raised when timestamps are malformed or outside the permitted skew."""


def parse_timestamp(value: str) -> datetime:
    if not value:
        raise TimestampError("timestamp missing")
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover - delegated to datetime
        raise TimestampError("timestamp is not ISO-8601 compatible") from exc
    if dt.tzinfo is None:
        raise TimestampError("timestamp must include timezone information")
    return dt.astimezone(timezone.utc)


def assert_within_skew(timestamp: str, *, max_skew_ms: int, now: datetime | None = None) -> datetime:
    """Validate timestamp string and ensure it is within the configured skew."""
    dt = parse_timestamp(timestamp)
    ref = now or datetime.now(timezone.utc)
    delta_ms = abs((ref - dt).total_seconds() * 1000)
    if delta_ms > max_skew_ms:
        raise TimestampError(
            f"timestamp skew {delta_ms:.1f}ms exceeds max {max_skew_ms}ms"
        )
    return dt
