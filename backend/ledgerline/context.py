"""Application context: settings, clock, provider, DB connections, policy."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from . import db
from .clock import Clock
from .config import Settings
from .money import CURRENCY_EXPONENT, MoneyError, validate_minor

DEFAULT_POLICY: dict[str, Any] = {
    # Short payments up to this gap are treated as bank fees and written off.
    "fee_tolerance_minor": {"USD": 5_000, "EUR": 2_500, "GBP": 2_500},
    # ...and never more than this share of the amount billed (basis points).
    "fee_tolerance_bps": 100,
    # Refunds above this need a human approval bound to the exact scope.
    "refund_auto_limit_minor": {"USD": 100_000, "EUR": 100_000, "GBP": 100_000},
    # Treasury never draws a wallet below its reserve.
    "reserve_minor": {"USD": 500_000, "EUR": 200_000, "GBP": 150_000},
    # Cash set aside from planning, e.g. a pre-funded sandbox wallet where only a budget is the operating book.
    "ring_fenced_minor": {"USD": 0, "EUR": 0, "GBP": 0},
    "obligation_lookahead_days": 14,
    "evidence_max_ttl_seconds": 900,
    "evidence_clock_skew_seconds": 60,
    "webhook_tolerance_seconds": 300,
}


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULT_POLICY)
    for key in ("fee_tolerance_minor", "refund_auto_limit_minor", "reserve_minor", "ring_fenced_minor"):
        if key in policy:
            value = policy[key]
            if not isinstance(value, dict) or set(value) != set(CURRENCY_EXPONENT):
                raise MoneyError(f"{key} must set every currency: {sorted(CURRENCY_EXPONENT)}")
            out[key] = {ccy: validate_minor(v, allow_zero=True) for ccy, v in value.items()}
    for key, lo, hi in (
        ("fee_tolerance_bps", 0, 500),
        ("obligation_lookahead_days", 1, 90),
        ("evidence_max_ttl_seconds", 60, 3600),
        ("evidence_clock_skew_seconds", 0, 300),
        ("webhook_tolerance_seconds", 30, 900),
    ):
        if key in policy:
            v = policy[key]
            if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
                raise MoneyError(f"{key} must be an integer in [{lo}, {hi}]")
            out[key] = v
    return out


@dataclass
class AppContext:
    settings: Settings
    clock: Clock
    provider: Any
    local_bank: Any | None = None
    sandbox: Any | None = None
    claude: Any | None = None
    org: dict[str, Any] | None = None
    _initialised: bool = field(default=False, repr=False)
    _init_lock: Any = field(default_factory=threading.Lock, repr=False)

    def connect(self) -> sqlite3.Connection:
        if not self._initialised:
            with self._init_lock:
                if not self._initialised:
                    from .migrations import TENANT, migrate
                    conn = db.connect(self.settings.db_path)
                    try:
                        migrate(conn, TENANT)
                    except BaseException:
                        conn.close()
                        raise
                    self._initialised = True
                    return conn
        return db.connect(self.settings.db_path)

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = self.connect()
        try:
            yield c
        finally:
            c.close()

    def policy(self, conn: sqlite3.Connection) -> dict[str, Any]:
        stored = db.get_setting(conn, "policy")
        return validate_policy(stored) if stored else dict(DEFAULT_POLICY)

    def paused(self, conn: sqlite3.Connection) -> bool:
        return bool(db.get_setting(conn, "money_out_paused", False))
