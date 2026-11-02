"""Append-only, hash-chained audit trail and balanced double-entry journal.

Each event's hash covers its own fields and the previous event's hash, so editing, removing or reordering an
event breaks every later link. Rewriting the whole chain needs database write access and is caught only by
comparing the head with a copy kept elsewhere, such as a downloaded evidence export.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Any

from . import crypto

GENESIS = "0" * 64


def event_hash(prev: str, at: str, actor: str, action: str, entity_type: str, entity_id: str, operation_id: str | None, detail: str) -> str:
    return crypto.sha256_hex(crypto.canonical_json({
        "prev": prev, "at": at, "actor": actor, "action": action, "entity_type": entity_type,
        "entity_id": entity_id, "operation_id": operation_id, "detail": detail}))


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
    from . import db

    text = json.dumps(detail or {}, sort_keys=True)
    last = conn.execute("SELECT hash FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
    prev = (last[0] if last else None) or GENESIS
    digest = event_hash(prev, at, actor, action, entity_type, entity_id, operation_id, text)
    conn.execute(
        "INSERT INTO audit_events(at, actor, action, entity_type, entity_id, operation_id, detail, prev_hash, hash)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (at, actor, action, entity_type, entity_id, operation_id, text, prev, digest),
    )
    count = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    db.set_setting(conn, "audit_chain", {"count": count, "head": digest})


def verify_chain(conn: sqlite3.Connection) -> dict[str, Any]:
    """Recompute every link. Also catches removal of the newest events, using the recorded count and head."""
    from . import db

    prev, count = GENESIS, 0
    for e in db.rows(conn, "SELECT * FROM audit_events ORDER BY id"):
        count += 1
        expected = event_hash(prev, e["at"], e["actor"], e["action"], e["entity_type"], e["entity_id"], e["operation_id"], e["detail"])
        if e["prev_hash"] != prev or e["hash"] != expected:
            return {"ok": False, "events": count, "head": prev, "broken_at": e["id"],
                    "problem": f"event {e['id']} ({e['action']}) does not match its hash; it or an earlier event was changed or removed"}
        prev = e["hash"]
    anchor = db.get_setting(conn, "audit_chain")
    if anchor and (anchor["count"] != count or anchor["head"] != prev):
        return {"ok": False, "events": count, "head": prev, "broken_at": None,
                "problem": f"the log has {count} events ending in a different hash than the {anchor['count']} recorded; newest events were removed or replaced"}
    return {"ok": True, "events": count, "head": prev, "broken_at": None, "problem": None}


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
