"""A company's records as CSV files in one zip, for a spreadsheet or another system. Read-only.

Nothing secret is included: no keys, no stored plan inputs. A cell that a spreadsheet would read as a formula (it starts
with =, +, -, @, a tab or a carriage return) gets a leading apostrophe, so opening the file cannot run anything.
"""
from __future__ import annotations

import csv
import io
import zipfile
from typing import Any

from .clock import iso
from .context import AppContext

TABLES: list[tuple[str, str]] = [
    ("customers", "SELECT id, name, country, payer_names, agent_key_id, agent_url, refund_beneficiary FROM customers ORDER BY id"),
    ("invoices", "SELECT * FROM invoices ORDER BY id"),
    ("payments", "SELECT * FROM deposits ORDER BY received_at, id"),
    ("plans", "SELECT deposit_id, version, kind, category, summary, actions, evidence_id, created_at FROM plans ORDER BY deposit_id, version"),
    ("evidence", "SELECT id, deposit_id, asked_customer_id, version, source, transport, verdict, reason, checks, created_at FROM evidence ORDER BY deposit_id, version"),
    ("allocations", "SELECT * FROM allocations"),
    ("credits", "SELECT * FROM credits"),
    ("approvals", "SELECT * FROM approvals ORDER BY created_at"),
    ("transfers", "SELECT * FROM operations ORDER BY created_at"),
    ("bills", "SELECT * FROM obligations ORDER BY due_at, id"),
    ("bill_payments", "SELECT * FROM bill_payments ORDER BY created_at"),
    ("audit_log", "SELECT id, at, actor, action, entity_type, entity_id, operation_id, detail, prev_hash, hash FROM audit_events ORDER BY id"),
]
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _cell(v: Any) -> Any:
    if isinstance(v, str) and v.startswith(_FORMULA):
        return "'" + v
    return v


def _csv(rows: list[dict[str, Any]], columns: list[str]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(columns)
    for r in rows:
        w.writerow([_cell(r[c]) for c in columns])
    return out.getvalue()


def build(ctx: AppContext, exported_by: str) -> tuple[bytes, str]:
    """The zip's bytes and a file name."""
    now = ctx.clock.now()
    buf = io.BytesIO()
    counts = []
    with ctx.conn() as conn, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, sql in TABLES:
            cur = conn.execute(sql)
            fetched = cur.fetchall()
            rows = [dict(r) for r in fetched] if fetched else []
            described = getattr(cur, "description", None)  # SQLite names the columns even when there are no rows
            columns = [d[0] for d in described] if described else (list(rows[0]) if rows else [])
            z.writestr(f"{name}.csv", "\ufeff" + _csv(rows, columns))  # the byte-order mark lets Excel read UTF-8
            counts.append(f"{name}.csv: {len(rows)} rows")
        org = ctx.org or {}
        z.writestr("README.txt", "\r\n".join([
            f"Ledgerline export of {org.get('name', '')} ({org.get('id', '')})",
            f"Exported {iso(now)} by {exported_by}.",
            "Amounts are in minor units (cents): divide by 100 for USD, EUR and GBP.",
            "Cells that start with =, +, -, @ have a leading apostrophe so a spreadsheet does not run them.",
            "The audit log's hash columns let you check that no entry was changed: each hash covers the entry and the one before.",
            "",
            *counts,
        ]) + "\r\n")
    stamp = now.strftime("%Y%m%d")
    return buf.getvalue(), f"ledgerline-{org.get('id', 'export')}-{stamp}.zip"


def table_names() -> list[str]:
    return [n for n, _ in TABLES]
