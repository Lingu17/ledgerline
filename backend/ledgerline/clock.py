"""Demo clock. Scenario dates are offsets from the moment the demo was seeded."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


class Clock:
    def __init__(self) -> None:
        self._offset = timedelta(0)

    def now(self) -> datetime:
        return datetime.now(timezone.utc) + self._offset

    def advance(self, delta: timedelta) -> None:
        """Tests only: move time forward to exercise expiry."""
        self._offset += delta

    def reset(self) -> None:
        self._offset = timedelta(0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return dt.astimezone(timezone.utc)
