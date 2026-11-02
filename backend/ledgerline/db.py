"""SQLite storage. Every write path goes through `transaction()` (BEGIN IMMEDIATE)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  country TEXT NOT NULL,
  payer_names TEXT NOT NULL,            -- JSON list of remitter names seen on deposits
  agent_key_id TEXT,                    -- registered explain_payment signing key id
  agent_public_key TEXT,                -- base64 raw Ed25519 public key
  refund_beneficiary TEXT NOT NULL,     -- destination label for refunds (synthetic)
  demo_only INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS invoices (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers(id),
  currency TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  prior_paid_minor INTEGER NOT NULL DEFAULT 0 CHECK (prior_paid_minor >= 0),
  status TEXT NOT NULL CHECK (status IN ('open','scheduled','paid')),
  issued_at TEXT NOT NULL,
  due_at TEXT NOT NULL,
  description TEXT NOT NULL,
  CHECK (prior_paid_minor <= amount_minor)
);

CREATE TABLE IF NOT EXISTS deposits (
  id TEXT PRIMARY KEY,
  provider_ref TEXT NOT NULL UNIQUE,
  source TEXT NOT NULL,                 -- local_simulated_webhook | airwallex_sandbox
  global_account_id TEXT,
  currency TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  payer_name TEXT NOT NULL,
  reference TEXT NOT NULL DEFAULT '',
  received_at TEXT NOT NULL,
  status TEXT NOT NULL,
  category TEXT,
  customer_id TEXT REFERENCES customers(id),
  version INTEGER NOT NULL DEFAULT 1,   -- bumps on every mutation; approvals bind to it
  escalation_reason TEXT
);

CREATE TABLE IF NOT EXISTS plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deposit_id TEXT NOT NULL REFERENCES deposits(id),
  version INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('initial','revised','operator')),
  category TEXT NOT NULL,
  summary TEXT NOT NULL,
  actions TEXT NOT NULL,                -- JSON list
  evidence_id TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (deposit_id, version)
);

CREATE TABLE IF NOT EXISTS allocations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deposit_id TEXT NOT NULL REFERENCES deposits(id),
  invoice_id TEXT NOT NULL REFERENCES invoices(id),
  currency TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  created_at TEXT NOT NULL,
  UNIQUE (deposit_id, invoice_id)
);

CREATE TABLE IF NOT EXISTS writeoffs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id TEXT NOT NULL REFERENCES invoices(id),
  deposit_id TEXT NOT NULL REFERENCES deposits(id),
  currency TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (invoice_id, deposit_id)
);

CREATE TABLE IF NOT EXISTS credits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deposit_id TEXT NOT NULL REFERENCES deposits(id),
  customer_id TEXT NOT NULL REFERENCES customers(id),
  currency TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  earmark_invoice_id TEXT REFERENCES invoices(id),
  evidence_id TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (deposit_id)
);

CREATE TABLE IF NOT EXISTS payment_links (
  id TEXT PRIMARY KEY,
  invoice_id TEXT NOT NULL REFERENCES invoices(id),
  deposit_id TEXT REFERENCES deposits(id),
  currency TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  status TEXT NOT NULL,                 -- local_draft | sandbox_created | paid | draft_fallback
  url TEXT,
  provider_id TEXT,
  note TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (invoice_id, deposit_id)
);

CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  deposit_id TEXT NOT NULL REFERENCES deposits(id),
  asked_customer_id TEXT,
  version INTEGER NOT NULL,
  source TEXT NOT NULL,                 -- mcp_signed | claude_extracted | fixture_extracted
  transport TEXT,
  envelope TEXT NOT NULL,               -- raw JSON as received
  claim_hash TEXT NOT NULL,
  checks TEXT NOT NULL,                 -- JSON list of {name, passed, detail}
  verdict TEXT NOT NULL CHECK (verdict IN ('verified','rejected','advisory')),
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (deposit_id, version)
);

CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  operation_type TEXT NOT NULL,
  deposit_id TEXT REFERENCES deposits(id),
  scope TEXT NOT NULL,                  -- canonical JSON of the bound fields
  scope_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending','approved','rejected','invalidated','executed')),
  reason TEXT NOT NULL,
  decided_by TEXT,
  decided_at TEXT,
  invalidated_reason TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operations (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('refund','fx_conversion')),
  deposit_id TEXT REFERENCES deposits(id),
  request_id TEXT NOT NULL UNIQUE,
  currency TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  destination TEXT NOT NULL,
  status TEXT NOT NULL,
  approval_id TEXT REFERENCES approvals(id),
  provider_id TEXT,
  needs_reconciliation INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  detail TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
-- Durable per-deposit refund lock: at most one live refund per deposit.
CREATE UNIQUE INDEX IF NOT EXISTS one_live_refund_per_deposit
  ON operations(deposit_id) WHERE kind = 'refund' AND status NOT IN ('cancelled','failed');

CREATE TABLE IF NOT EXISTS operation_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  operation_id TEXT NOT NULL REFERENCES operations(id),
  from_status TEXT,
  to_status TEXT NOT NULL,
  detail TEXT NOT NULL,
  at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS obligations (
  id TEXT PRIMARY KEY,
  payee TEXT NOT NULL,
  currency TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  due_at TEXT NOT NULL,
  description TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('scheduled','paid'))
);

CREATE TABLE IF NOT EXISTS fx_quotes (
  id TEXT PRIMARY KEY,
  provider_quote_id TEXT NOT NULL,
  source TEXT NOT NULL,                 -- local_demo_rate | airwallex_sandbox
  sell_currency TEXT NOT NULL,
  buy_currency TEXT NOT NULL,
  sell_amount_minor INTEGER NOT NULL,
  buy_amount_minor INTEGER NOT NULL,
  rate TEXT NOT NULL,                   -- buy per sell, decimal string
  obligation_id TEXT REFERENCES obligations(id),
  valid_to TEXT NOT NULL,
  used_by_operation TEXT UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wallet_opening (
  currency TEXT PRIMARY KEY,
  amount_minor INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS journal_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  memo TEXT NOT NULL,
  ref_type TEXT NOT NULL,
  ref_id TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS journal_lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id INTEGER NOT NULL REFERENCES journal_entries(id),
  account TEXT NOT NULL,
  currency TEXT NOT NULL,
  debit_minor INTEGER NOT NULL DEFAULT 0 CHECK (debit_minor >= 0),
  credit_minor INTEGER NOT NULL DEFAULT 0 CHECK (credit_minor >= 0)
);

-- Payer/reference we recorded when creating a sandbox deposit simulation; the settled webhook omits them.
CREATE TABLE IF NOT EXISTS deposit_hints (
  provider_ref TEXT PRIMARY KEY,
  payer_name TEXT NOT NULL,
  reference TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_events (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  body_sha256 TEXT NOT NULL,
  received_at TEXT NOT NULL,
  result TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  operation_id TEXT,
  detail TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class PgTarget:
    """A logical database stored as one PostgreSQL schema (see pg.py). Used wherever a SQLite path was."""
    url: str
    schema: str

    @property
    def parent(self) -> "PgTarget":  # code that mkdirs the parent of a db path gets a harmless object
        return self

    def mkdir(self, *args: Any, **kwargs: Any) -> None:
        return None

    def __str__(self) -> str:
        return f"postgresql schema {self.schema}"


def connect(db_path: "Path | PgTarget") -> sqlite3.Connection:
    if isinstance(db_path, PgTarget):
        from .pg import PgConnection

        return PgConnection(db_path.url, db_path.schema)  # type: ignore[return-value]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Serialize writers with BEGIN IMMEDIATE; roll back on any exception."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def row(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def rows(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    r = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )
