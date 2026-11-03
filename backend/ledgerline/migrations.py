"""Versioned schema migrations for the control-plane DB and each organization's tenant DB.

Each migration runs once, inside a transaction, and is recorded in
`schema_migrations`. Migrations are append-only: never edit a shipped one.
"""
from __future__ import annotations

import sqlite3
from typing import Callable

from .db import SCHEMA as TENANT_V1

Migration = tuple[int, str, str | Callable[[sqlite3.Connection], None]]

CONTROL: list[Migration] = [
    (1, "control plane", """
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  password_changed_at TEXT NOT NULL,
  disabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE organizations (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('workspace','sample')),
  bank_mode TEXT NOT NULL DEFAULT 'local' CHECK (bank_mode IN ('local','airwallex_sandbox')),
  webhook_secret_local TEXT NOT NULL,
  airwallex_webhook_secret TEXT,
  airwallex_global_accounts TEXT NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL
);
CREATE TABLE memberships (
  user_id TEXT NOT NULL REFERENCES users(id),
  org_id TEXT NOT NULL REFERENCES organizations(id),
  role TEXT NOT NULL CHECK (role IN ('owner','operator','viewer')),
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, org_id)
);
CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  org_id TEXT REFERENCES organizations(id),
  csrf_token TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  user_agent TEXT
);
CREATE INDEX sessions_user ON sessions(user_id);
CREATE TABLE invitations (
  token_hash TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(id),
  email TEXT NOT NULL COLLATE NOCASE,
  role TEXT NOT NULL CHECK (role IN ('owner','operator','viewer')),
  invited_by TEXT NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  accepted_at TEXT,
  revoked_at TEXT
);
CREATE TABLE login_failures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE INDEX login_failures_key ON login_failures(key, at);
CREATE TABLE control_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  org_id TEXT,
  action TEXT NOT NULL,
  detail TEXT NOT NULL
);
"""),
    (2, "sign in with Google / Apple", """
CREATE TABLE oauth_identities (
  provider TEXT NOT NULL CHECK (provider IN ('google','apple')),
  subject TEXT NOT NULL,
  user_id TEXT NOT NULL REFERENCES users(id),
  email TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_login_at TEXT,
  PRIMARY KEY (provider, subject)
);
CREATE UNIQUE INDEX oauth_identities_user_provider ON oauth_identities(user_id, provider);
CREATE TABLE oauth_states (
  state_hash TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  binding_hash TEXT NOT NULL,
  nonce TEXT NOT NULL,
  code_verifier TEXT,
  intent TEXT NOT NULL CHECK (intent IN ('signin','link')),
  link_user_id TEXT REFERENCES users(id),
  return_to TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
)
"""),
    (3, "server-wide Claude call budget", """
CREATE TABLE claude_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  org_id TEXT NOT NULL,
  day TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('reserved','succeeded','failed')),
  reserved_at TEXT NOT NULL,
  settled_at TEXT,
  detail TEXT
);
CREATE INDEX claude_calls_day ON claude_calls(day, org_id)
"""),
    (4, "each organization's own Airwallex credentials, encrypted", "ALTER TABLE organizations ADD COLUMN airwallex_credentials_enc TEXT"),
    (5, "limits on new accounts and organizations per address", """
CREATE TABLE creations (
  at TEXT NOT NULL,
  ip TEXT NOT NULL,
  what TEXT NOT NULL
);
CREATE INDEX creations_ip_at ON creations(ip, at);
CREATE INDEX creations_at ON creations(at)
"""),
]


def _tenant_v2(conn: sqlite3.Connection) -> None:
    # conn.execute, not executescript: executescript would COMMIT the migration transaction early.
    conn.execute("""
CREATE TABLE IF NOT EXISTS invoice_adjustments (
  id TEXT PRIMARY KEY,
  invoice_id TEXT NOT NULL REFERENCES invoices(id),
  currency TEXT NOT NULL,
  delta_minor INTEGER NOT NULL CHECK (delta_minor != 0),
  reason TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
)""")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(approvals)")}
    if "created_by" not in cols:
        conn.execute("ALTER TABLE approvals ADD COLUMN created_by TEXT")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(customers)")}
    if "updated_at" not in cols:
        conn.execute("ALTER TABLE customers ADD COLUMN updated_at TEXT")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(invoices)")}
    if "voided_at" not in cols:
        conn.execute("ALTER TABLE invoices ADD COLUMN voided_at TEXT")


def _tenant_v6(conn: sqlite3.Connection) -> None:
    """Hash chain over the audit log, including events written before this version, plus stored plan runs."""
    from .audit import GENESIS, event_hash

    conn.execute("ALTER TABLE audit_events ADD COLUMN prev_hash TEXT")
    conn.execute("ALTER TABLE audit_events ADD COLUMN hash TEXT")
    prev = GENESIS
    rows = conn.execute("SELECT id, at, actor, action, entity_type, entity_id, operation_id, detail FROM audit_events ORDER BY id").fetchall()
    for r in rows:
        digest = event_hash(prev, r[1], r[2], r[3], r[4], r[5], r[6], r[7])
        conn.execute("UPDATE audit_events SET prev_hash = ?, hash = ? WHERE id = ?", (prev, digest, r[0]))
        prev = digest
    conn.execute("""
CREATE TABLE IF NOT EXISTS plan_runs (
  id TEXT PRIMARY KEY,
  at TEXT NOT NULL,
  trigger TEXT NOT NULL,
  inputs TEXT NOT NULL,
  output TEXT NOT NULL,
  inputs_hash TEXT NOT NULL,
  output_hash TEXT NOT NULL
)""")


TENANT: list[Migration] = [
    (1, "ledger schema", TENANT_V1),
    (2, "invoice adjustments, approval author, edit timestamps", _tenant_v2),
    # Hosted mode stores the simulated payer agents' private keys here, encrypted (payer_agents/keys.py).
    (3, "encrypted payer-agent signing keys", "CREATE TABLE IF NOT EXISTS agent_keys (customer_id TEXT PRIMARY KEY, private_key_enc TEXT NOT NULL, created_at TEXT NOT NULL)"),
    (4, "bill priority, deferral limit and short-cash decisions", """
ALTER TABLE obligations ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal';
ALTER TABLE obligations ADD COLUMN defer_until TEXT;
CREATE TABLE IF NOT EXISTS treasury_decisions (
  obligation_id TEXT PRIMARY KEY REFERENCES obligations(id),
  decision TEXT NOT NULL,
  rank_no INTEGER NOT NULL,
  shortfall_minor INTEGER NOT NULL,
  source_currency TEXT,
  reason TEXT NOT NULL,
  version INTEGER NOT NULL,
  decided_at TEXT NOT NULL,
  trigger TEXT NOT NULL
)"""),
    (5, "bill payments through the bank", """
CREATE TABLE IF NOT EXISTS bill_payments (
  id TEXT PRIMARY KEY,
  obligation_id TEXT NOT NULL REFERENCES obligations(id),
  request_id TEXT NOT NULL UNIQUE,
  currency TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  destination TEXT NOT NULL,
  scope_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  proposed_by TEXT NOT NULL,
  decided_by TEXT,
  decided_at TEXT,
  provider_id TEXT,
  needs_reconciliation INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  lease_until TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_payment_per_bill
  ON bill_payments(obligation_id) WHERE status NOT IN ('rejected','invalidated','failed','cancelled')"""),
    (6, "hash-chained audit log and replayable plan runs", _tenant_v6),
    (7, "early-payment offers", """
CREATE TABLE IF NOT EXISTS early_pay_offers (
  id TEXT PRIMARY KEY,
  invoice_id TEXT NOT NULL REFERENCES invoices(id),
  customer_id TEXT NOT NULL REFERENCES customers(id),
  currency TEXT NOT NULL,
  invoice_remaining_minor INTEGER NOT NULL,
  discount_bps INTEGER NOT NULL,
  discount_minor INTEGER NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  status TEXT NOT NULL,
  url TEXT,
  provider_id TEXT,
  deposit_id TEXT,
  note TEXT,
  offered_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_offer_per_invoice
  ON early_pay_offers(invoice_id) WHERE status IN ('creating','open','unknown')"""),
    (8, "wrong-currency payments converted to settle an invoice", """
CREATE TABLE IF NOT EXISTS deposit_conversions (
  id TEXT PRIMARY KEY,
  deposit_id TEXT NOT NULL REFERENCES deposits(id),
  invoice_id TEXT NOT NULL REFERENCES invoices(id),
  operation_id TEXT NOT NULL,
  sell_currency TEXT NOT NULL,
  sell_minor INTEGER NOT NULL CHECK (sell_minor > 0),
  buy_currency TEXT NOT NULL,
  buy_minor INTEGER NOT NULL CHECK (buy_minor > 0),
  status TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_conversion_per_deposit
  ON deposit_conversions(deposit_id) WHERE status = 'processing'"""),
    (9, "bills that release an invoice when paid", "ALTER TABLE obligations ADD COLUMN unlocks_invoice_id TEXT"),
    (10, "a customer's own payer agent, reached over the network, and who set its key", """
ALTER TABLE customers ADD COLUMN agent_url TEXT;
ALTER TABLE customers ADD COLUMN agent_key_set_by TEXT;
ALTER TABLE customers ADD COLUMN agent_key_set_at TEXT
"""),
]


def migrate(conn: sqlite3.Connection, migrations: list[Migration]) -> list[int]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    ran = []
    for version, name, step in migrations:
        if version in applied:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            if version not in {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}:
                if callable(step):
                    step(conn)
                else:
                    for statement in [s for s in step.split(";\n") if s.strip()]:
                        conn.execute(statement)
                conn.execute("INSERT INTO schema_migrations(version, name) VALUES (?, ?)", (version, name))
                ran.append(version)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    from .pg import harden

    harden(conn)  # no-op on SQLite
    return ran
