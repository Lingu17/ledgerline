"""Append-only audit trail and balanced double-entry journal."""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Any


def record(
    conn: sqlite3.Connection,
    at: str,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    detail: dict[str, Any] | None = None,
    operation_id: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO audit_events(at, actor, action, entity_type, entity_id, operation_id, detail)"
        " VALUES (?,?,?,?,?,?,?)",
        (at, actor, action, entity_type, entity_id, operation_id, json.dumps(detail or {}, sort_keys=True)),
    )


class UnbalancedJournal(ValueError):
    pass


def post(
    conn: sqlite3.Connection,
    at: str,
    memo: str,
    ref_type: str,
    ref_id: str,
    lines: list[tuple[str, str, int, int]],
) -> int:
    """lines: (account, currency, debit_minor, credit_minor). Must balance per currency."""
    totals: dict[str, int] = defaultdict(int)
    for _account, ccy, dr, cr in lines:
        if dr < 0 or cr < 0 or (dr and cr):
            raise UnbalancedJournal("each line is either a debit or a credit")
        totals[ccy] += dr - cr
    if any(v != 0 for v in totals.values()):
        raise UnbalancedJournal(f"journal does not balance per currency: {dict(totals)}")
    cur = conn.execute(
        "INSERT INTO journal_entries(memo, ref_type, ref_id, at) VALUES (?,?,?,?)", (memo, ref_type, ref_id, at)
    )
    entry_id = int(cur.lastrowid)
    conn.executemany(
        "INSERT INTO journal_lines(entry_id, account, currency, debit_minor, credit_minor) VALUES (?,?,?,?,?)",
        [(entry_id, a, c, d, k) for a, c, d, k in lines],
    )
    return entry_id


def move(account_dr: str, account_cr: str, ccy: str, amount: int) -> list[tuple[str, str, int, int]]:
    return [(account_dr, ccy, amount, 0), (account_cr, ccy, 0, amount)]


def account_balance(conn: sqlite3.Connection, account: str, ccy: str) -> int:
    """Debit-positive balance."""
    r = conn.execute(
        "SELECT COALESCE(SUM(debit_minor - credit_minor), 0) AS b FROM journal_lines WHERE account = ? AND currency = ?",
        (account, ccy),
    ).fetchone()
    return int(r["b"])
