"""Instants in the protocol's spelling."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeAlias

Clock: TypeAlias = Callable[[], datetime]


def now() -> datetime:
    """The default clock: the current time in UTC."""
    return datetime.now(UTC)


def instant(at: datetime | str) -> str:
    """``YYYY-MM-DDTHH:MM:SSZ``, with a fraction of 3 or 6 digits when needed.

    A string is passed through untouched: the verifier decides whether it is
    an instant. A ``datetime`` must be timezone-aware, because a naive time
    names no instant.
    """
    if isinstance(at, str):
        return at
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("a time must be timezone-aware; a naive datetime names no instant")
    utc = at.astimezone(UTC)
    base = utc.strftime("%Y-%m-%dT%H:%M:%S")
    if utc.microsecond == 0:
        return f"{base}Z"
    if utc.microsecond % 1000 == 0:
        return f"{base}.{utc.microsecond // 1000:03d}Z"
    return f"{base}.{utc.microsecond:06d}Z"


def epoch_seconds(at: datetime) -> int:
    """Whole seconds since 1970-01-01T00:00:00Z, rounded down."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("a time must be timezone-aware; a naive datetime names no instant")
    return int(at.timestamp() // 1)


def parse_instant(text: str) -> datetime:
    """Reads an instant the verifier has already accepted."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))
