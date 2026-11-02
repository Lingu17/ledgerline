"""LOCAL DEMO bank simulator. No network, no real money.

State lives in its own SQLite file so it behaves like an external system: it
survives Ledgerline restarts and is not rolled back by Ledgerline transactions.
Fault injection lets tests and the demo exercise timeouts honestly.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterator

from ..clock import Clock, iso, parse_iso
from ..money import convert_ceil
from .base import (
    ConversionResult,
    PaymentLinkResult,
    ProviderAmbiguous,
    ProviderError,
    Quote,
    TransferResult,
    normalise_conversion_status,
)

# Synthetic demo rates, displayed in the UI. Key: (sell, buy) -> buy units per sell unit.
DEMO_RATES: dict[tuple[str, str], Decimal] = {
    ("USD", "EUR"): Decimal("0.9200"),
    ("GBP", "EUR"): Decimal("1.1600"),
    ("GBP", "USD"): Decimal("1.2600"),
    ("EUR", "USD"): Decimal("1.0850"),
    ("EUR", "GBP"): Decimal("0.8600"),
    ("USD", "GBP"): Decimal("0.7900"),
}
QUOTE_VALIDITY = timedelta(minutes=1)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transfers (
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL, destination TEXT NOT NULL, reference TEXT NOT NULL,
  status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversions (
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, quote_id TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quotes (
  id TEXT PRIMARY KEY, valid_to TEXT NOT NULL);
"""


class LocalBank:
    name = "local"
    label = "No bank connected (simulated records, no real money)"

    def __init__(self, path: Path, clock: Clock) -> None:
        self.path = path
        self.clock = clock
        self._lock = threading.Lock()
        # Fault injection: callables consumed by the next create_transfer call.
        self.next_transfer_fault: str | None = None  # 'timeout_after_accept' | 'timeout_before_accept' | 'reject'
        self.on_create: Callable[[], None] | None = None
        # Next conversion outcome: None (SETTLED) | 'SCHEDULED' | 'CANCELLED' | 'timeout_after_accept' | 'timeout_before_accept'
        self.next_conversion_fault: str | None = None
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)
            from ..pg import harden

            harden(c)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Autocommit connection that is always closed (Windows keeps files locked otherwise)."""
        from .. import db

        c = db.connect(self.path)  # SQLite file locally; a PostgreSQL schema when LEDGERLINE_DATABASE_URL is set
        try:
            yield c
        finally:
            c.close()

    def reset(self) -> None:
        with self._lock, self._conn() as c:
            for table in ("transfers", "conversions", "quotes"):
                c.execute(f"DELETE FROM {table}")

    def _result(self, r: sqlite3.Row) -> TransferResult:
        return TransferResult(r["id"], r["request_id"], r["status"].lower(), r["status"])

    # Transfers -----------------------------------------------------------
    def create_transfer(self, *, request_id, amount_minor, currency, destination, reference) -> TransferResult:
        fault, self.next_transfer_fault = self.next_transfer_fault, None
        if self.on_create:
            self.on_create()
        if fault == "timeout_before_accept":
            raise ProviderAmbiguous("simulated timeout before the bank recorded the request")
        if fault == "reject":
            raise ProviderError("simulated rejection: beneficiary account closed")
        with self._lock, self._conn() as c:
            existing = c.execute("SELECT * FROM transfers WHERE request_id = ?", (request_id,)).fetchone()
            if existing:
                # Real providers reject reused request_ids; the caller must look up instead.
                raise ProviderError(f"duplicate request_id {request_id}")
            tid = "tr_" + uuid.uuid4().hex[:12]
            c.execute(
                "INSERT INTO transfers VALUES (?,?,?,?,?,?,?,?)",
                (tid, request_id, amount_minor, currency, destination, reference, "PROCESSING", iso(self.clock.now())),
            )
            row = c.execute("SELECT * FROM transfers WHERE id = ?", (tid,)).fetchone()
        if fault == "timeout_after_accept":
            raise ProviderAmbiguous("simulated timeout after the bank accepted the request")
        return self._result(row)

    def find_transfer(self, request_id: str) -> TransferResult | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM transfers WHERE request_id = ?", (request_id,)).fetchone()
        return self._result(r) if r else None

    def get_transfer(self, provider_id: str) -> TransferResult:
        with self._conn() as c:
            r = c.execute("SELECT * FROM transfers WHERE id = ?", (provider_id,)).fetchone()
        if not r:
            raise ProviderError(f"unknown transfer {provider_id}")
        return self._result(r)

    _ALLOWED = {
        "PROCESSING": {"SENT", "FAILED", "CANCELLED"},
        "SENT": {"PAID", "FAILED"},
    }

    def simulate_transfer_status(self, provider_id: str, next_status: str) -> TransferResult:
        nxt = next_status.upper()
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM transfers WHERE id = ?", (provider_id,)).fetchone()
            if not r:
                raise ProviderError(f"unknown transfer {provider_id}")
            if nxt not in self._ALLOWED.get(r["status"], set()):
                raise ProviderError(f"cannot move transfer from {r['status']} to {nxt}")
            c.execute("UPDATE transfers SET status = ? WHERE id = ?", (nxt, provider_id))
            r = c.execute("SELECT * FROM transfers WHERE id = ?", (provider_id,)).fetchone()
        return self._result(r)

    def count_transfers(self, reference_prefix: str = "") -> int:
        with self._conn() as c:
            return c.execute(
                "SELECT COUNT(*) FROM transfers WHERE reference LIKE ?", (reference_prefix + "%",)
            ).fetchone()[0]

    # FX ------------------------------------------------------------------
    def create_quote(self, *, sell_currency, buy_currency, buy_amount_minor) -> Quote:
        rate = DEMO_RATES[(sell_currency, buy_currency)]
        sell = convert_ceil(buy_amount_minor, sell_currency, buy_currency, rate)
        qid = "q_" + uuid.uuid4().hex[:12]
        valid_to = self.clock.now() + QUOTE_VALIDITY
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO quotes VALUES (?,?)", (qid, iso(valid_to)))
        return Quote(qid, sell_currency, buy_currency, sell, buy_amount_minor, rate, valid_to, "local_demo_rate")

    def create_conversion(self, *, request_id, quote: Quote) -> ConversionResult:
        fault, self.next_conversion_fault = self.next_conversion_fault, None
        if fault == "timeout_before_accept":
            raise ProviderAmbiguous("simulated timeout before the bank recorded the conversion")
        status = fault if fault in ("SCHEDULED", "CANCELLED", "OVERDUE") else "SETTLED"
        with self._lock, self._conn() as c:
            q = c.execute("SELECT * FROM quotes WHERE id = ?", (quote.provider_quote_id,)).fetchone()
            if not q:
                raise ProviderError("unknown quote")
            if parse_iso(q["valid_to"]) < self.clock.now():
                raise ProviderError("quote expired")
            try:
                cid = "conv_" + uuid.uuid4().hex[:12]
                c.execute("INSERT INTO conversions VALUES (?,?,?,?,?)",
                          (cid, request_id, quote.provider_quote_id, status, iso(self.clock.now())))
            except sqlite3.IntegrityError as exc:
                raise ProviderError("quote already used or request_id reused") from exc
        if fault == "timeout_after_accept":
            raise ProviderAmbiguous("simulated timeout after the bank accepted the conversion")
        return ConversionResult(cid, request_id, normalise_conversion_status(status))

    def _conversion(self, r) -> ConversionResult:
        return ConversionResult(r["id"], r["request_id"], normalise_conversion_status(r["status"]))

    def get_conversion(self, provider_id: str) -> ConversionResult:
        with self._conn() as c:
            r = c.execute("SELECT * FROM conversions WHERE id = ?", (provider_id,)).fetchone()
        if not r:
            raise ProviderError(f"unknown conversion {provider_id}")
        return self._conversion(r)

    def find_conversion(self, request_id: str) -> ConversionResult | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM conversions WHERE request_id = ?", (request_id,)).fetchone()
        return self._conversion(r) if r else None

    def simulate_conversion_status(self, provider_id: str, status: str) -> ConversionResult:
        with self._lock, self._conn() as c:
            c.execute("UPDATE conversions SET status = ? WHERE id = ? AND status IN ('SCHEDULED','OVERDUE')", (status.upper(), provider_id))
        return self.get_conversion(provider_id)

    # Payment links ----------------------------------------------------------
    def create_payment_link(self, *, title, amount_minor, currency, reference) -> PaymentLinkResult:
        # The local bank has no hosted checkout. Callers record an honest draft instead.
        from .base import ProviderUnsupported

        raise ProviderUnsupported("local demo has no hosted payment links; balance-due draft created instead")
