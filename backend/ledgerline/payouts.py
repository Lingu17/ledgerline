"""Refund approvals and execution.

Invariants enforced here:
- An approval binds operation, deposit (and its version), amount, currency,
  destination and the evidence version. Execution recomputes that scope inside
  a DB transaction; any difference invalidates the approval.
- At most one live refund per deposit (unique partial index), one stable
  request_id per approval, and a submission lease so concurrent callers cannot
  double-submit.
- An ambiguous provider response leaves the refund `processing` with
  needs_reconciliation=1. The next attempt looks the request_id up first.
- SENT is not final. The refund liability is only released when PAID.
- The pause switch blocks every submission, including retries of pending ones.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import timedelta
from typing import Any

from . import audit, crypto, db
from .clock import iso, parse_iso
from .context import AppContext
from .providers.base import ProviderAmbiguous, ProviderError, TransferResult
from .reconcile import (
    ESCALATED,
    REFUND_APPROVAL,
    REFUND_IN_FLIGHT,
    REFUNDED,
    ReconcileError,
    deposit_buckets,
)
from .sender import through_sender

REQUEST_NS = uuid.UUID("8f1d3c52-7f0e-4a51-9a39-3b6e2f0c9d11")
LEASE = timedelta(seconds=60)


class PayoutError(ValueError):
    pass


class Paused(PayoutError):
    pass


class StaleApproval(PayoutError):
    pass


class SelfApproval(PayoutError):
    """Four-eyes rule: whoever proposed a money-out cannot approve it."""


class PracticeOnly(PayoutError):
    """Something that exists only in a practice company was asked for in a real one."""


# A labelled stand-in in practice companies, so one person can finish the walkthrough. It can only send, never approve.
PRACTICE_TEAMMATE = "practice-teammate"


def same_person(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and a.casefold() == b.casefold()


# --------------------------------------------------------------------------- scope
def current_scope(conn: sqlite3.Connection, deposit_id: str, amount_minor: int, evidence_id: str | None) -> dict[str, Any]:
    d = db.row(conn, "SELECT * FROM deposits WHERE id = ?", (deposit_id,))
    if d is None or not d["customer_id"]:
        raise PayoutError("refund needs a deposit with an identified payer")
    cust = db.row(conn, "SELECT refund_beneficiary FROM customers WHERE id = ?", (d["customer_id"],))
    ev = db.row(conn, "SELECT id, version, claim_hash FROM evidence WHERE id = ?", (evidence_id,)) if evidence_id else None
    latest_ev = db.row(conn, "SELECT id FROM evidence WHERE deposit_id = ? ORDER BY version DESC LIMIT 1", (deposit_id,))
    return {
        "operation": "refund",
        "deposit_id": deposit_id,
        "deposit_version": d["version"],
        "amount_minor": amount_minor,
        "currency": d["currency"],
        "destination": cust["refund_beneficiary"],
        "evidence_id": ev["id"] if ev else None,
        "evidence_version": ev["version"] if ev else None,
        "evidence_claim_hash": ev["claim_hash"] if ev else None,
        "latest_evidence_id": latest_ev["id"] if latest_ev else None,
    }


def approval_expired(ctx: AppContext, conn: sqlite3.Connection, decided_at: str | None) -> int | None:
    """The approval window in hours if an approval given at decided_at has run out, else None. Practice companies never
    expire, so a judge who comes back days later can still finish."""
    if not decided_at or (ctx.org and ctx.org.get("kind") == "sample"):
        return None
    hours = ctx.policy(conn)["approval_ttl_hours"]
    try:
        given = parse_iso(decided_at)
    except ValueError:
        return hours  # an approval time that cannot be read counts as expired
    return hours if ctx.clock.now() - given >= timedelta(hours=hours) else None


def sender_must_differ(a: dict[str, Any]) -> bool:
    """Two people must be involved. If a person proposed it, the approver is the second; if not, the sender has to be.
    created_by is empty on older rows, "system" for the agent's proposals, and an email for a team member."""
    proposer = a.get("created_by") or ""
    by_person = bool(proposer) and proposer not in ("system", "rules", "agent") and ":" not in proposer
    return not by_person and a.get("decided_by") != "policy:auto_limit"


def create_refund_approval(conn: sqlite3.Connection, ctx: AppContext, deposit_id: str, *, amount_minor: int,
                           evidence_id: str | None, reason: str, actor: str = "system") -> dict[str, Any]:
    now = iso(ctx.clock.now())
    live = db.row(conn, "SELECT * FROM approvals WHERE deposit_id = ? AND status IN ('pending','approved')", (deposit_id,))
    if live:
        return live
    if amount_minor > deposit_buckets(conn, deposit_id)["unapplied"]:
        raise PayoutError("refund exceeds the deposit's unapplied amount")
    scope = current_scope(conn, deposit_id, amount_minor, evidence_id)
    policy = ctx.policy(conn)
    within_limit = amount_minor <= policy["refund_auto_limit_minor"][scope["currency"]] and evidence_id is not None
    approval_id = "APR-" + uuid.uuid4().hex[:8].upper()
    status = "approved" if within_limit else "pending"
    conn.execute(
        "INSERT INTO approvals(id, operation_type, deposit_id, scope, scope_hash, status, reason, decided_by, decided_at, invalidated_reason, created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (approval_id, "refund", deposit_id, crypto.canonical_json(scope).decode(), crypto.scope_hash(scope), status, reason,
         "policy:auto_limit" if within_limit else None, now if within_limit else None, None, now, actor),
    )
    audit.record(conn, now, actor, "approval.created", "approval", approval_id,
                 {"deposit_id": deposit_id, "status": status, "scope_hash": crypto.scope_hash(scope), "scope": scope})
    return db.row(conn, "SELECT * FROM approvals WHERE id = ?", (approval_id,))


def operator_return_to_sender(ctx: AppContext, deposit_id: str, actor: str) -> dict[str, Any]:
    """Human decision on an escalated deposit: propose returning it to the remitter (still needs approval)."""
    with ctx.conn() as conn, db.transaction(conn):
        d = db.row(conn, "SELECT * FROM deposits WHERE id = ?", (deposit_id,))
        if d is None or d["status"] != ESCALATED:
            raise PayoutError("only escalated deposits can be returned to sender")
        a = create_refund_approval(conn, ctx, deposit_id, amount_minor=d["amount_minor"],
                                   evidence_id=None, reason="operator: return unidentified funds to sender", actor=actor)
        # Operator-initiated refunds always need an explicit approval, never the auto limit.
        if a["status"] == "approved" and a["decided_by"] == "policy:auto_limit":
            conn.execute("UPDATE approvals SET status='pending', decided_by=NULL, decided_at=NULL WHERE id = ?", (a["id"],))
        return db.row(conn, "SELECT * FROM approvals WHERE id = ?", (a["id"],))


def _recheck(conn: sqlite3.Connection, a: dict[str, Any], now: str) -> dict[str, Any]:
    stored = json.loads(a["scope"])
    try:
        fresh = current_scope(conn, a["deposit_id"], stored["amount_minor"], stored["evidence_id"])
    except PayoutError as exc:
        fresh = {"error": str(exc)}
    problems = []
    if crypto.scope_hash(fresh) != a["scope_hash"]:
        changed = sorted(k for k in set(stored) | set(fresh) if stored.get(k) != fresh.get(k))
        problems.append("scope changed: " + ", ".join(changed))
    elif stored["amount_minor"] > deposit_buckets(conn, a["deposit_id"])["unapplied"]:
        problems.append("deposit no longer has enough unapplied cash")
    if problems:
        conn.execute("UPDATE approvals SET status='invalidated', invalidated_reason=? WHERE id = ?", ("; ".join(problems), a["id"]))
        audit.record(conn, now, "system", "approval.invalidated", "approval", a["id"], {"reason": problems})
    return {"ok": not problems, "problems": problems, "scope": stored}


def decide(ctx: AppContext, approval_id: str, *, approve: bool, actor: str, seen_scope_hash: str) -> dict[str, Any]:
    with ctx.conn() as conn:
        with db.transaction(conn):
            now = iso(ctx.clock.now())
            a = db.row(conn, "SELECT * FROM approvals WHERE id = ?", (approval_id,))
            if a is None:
                raise PayoutError("unknown approval")
            if a["status"] != "pending":
                raise PayoutError(f"approval is {a['status']}, not pending")
            if seen_scope_hash != a["scope_hash"]:
                raise StaleApproval("the approval you saw is not the one on record; reload and review again")
            if approve and same_person(a.get("created_by"), actor):
                raise SelfApproval("you proposed this refund; a different team member must approve it")
            check = _recheck(conn, a, now)
            if check["ok"]:
                conn.execute(
                    "UPDATE approvals SET status=?, decided_by=?, decided_at=? WHERE id = ?",
                    ("approved" if approve else "rejected", actor, now, approval_id),
                )
                audit.record(conn, now, actor, "approval.approved" if approve else "approval.rejected", "approval", approval_id,
                             {"scope_hash": a["scope_hash"], "deposit_id": a["deposit_id"]})
                if not approve:
                    conn.execute("UPDATE deposits SET status = ?, escalation_reason = ? WHERE id = ? AND status = ?",
                                 (ESCALATED, "refund approval rejected by operator", a["deposit_id"], REFUND_APPROVAL))
        if not check["ok"]:
            raise StaleApproval("; ".join(check["problems"]))
        return db.row(conn, "SELECT * FROM approvals WHERE id = ?", (approval_id,))


# --------------------------------------------------------------------------- execution
def request_id_for(approval_id: str) -> str:
    return str(uuid.uuid5(REQUEST_NS, approval_id))


def _event(conn, op_id, frm, to, detail, now):
    conn.execute("INSERT INTO operation_events(operation_id, from_status, to_status, detail, at) VALUES (?,?,?,?,?)",
                 (op_id, frm, to, detail, now))


@through_sender("send_refund")
def execute_refund(ctx: AppContext, approval_id: str, actor: str, *, automatic: bool = False) -> dict[str, Any]:
    """Send an approved refund. One the policy approved, now over a lowered limit, goes back to a second person instead."""
    result = _send_refund(ctx, approval_id, actor)
    if result.get("expired_after_hours") and not automatic:
        raise StaleApproval(f"this approval expired: it was not sent within {result['expired_after_hours']} hours, so it is back with the approvers to approve again")
    if result.get("returned_to_person") and not automatic:
        raise StaleApproval("this refund is now over the auto-approval limit, so it needs a second person to approve it")
    return result


def send_as_practice_teammate(ctx: AppContext, approval_id: str, pressed_by: str) -> dict[str, Any]:
    """Practice companies only: the practice teammate sends a refund a member approved. The audit log names it, never a
    real member, and the usual sender check still applies to it."""
    if not ctx.org or ctx.org.get("kind") != "sample":
        raise PracticeOnly("the practice teammate exists only in practice companies; a real company needs a second real member to send this")
    with ctx.conn() as conn:
        a = db.row(conn, "SELECT decided_by FROM approvals WHERE id = ?", (approval_id,))
    if a and same_person(a["decided_by"], PRACTICE_TEAMMATE):
        raise SelfApproval("the practice teammate cannot send a refund it approved")
    result = execute_refund(ctx, approval_id, PRACTICE_TEAMMATE)
    if not result.get("replayed"):
        with ctx.conn() as conn, db.transaction(conn):
            audit.record(conn, iso(ctx.clock.now()), PRACTICE_TEAMMATE, "practice_teammate.sent", "approval", approval_id,
                         {"operation_id": result["operation"]["id"], "button_pressed_by": pressed_by})
    return result


def _send_refund(ctx: AppContext, approval_id: str, actor: str) -> dict[str, Any]:
    with ctx.conn() as conn:
        with db.transaction(conn):
            now = iso(ctx.clock.now())
            a = db.row(conn, "SELECT * FROM approvals WHERE id = ?", (approval_id,))
            if a is None:
                raise PayoutError("unknown approval")
            if a["status"] == "executed":
                op = db.row(conn, "SELECT * FROM operations WHERE approval_id = ?", (approval_id,))
                return {"operation": op, "replayed": True}
            if a["status"] != "approved":
                raise PayoutError(f"approval is {a['status']}; it must be approved before execution")
            if ctx.paused(conn):
                raise Paused("money-out is paused; the approval is kept and can execute after resume")
            hours = approval_expired(ctx, conn, a["decided_at"])
            if hours is not None:  # nothing is deleted: the approval goes back to the approvers, and the audit log says why
                conn.execute("UPDATE approvals SET status='pending', decided_by=NULL, decided_at=NULL WHERE id = ?", (approval_id,))
                audit.record(conn, now, "system", "approval.expired", "approval", approval_id,
                             {"approved_by": a["decided_by"], "approved_at": a["decided_at"], "ttl_hours": hours})
                return {"operation": None, "expired_after_hours": hours}
            if a["decided_by"] == "policy:auto_limit":
                # The limit may have been lowered since the policy approved this, for example while money-out was paused.
                stored = json.loads(a["scope"])
                limit = ctx.policy(conn)["refund_auto_limit_minor"][stored["currency"]]
                if stored["amount_minor"] > limit:
                    conn.execute("UPDATE approvals SET status='pending', decided_by=NULL, decided_at=NULL WHERE id = ?", (approval_id,))
                    audit.record(conn, now, "system", "approval.returned_to_person", "approval", approval_id,
                                 {"reason": "the amount is now over the refund auto-approval limit", "amount_minor": stored["amount_minor"],
                                  "limit_minor": limit, "currency": stored["currency"]})
                    return {"operation": None, "returned_to_person": True}
            if sender_must_differ(a) and same_person(actor, a["decided_by"]):
                raise SelfApproval("you approved this refund and nobody on the team proposed it, so a different team member must send it")
            check = _recheck(conn, a, now)
            if not check["ok"]:
                stale_reason = "; ".join(check["problems"])
            else:
                stale_reason = None
                scope = check["scope"]
                op_id = "OP-" + uuid.uuid4().hex[:8].upper()
                try:
                    conn.execute(
                        "INSERT INTO operations(id, kind, deposit_id, request_id, currency, amount_minor, destination, status,"
                        " approval_id, detail, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (op_id, "refund", scope["deposit_id"], request_id_for(approval_id), scope["currency"],
                         scope["amount_minor"], scope["destination"], "pending", approval_id,
                         json.dumps({"scope_hash": a["scope_hash"]}), now, now),
                    )
                except sqlite3.IntegrityError as exc:
                    raise PayoutError("a live refund already exists for this deposit (duplicate lock)") from exc
                audit.post(conn, now, f"Reserve refund {op_id}", "operation", op_id,
                           audit.move("unapplied_cash", "refund_payable", scope["currency"], scope["amount_minor"]))
                _event(conn, op_id, None, "pending", "created from approval " + approval_id, now)
                conn.execute("UPDATE approvals SET status='executed' WHERE id = ?", (approval_id,))
                conn.execute("UPDATE deposits SET status = ? WHERE id = ?", (REFUND_IN_FLIGHT, scope["deposit_id"]))
                audit.record(conn, now, actor, "refund.created", "operation", op_id,
                             {"approval_id": approval_id, "request_id": request_id_for(approval_id), "scope_hash": a["scope_hash"]},
                             operation_id=op_id)
        if stale_reason:
            raise StaleApproval(stale_reason)
    op = submit_operation(ctx, op_id, actor)
    return {"operation": op, "replayed": False}


def submit_operation(ctx: AppContext, op_id: str, actor: str = "system") -> dict[str, Any]:
    """Send (or reconcile) a refund with the provider. Safe to call repeatedly and concurrently."""
    with ctx.conn() as conn:
        with db.transaction(conn):
            now_dt = ctx.clock.now()
            now = iso(now_dt)
            op = db.row(conn, "SELECT * FROM operations WHERE id = ? AND kind = 'refund'", (op_id,))
            if op is None:
                raise PayoutError("unknown refund operation")
            detail = json.loads(op["detail"])
            if op["status"] not in ("pending", "processing"):
                return op
            if op["status"] == "processing" and not op["needs_reconciliation"]:
                return op
            lease = detail.get("lease_until")
            if lease and parse_iso(lease) > now_dt:
                return op  # another caller is talking to the provider right now
            if ctx.paused(conn):
                raise Paused("money-out is paused; pending refunds are held")
            attempt = op["attempts"] + 1
            lookup_first = op["attempts"] > 0  # we have contacted the provider before: never blind-resend
            detail["lease_until"] = iso(now_dt + LEASE)
            conn.execute(
                "UPDATE operations SET status='processing', needs_reconciliation=1, attempts=?, detail=?, updated_at=? WHERE id = ?",
                (attempt, json.dumps(detail), now, op_id),
            )
            _event(conn, op_id, op["status"], "processing", f"attempt {attempt}" + (" (lookup by request_id first)" if lookup_first else ""), now)

    provider = ctx.provider
    result: TransferResult | None = None
    error: str | None = None
    ambiguous = False
    try:
        if lookup_first:
            result = provider.find_transfer(op["request_id"])
        if result is None:
            result = provider.create_transfer(
                request_id=op["request_id"], amount_minor=op["amount_minor"], currency=op["currency"],
                destination=op["destination"], reference=f"Ledgerline refund {op['deposit_id']}",
            )
    except ProviderAmbiguous as exc:
        ambiguous, error = True, str(exc)
    except ProviderError as exc:
        error = str(exc)
        if lookup_first:
            # A rejection on a retry may mean "duplicate request_id": look again before deciding.
            try:
                result = provider.find_transfer(op["request_id"])
            except (ProviderError, ProviderAmbiguous):
                ambiguous = True
            if result is None and not ambiguous:
                ambiguous = True  # still unknown: do not declare failure on a retry path

    with ctx.conn() as conn:
        with db.transaction(conn):
            now = iso(ctx.clock.now())
            op = db.row(conn, "SELECT * FROM operations WHERE id = ?", (op_id,))
            detail = json.loads(op["detail"])
            detail.pop("lease_until", None)
            if result is not None:
                conn.execute(
                    "UPDATE operations SET provider_id=?, needs_reconciliation=0, last_error=NULL, detail=?, updated_at=? WHERE id = ?",
                    (result.provider_id, json.dumps(detail), now, op_id),
                )
                op = db.row(conn, "SELECT * FROM operations WHERE id = ?", (op_id,))
                if result.status not in ("failed", "cancelled"):
                    # Funds left the wallet only if the provider accepted the transfer.
                    _post_cash_out(conn, op, now)
                    op = db.row(conn, "SELECT * FROM operations WHERE id = ?", (op_id,))
                _apply_status(conn, op, result.status, now, f"provider {result.raw_status}")
            elif ambiguous:
                conn.execute(
                    "UPDATE operations SET needs_reconciliation=1, last_error=?, detail=?, updated_at=? WHERE id = ?",
                    (error, json.dumps(detail), now, op_id),
                )
                _event(conn, op_id, "processing", "processing", f"ambiguous: {error}; must reconcile by request_id", now)
                audit.record(conn, now, "system", "refund.ambiguous", "operation", op_id, {"error": error}, operation_id=op_id)
            else:
                conn.execute("UPDATE operations SET last_error=?, needs_reconciliation=0, detail=?, updated_at=? WHERE id = ?",
                             (error, json.dumps(detail), now, op_id))
                op = db.row(conn, "SELECT * FROM operations WHERE id = ?", (op_id,))
                _apply_status(conn, op, "failed", now, f"rejected: {error}")
            return db.row(conn, "SELECT * FROM operations WHERE id = ?", (op_id,))


def _post_cash_out(conn, op, now):
    detail = json.loads(op["detail"])
    if detail.get("cash_out_posted"):
        return
    audit.post(conn, now, f"Refund {op['id']} funds leave wallet", "operation", op["id"],
               audit.move("cash_in_transit", f"cash:{op['currency']}", op["currency"], op["amount_minor"]))
    detail["cash_out_posted"] = True
    conn.execute("UPDATE operations SET detail = ? WHERE id = ?", (json.dumps(detail), op["id"]))


_TRANSITIONS = {
    "pending": {"processing", "cancelled", "failed"},
    "processing": {"sent", "paid", "failed", "cancelled"},
    "sent": {"paid", "failed"},
}


def _apply_status(conn, op, new_status, now, why):
    old = op["status"]
    if new_status == old:
        return
    if new_status not in _TRANSITIONS.get(old, set()):
        raise PayoutError(f"illegal refund transition {old} -> {new_status}")
    ccy, amt = op["currency"], op["amount_minor"]
    cash_out = json.loads(op["detail"]).get("cash_out_posted")
    conn.execute("UPDATE operations SET status = ?, updated_at = ? WHERE id = ?", (new_status, now, op["id"]))
    _event(conn, op["id"], old, new_status, why, now)
    if new_status == "paid":
        audit.post(conn, now, f"Refund {op['id']} confirmed paid", "operation", op["id"],
                   audit.move("refund_payable", "cash_in_transit", ccy, amt))
        conn.execute("UPDATE deposits SET status = ? WHERE id = ?", (REFUNDED, op["deposit_id"]))
    elif new_status in ("failed", "cancelled"):
        if cash_out:
            audit.post(conn, now, f"Refund {op['id']} returned", "operation", op["id"],
                       audit.move(f"cash:{ccy}", "cash_in_transit", ccy, amt))
        audit.post(conn, now, f"Refund {op['id']} reservation released", "operation", op["id"],
                   audit.move("refund_payable", "unapplied_cash", ccy, amt))
        conn.execute("UPDATE deposits SET status = ?, escalation_reason = ? WHERE id = ?",
                     (ESCALATED, f"refund {new_status}: {why}", op["deposit_id"]))
    audit.record(conn, now, "provider", f"refund.{new_status}", "operation", op["id"], {"from": old, "why": why}, operation_id=op["id"])


def sync_operation(ctx: AppContext, op_id: str) -> dict[str, Any]:
    with ctx.conn() as conn:
        op = db.row(conn, "SELECT * FROM operations WHERE id = ?", (op_id,))
    if op is None:
        raise PayoutError("unknown operation")
    if op["needs_reconciliation"] or op["status"] == "pending":
        return submit_operation(ctx, op_id)
    if op["status"] not in ("processing", "sent") or not op["provider_id"]:
        return op
    result = ctx.provider.get_transfer(op["provider_id"])
    with ctx.conn() as conn, db.transaction(conn):
        op = db.row(conn, "SELECT * FROM operations WHERE id = ?", (op_id,))
        _apply_status(conn, op, result.status, iso(ctx.clock.now()), f"provider {result.raw_status}")
        return db.row(conn, "SELECT * FROM operations WHERE id = ?", (op_id,))


def simulate_bank_status(ctx: AppContext, op_id: str, next_status: str) -> dict[str, Any]:
    """Demo/sandbox control: ask the (simulated) bank to move the transfer, then sync from it."""
    with ctx.conn() as conn:
        op = db.row(conn, "SELECT * FROM operations WHERE id = ?", (op_id,))
    if op is None or not op["provider_id"]:
        raise PayoutError("operation has no provider transfer yet")
    allowed = {'processing': {'SENT', 'FAILED'}, 'sent': {'PAID', 'FAILED'}}
    if op['kind'] != 'refund' or next_status not in allowed.get(op['status'], set()):
        raise PayoutError('simulation must move a processing refund to SENT, then a sent refund to PAID or FAILED')
    ctx.provider.simulate_transfer_status(op["provider_id"], next_status)
    return sync_operation(ctx, op_id)


def cancel_pending(ctx: AppContext, op_id: str, actor: str) -> dict[str, Any]:
    with ctx.conn() as conn, db.transaction(conn):
        op = db.row(conn, "SELECT * FROM operations WHERE id = ?", (op_id,))
        if op is None or op["status"] != "pending":
            raise PayoutError("only refunds not yet submitted to the provider can be cancelled here")
        now = iso(ctx.clock.now())
        _apply_status(conn, op, "cancelled", now, f"cancelled by {actor}")
        return db.row(conn, "SELECT * FROM operations WHERE id = ?", (op_id,))


def auto_execute_ready(ctx: AppContext, actor: str = "system") -> list[str]:
    """Send only what the policy limit approved. A refund a person approved waits for a person to send it."""
    with ctx.conn() as conn:
        ids = [r["id"] for r in db.rows(conn, "SELECT id FROM approvals WHERE status = 'approved' AND operation_type='refund' AND decided_by = 'policy:auto_limit'")]
    done = []
    for aid in ids:
        try:
            r = execute_refund(ctx, aid, actor, automatic=True)
            if not r.get("returned_to_person") and not r.get("expired_after_hours"):
                done.append(aid)
        except (Paused, StaleApproval, PayoutError, ReconcileError):
            continue
    return done
