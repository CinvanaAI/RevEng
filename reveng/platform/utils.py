"""Shared utilities for the platform layer."""
from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> str:
    """Return the current UTC time as an ISO-8601 string with millisecond precision."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
