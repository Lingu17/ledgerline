"""Per-currency conservation and journal checks. No cross-currency totals."""
from __future__ import annotations

import sqlite3
from typing import Any

from . import db
from .money import CURRENCY_EXPONENT, fmt


def _s(conn, sql, params=()) -> int:
    return int(conn.execute(sql, params).fetchone()[0] or 0)


def _bal(conn, account: str, ccy: str) -> int:
    return _s(conn, "SELECT COALESCE(SUM(debit_minor - credit_minor),0) FROM journal_lines WHERE account = ? AND currency = ?",
              (account, ccy))


def conservation(conn: sqlite3.Connection) -> dict[str, Any]:
    """deposits = allocated + credits + refunds paid + refunds pending + unapplied, per currency.

    `unapplied` is read from the journal (credit balance of unapplied_cash), not
    derived by subtraction, so the equation is a real cross-check between the
    operational tables and the double-entry postings.
    """
    out: dict[str, Any] = {"currencies": {}, "all_balanced": True}
    for ccy in CURRENCY_EXPONENT:
        deposits = _s(conn, "SELECT COALESCE(SUM(amount_minor),0) FROM deposits WHERE currency = ?", (ccy,))
        allocated = _s(conn, "SELECT COALESCE(SUM(amount_minor),0) FROM allocations WHERE currency = ?", (ccy,))
        credits = _s(conn, "SELECT COALESCE(SUM(amount_minor),0) FROM credits WHERE currency = ?", (ccy,))
        refunds_paid = _s(conn, "SELECT COALESCE(SUM(amount_minor),0) FROM operations WHERE kind='refund' AND currency=? AND status='paid'", (ccy,))
        refunds_pending = _s(conn, "SELECT COALESCE(SUM(amount_minor),0) FROM operations WHERE kind='refund' AND currency=? AND status IN ('pending','processing','sent')", (ccy,))
        unapplied = -_bal(conn, "unapplied_cash", ccy)
        converted = _s(conn, "SELECT COALESCE(SUM(sell_minor),0) FROM deposit_conversions WHERE sell_currency = ? AND status = 'settled'", (ccy,))
        rhs = allocated + credits + refunds_paid + refunds_pending + unapplied + converted
        trial = _s(conn, "SELECT COALESCE(SUM(debit_minor - credit_minor),0) FROM journal_lines WHERE currency = ?", (ccy,))
        refund_payable = -_bal(conn, "refund_payable", ccy)
        opening = _s(conn, "SELECT COALESCE(SUM(amount_minor),0) FROM wallet_opening WHERE currency = ?", (ccy,))
        cash = _bal(conn, f"cash:{ccy}", ccy)
        fx_in = _s(conn, "SELECT COALESCE(SUM(debit_minor),0) FROM journal_lines WHERE account = ? AND currency = ? AND entry_id IN (SELECT id FROM journal_entries WHERE memo LIKE 'FX %')", (f"cash:{ccy}", ccy))
        fx_out = _s(conn, "SELECT COALESCE(SUM(credit_minor),0) FROM journal_lines WHERE account = ? AND currency = ? AND entry_id IN (SELECT id FROM journal_entries WHERE memo LIKE 'FX %')", (f"cash:{ccy}", ccy))
        in_transit = _bal(conn, "cash_in_transit", ccy)
        refunds_out_returned = _s(conn, "SELECT COALESCE(SUM(debit_minor),0) FROM journal_lines WHERE account = ? AND currency = ? AND entry_id IN (SELECT id FROM journal_entries WHERE memo LIKE 'Refund % returned')", (f"cash:{ccy}", ccy))
        refunds_out = _s(conn, "SELECT COALESCE(SUM(credit_minor),0) FROM journal_lines WHERE account = ? AND currency = ? AND entry_id IN (SELECT id FROM journal_entries WHERE memo LIKE 'Refund % funds leave wallet')", (f"cash:{ccy}", ccy))
        bills_paid = _bal(conn, "bills_paid", ccy)
        cash_expected = opening + deposits + fx_in - fx_out - refunds_out + refunds_out_returned - bills_paid
        m = lambda v: fmt(v, ccy)  # noqa: E731 - details are read by people: show money, not minor units
        checks = [
            {"name": "deposit_conservation", "passed": deposits == rhs,
             "detail": f"deposits {m(deposits)} vs allocated + credits + refunds + unapplied {m(rhs)}"},
            {"name": "journal_trial_balance", "passed": trial == 0, "detail": f"sum(debits − credits) = {m(trial)}"},
            {"name": "refund_liability", "passed": refund_payable == refunds_pending,
             "detail": f"refund payable {m(refund_payable)} vs refunds not yet paid {m(refunds_pending)}"},
            {"name": "cash_walk", "passed": cash == cash_expected,
             "detail": f"journal cash {m(cash)} vs opening + deposits ± FX − refunds − bills paid {m(cash_expected)}"},
            {"name": "no_negative_unapplied", "passed": unapplied >= 0, "detail": f"unapplied {m(unapplied)}"},
        ]
        balanced = all(c["passed"] for c in checks)
        out["all_balanced"] = out["all_balanced"] and balanced
        out["currencies"][ccy] = {
            "currency": ccy,
            "deposits": deposits,
            "allocated": allocated,
            "customer_credits": credits,
            "refunds_paid": refunds_paid,
            "refunds_pending": refunds_pending,
            "unapplied": unapplied,
            "converted": converted,
            "opening_balance": opening,
            "fx_in": fx_in,
            "fx_out": fx_out,
            "refunds_cash_out": refunds_out - refunds_out_returned,
            "cash_in_transit": in_transit,
            "wallet_cash": cash,
            "bank_fee_writeoffs": _s(conn, "SELECT COALESCE(SUM(amount_minor),0) FROM writeoffs WHERE currency = ?", (ccy,)),
            "balanced": balanced,
            "checks": checks,
        }
    return out


def journal(conn: sqlite3.Connection, limit: int = 200) -> list[dict[str, Any]]:
    entries = db.rows(conn, "SELECT * FROM journal_entries ORDER BY id DESC LIMIT ?", (limit,))
    for e in entries:
        e["lines"] = db.rows(conn, "SELECT account, currency, debit_minor, credit_minor FROM journal_lines WHERE entry_id = ?", (e["id"],))
    return entries


def per_deposit_check(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    from .reconcile import deposit_buckets

    out = []
    for d in db.rows(conn, "SELECT id FROM deposits ORDER BY id"):
        b = deposit_buckets(conn, d["id"])
        out.append({"deposit_id": d["id"], **b, "ok": b["unapplied"] >= 0})
    return out
