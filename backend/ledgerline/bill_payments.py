"""Paying a bill through the bank, with the same controls as refunds.

- A second person always approves. The approval binds bill, amount, currency and destination by hash.
- One live payment per bill (unique partial index), one stable request_id per payment.
- Only a bill the plan currently decides to fund can be paid, checked again under the lock at execution.
- An ambiguous provider response stays processing; the next attempt looks the request_id up first.
- SENT is not final. The bill stays scheduled and its cash stays committed until PAID.
- The pause switch blocks every submission, including retries.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from . import audit, crypto, db, treasury
from .clock import iso, parse_iso
from .context import AppContext
from .money import fmt
from .payouts import LEASE, REQUEST_NS, Paused, PayoutError, SelfApproval, StaleApproval
from .providers.base import ProviderAmbiguous, ProviderError

_FINAL_FAIL = ("failed", "cancelled")


def _scope(bill: dict[str, Any], destination: str) -> dict[str, Any]:
    return {"operation": "bill_payment", "obligation_id": bill["id"], "payee": bill["payee"], "amount_minor": bill["amount_minor"],
            "currency": bill["currency"], "destination": destination}


def _row(conn, payment_id: str) -> dict[str, Any]:
    p = db.row(conn, "SELECT * FROM bill_payments WHERE id = ?", (payment_id,))
    if p is None:
        raise PayoutError("unknown bill payment")
    return p


def _require_funded(conn, ctx: AppContext, obligation_id: str, rates) -> None:
    d = next((x for x in treasury.rank_bills(conn, ctx, rates) if x["obligation_id"] == obligation_id), None)
    if d is None:
        raise PayoutError("this bill is outside the planning window; bring it into the plan before paying it")
    if d["decision"] != "fund":
        raise PayoutError(f"the plan for this bill is to {d['decision']}, not fund it: {d['reason']}")


def _check_destination(ctx: AppContext, destination: str, currency: str) -> None:
    """On a connected account the destination must be one of that account's beneficiaries, in the bill's currency."""
    if ctx.sandbox is None:
        return
    from .beneficiaries import summary

    match = next((summary(i) for i in ctx.sandbox.list_beneficiaries() if i.get("id") == destination), None)
    if match is None:
        raise PayoutError("that beneficiary is not on the connected Airwallex account")
    if match["currency"] != currency:
        raise PayoutError(f"that beneficiary is paid in {match['currency']}, not {currency}")


def propose(ctx: AppContext, obligation_id: str, destination: Any, actor: str) -> dict[str, Any]:
    if not isinstance(destination, str) or not 2 <= len(destination.strip()) <= 120:
        raise PayoutError("choose who receives this payment")
    destination = destination.strip()
    rates = treasury.decision_rates(ctx)
    with ctx.conn() as conn:
        bill = db.row(conn, "SELECT currency FROM obligations WHERE id = ?", (obligation_id,))
    if bill is None:
        raise PayoutError("unknown bill")
    _check_destination(ctx, destination, bill["currency"])
    with ctx.conn() as conn, db.transaction(conn):
        bill = db.row(conn, "SELECT * FROM obligations WHERE id = ?", (obligation_id,))
        if bill["status"] != "scheduled":
            raise PayoutError("this bill is already paid")
        if db.row(conn, "SELECT id FROM bill_payments WHERE obligation_id = ? AND status NOT IN ('rejected','invalidated','failed','cancelled')", (obligation_id,)):
            raise PayoutError("a payment for this bill already exists (duplicate lock)")
        _require_funded(conn, ctx, obligation_id, rates)
        now = iso(ctx.clock.now())
        pid = "PAY-" + uuid.uuid4().hex[:8].upper()
        scope = _scope(bill, destination)
        conn.execute(
            "INSERT INTO bill_payments(id, obligation_id, request_id, currency, amount_minor, destination, scope_hash, status, proposed_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,'proposed',?,?,?)",
            (pid, obligation_id, str(uuid.uuid5(REQUEST_NS, pid)), bill["currency"], bill["amount_minor"], destination,
             crypto.scope_hash(scope), actor, now, now))
        audit.record(conn, now, actor, "bill_payment.proposed", "bill_payment", pid, {"scope": scope, "scope_hash": crypto.scope_hash(scope)})
        return _row(conn, pid)


def _scope_problem(conn, p: dict[str, Any]) -> str | None:
    bill = db.row(conn, "SELECT * FROM obligations WHERE id = ?", (p["obligation_id"],))
    if bill["status"] != "scheduled":
        return "the bill is already paid"
    if crypto.scope_hash(_scope(bill, p["destination"])) != p["scope_hash"]:
        return "the bill changed after this payment was proposed"
    return None


def _invalidate(ctx: AppContext, p: dict[str, Any], why: str) -> None:
    with ctx.conn() as conn, db.transaction(conn):
        now = iso(ctx.clock.now())
        conn.execute("UPDATE bill_payments SET status='invalidated', last_error=?, updated_at=? WHERE id = ?", (why, now, p["id"]))
        audit.record(conn, now, "system", "bill_payment.invalidated", "bill_payment", p["id"], {"reason": why})


def decide(ctx: AppContext, payment_id: str, *, approve: bool, actor: str, seen_scope_hash: str) -> dict[str, Any]:
    problem = None
    with ctx.conn() as conn, db.transaction(conn):
        p = _row(conn, payment_id)
        if p["status"] != "proposed":
            raise PayoutError(f"this payment is {p['status']}, not waiting for a decision")
        if seen_scope_hash != p["scope_hash"]:
            raise StaleApproval("the payment you saw is not the one on record; reload and review again")
        if approve and p["proposed_by"] == actor:
            raise SelfApproval("you proposed this payment; a different team member must approve it")
        problem = _scope_problem(conn, p)
        if not problem:
            now = iso(ctx.clock.now())
            conn.execute("UPDATE bill_payments SET status=?, decided_by=?, decided_at=?, updated_at=? WHERE id = ?",
                         ("approved" if approve else "rejected", actor, now, now, payment_id))
            audit.record(conn, now, actor, "bill_payment.approved" if approve else "bill_payment.rejected", "bill_payment", payment_id,
                         {"scope_hash": p["scope_hash"]})
    if problem:
        _invalidate(ctx, p, problem)
        raise StaleApproval(problem)
    with ctx.conn() as conn:
        return _row(conn, payment_id)


def _claim(ctx: AppContext, payment_id: str, actor: str, rates) -> tuple[dict[str, Any], bool] | None:
    """Move to processing under the lock so concurrent callers cannot both reach the bank. None: nothing to send."""
    problem = None
    with ctx.conn() as conn, db.transaction(conn):
        now_dt = ctx.clock.now()
        now = iso(now_dt)
        p = _row(conn, payment_id)
        first = p["status"] == "approved"
        retry = p["status"] == "processing" and p["needs_reconciliation"]
        if not first and not retry:
            if p["status"] in ("proposed", "rejected", "invalidated"):
                raise PayoutError(f"this payment is {p['status']}; it must be approved before it is sent")
            return None
        if p["lease_until"] and parse_iso(p["lease_until"]) > now_dt:
            return None  # another caller is talking to the bank right now
        if ctx.paused(conn):
            raise Paused("money-out is paused; the payment is kept and can be sent after resume")
        if first:
            problem = _scope_problem(conn, p)
            if not problem:
                _require_funded(conn, ctx, p["obligation_id"], rates)
        if not problem:
            conn.execute("UPDATE bill_payments SET status='processing', needs_reconciliation=1, attempts=attempts+1, lease_until=?, updated_at=? WHERE id = ?",
                         (iso(now_dt + timedelta(seconds=LEASE.total_seconds())), now, payment_id))
            audit.record(conn, now, actor, "bill_payment.submitting", "bill_payment", payment_id,
                         {"request_id": p["request_id"], "lookup_first": not first})
            return _row(conn, payment_id), not first
    _invalidate(ctx, p, problem)
    raise StaleApproval(problem)


def execute(ctx: AppContext, payment_id: str, actor: str) -> dict[str, Any]:
    """Send (or reconcile) the payment. Safe to call repeatedly and concurrently."""
    claimed = _claim(ctx, payment_id, actor, treasury.decision_rates(ctx))
    if claimed is None:
        with ctx.conn() as conn:
            return _row(conn, payment_id)
    p, lookup_first = claimed
    result, error, ambiguous = None, None, False
    try:
        if lookup_first:
            result = ctx.provider.find_transfer(p["request_id"])
        if result is None:
            result = ctx.provider.create_transfer(
                request_id=p["request_id"], amount_minor=p["amount_minor"], currency=p["currency"], destination=p["destination"],
                reference=f"Ledgerline bill {p['obligation_id']}", reason="goods_purchased")
    except ProviderAmbiguous as exc:
        ambiguous, error = True, str(exc)
    except ProviderError as exc:
        error = str(exc)
        if lookup_first:  # a rejection on a retry may only mean "duplicate request_id": look again before deciding
            try:
                result = ctx.provider.find_transfer(p["request_id"])
            except (ProviderError, ProviderAmbiguous):
                pass
            ambiguous = result is None
    with ctx.conn() as conn, db.transaction(conn):
        now = iso(ctx.clock.now())
        if result is not None:
            conn.execute("UPDATE bill_payments SET provider_id=?, needs_reconciliation=0, last_error=NULL, lease_until=NULL, updated_at=? WHERE id = ?",
                         (result.provider_id, now, payment_id))
            _apply(conn, ctx, _row(conn, payment_id), result.status, now)
        elif ambiguous:
            conn.execute("UPDATE bill_payments SET needs_reconciliation=1, last_error=?, lease_until=NULL, updated_at=? WHERE id = ?", (error, now, payment_id))
            audit.record(conn, now, "system", "bill_payment.ambiguous", "bill_payment", payment_id, {"error": error})
        else:
            conn.execute("UPDATE bill_payments SET needs_reconciliation=0, last_error=?, lease_until=NULL, updated_at=? WHERE id = ?", (error, now, payment_id))
            _apply(conn, ctx, _row(conn, payment_id), "failed", now)
        return _row(conn, payment_id)


def _apply(conn, ctx: AppContext, p: dict[str, Any], status: str, now: str) -> None:
    """Cash and the bill change only on PAID: until then the bill stays committed in the plan."""
    if status == p["status"] or p["status"] in ("paid", *_FINAL_FAIL):
        return
    conn.execute("UPDATE bill_payments SET status=?, updated_at=? WHERE id = ?", (status, now, p["id"]))
    audit.record(conn, now, "provider", f"bill_payment.{status}", "bill_payment", p["id"], {"from": p["status"], "provider_id": p["provider_id"]})
    if status == "paid":
        bill = db.row(conn, "SELECT * FROM obligations WHERE id = ?", (p["obligation_id"],))
        conn.execute("UPDATE obligations SET status = 'paid' WHERE id = ?", (p["obligation_id"],))
        audit.post(conn, now, f"Bill {p['obligation_id']} paid: {bill['payee']} ({fmt(p['amount_minor'], p['currency'])})", "bill_payment", p["id"],
                   audit.move("bills_paid", f"cash:{p['currency']}", p["currency"], p["amount_minor"]))


def sync(ctx: AppContext, payment_id: str, actor: str = "system") -> dict[str, Any]:
    with ctx.conn() as conn:
        p = _row(conn, payment_id)
    if p["needs_reconciliation"]:
        return execute(ctx, payment_id, actor)
    if p["status"] in ("processing", "sent") and p["provider_id"]:
        result = ctx.provider.get_transfer(p["provider_id"])
        with ctx.conn() as conn, db.transaction(conn):
            _apply(conn, ctx, _row(conn, payment_id), result.status, iso(ctx.clock.now()))
            p = _row(conn, payment_id)
        if p["status"] == "paid":
            treasury.refresh_decisions(ctx, f"{p['obligation_id']} paid", actor)
    return p


def simulate(ctx: AppContext, payment_id: str, next_status: str, actor: str) -> dict[str, Any]:
    """Test-environment control: ask the bank to move the transfer, then read the result back from it."""
    with ctx.conn() as conn:
        p = _row(conn, payment_id)
    allowed = {"processing": {"SENT", "FAILED"}, "sent": {"PAID", "FAILED"}}
    if not p["provider_id"] or next_status not in allowed.get(p["status"], set()):
        raise PayoutError("simulation must move a processing payment to SENT, then a sent payment to PAID or FAILED")
    ctx.provider.simulate_transfer_status(p["provider_id"], next_status)
    return sync(ctx, payment_id, actor)


def list_payments(ctx: AppContext) -> list[dict[str, Any]]:
    with ctx.conn() as conn:
        return db.rows(conn, "SELECT p.*, o.payee FROM bill_payments p JOIN obligations o ON o.id = p.obligation_id ORDER BY p.created_at DESC")
