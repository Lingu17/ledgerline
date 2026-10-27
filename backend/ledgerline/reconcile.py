"""Deposit ingestion, initial plans, applying safe actions, and evidence-driven revision."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any

from . import audit, crypto, db
from .clock import iso
from .context import AppContext
from .evidence import verify
from .matching import InvoiceView, initial_plan
from .money import fmt, validate_currency, validate_minor

# Deposit statuses
RECEIVED = "received"
MATCHED = "matched"
PARTIAL = "partially_applied"
AWAITING_EVIDENCE = "awaiting_evidence"
ESCALATED = "escalated"
CREDITED = "credited"
REFUND_APPROVAL = "refund_awaiting_approval"
REFUND_IN_FLIGHT = "refund_in_flight"
REFUNDED = "refunded"


class ReconcileError(ValueError):
    pass


# --------------------------------------------------------------------------- queries
def customers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    out = db.rows(conn, "SELECT * FROM customers ORDER BY id")
    for c in out:
        c["payer_names"] = json.loads(c["payer_names"])
    return out


def key_registry(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    return {
        c["id"]: {"key_id": c["agent_key_id"], "public_key": c["agent_public_key"]}
        for c in db.rows(conn, "SELECT id, agent_key_id, agent_public_key FROM customers")
        if c["agent_public_key"]
    }


def invoice_views(conn: sqlite3.Connection) -> dict[str, InvoiceView]:
    rs = db.rows(
        conn,
        """SELECT i.*,
             COALESCE((SELECT SUM(amount_minor) FROM allocations a WHERE a.invoice_id = i.id), 0) AS allocated,
             COALESCE((SELECT SUM(amount_minor) FROM writeoffs w WHERE w.invoice_id = i.id), 0) AS written_off,
             COALESCE((SELECT SUM(delta_minor) FROM invoice_adjustments x WHERE x.invoice_id = i.id), 0) AS adjusted
           FROM invoices i""",
    )
    return {
        r["id"]: InvoiceView(
            id=r["id"],
            customer_id=r["customer_id"],
            currency=r["currency"],
            amount_minor=r["amount_minor"] + r["adjusted"],
            remaining_minor=r["amount_minor"] + r["adjusted"] - r["prior_paid_minor"] - r["allocated"] - r["written_off"],
            # A voided invoice (adjusted to zero) can never be matched or paid again.
            status="void" if r["voided_at"] else r["status"],
            due_at=r["due_at"],
        )
        for r in rs
    }


def deposit_buckets(conn: sqlite3.Connection, deposit_id: str) -> dict[str, int]:
    d = db.row(conn, "SELECT amount_minor FROM deposits WHERE id = ?", (deposit_id,))
    if not d:
        raise ReconcileError(f"unknown deposit {deposit_id}")
    q = lambda sql: int(conn.execute(sql, (deposit_id,)).fetchone()[0])  # noqa: E731
    allocated = q("SELECT COALESCE(SUM(amount_minor),0) FROM allocations WHERE deposit_id = ?")
    credited = q("SELECT COALESCE(SUM(amount_minor),0) FROM credits WHERE deposit_id = ?")
    refund_paid = q("SELECT COALESCE(SUM(amount_minor),0) FROM operations WHERE kind='refund' AND deposit_id = ? AND status = 'paid'")
    refund_pending = q(
        "SELECT COALESCE(SUM(amount_minor),0) FROM operations WHERE kind='refund' AND deposit_id = ? "
        "AND status NOT IN ('paid','failed','cancelled')"
    )
    unapplied = d["amount_minor"] - allocated - credited - refund_paid - refund_pending
    return {
        "amount": d["amount_minor"],
        "allocated": allocated,
        "credited": credited,
        "refund_paid": refund_paid,
        "refund_pending": refund_pending,
        "unapplied": unapplied,
    }


def latest_plan(conn: sqlite3.Connection, deposit_id: str) -> dict[str, Any] | None:
    p = db.row(conn, "SELECT * FROM plans WHERE deposit_id = ? ORDER BY version DESC LIMIT 1", (deposit_id,))
    if p:
        p["actions"] = json.loads(p["actions"])
    return p


def _bump_version(conn: sqlite3.Connection, deposit_id: str, now: str, why: str) -> int:
    """Any mutation of a deposit invalidates approvals bound to the previous version."""
    conn.execute("UPDATE deposits SET version = version + 1 WHERE id = ?", (deposit_id,))
    stale = db.rows(conn, "SELECT id FROM approvals WHERE deposit_id = ? AND status IN ('pending','approved')", (deposit_id,))
    for a in stale:
        conn.execute(
            "UPDATE approvals SET status='invalidated', invalidated_reason=? WHERE id = ?", (f"deposit changed: {why}", a["id"])
        )
        audit.record(conn, now, "system", "approval.invalidated", "approval", a["id"], {"reason": why, "deposit_id": deposit_id})
    return int(conn.execute("SELECT version FROM deposits WHERE id = ?", (deposit_id,)).fetchone()[0])


# --------------------------------------------------------------------------- ingest
def deposit_id_for(provider_ref: str) -> str:
    if provider_ref.startswith("SIM-DEP-"):
        return "DEP-" + provider_ref.removeprefix("SIM-DEP-")
    return "DEP-" + hashlib.sha256(provider_ref.encode()).hexdigest()[:10].upper()


def ingest_deposit(conn: sqlite3.Connection, ctx: AppContext, fields: dict[str, Any], *, source: str,
                   global_account_id: str | None = None) -> tuple[str, bool]:
    """Insert a settled deposit and run its deterministic initial plan. Idempotent on provider_ref.

    Must be called inside a transaction. Returns (deposit_id, created).
    """
    ccy = validate_currency(fields["currency"])
    amount = validate_minor(fields["amount_minor"])
    existing = db.row(conn, "SELECT id FROM deposits WHERE provider_ref = ?", (fields["provider_ref"],))
    if existing:
        return existing["id"], False
    dep_id = deposit_id_for(fields["provider_ref"])
    now = iso(ctx.clock.now())
    conn.execute(
        "INSERT INTO deposits(id, provider_ref, source, global_account_id, currency, amount_minor, payer_name, reference,"
        " received_at, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (dep_id, fields["provider_ref"], source, global_account_id, ccy, amount, fields["payer_name"],
         fields.get("reference") or "", fields["received_at"], RECEIVED),
    )
    audit.post(conn, now, f"Deposit {dep_id} received", "deposit", dep_id, audit.move(f"cash:{ccy}", "unapplied_cash", ccy, amount))
    audit.record(conn, now, "webhook" if "webhook" in source else source, "deposit.received", "deposit", dep_id,
                 {"currency": ccy, "amount_minor": amount, "payer": fields["payer_name"], "reference": fields.get("reference")})
    run_initial_plan(conn, ctx, dep_id)
    return dep_id, True


def run_initial_plan(conn: sqlite3.Connection, ctx: AppContext, deposit_id: str) -> dict[str, Any]:
    deposit = db.row(conn, "SELECT * FROM deposits WHERE id = ?", (deposit_id,))
    policy = ctx.policy(conn)
    plan = initial_plan(deposit, customers(conn), invoice_views(conn), policy["fee_tolerance_minor"][deposit["currency"]],
                        policy["fee_tolerance_bps"])
    return _store_and_apply(conn, ctx, deposit, plan.to_dict(), kind="initial", evidence_id=None)


def _store_and_apply(conn: sqlite3.Connection, ctx: AppContext, deposit: dict[str, Any], plan: dict[str, Any], *,
                     kind: str, evidence_id: str | None) -> dict[str, Any]:
    now = iso(ctx.clock.now())
    dep_id = deposit["id"]
    version = int(conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM plans WHERE deposit_id = ?", (dep_id,)).fetchone()[0])
    conn.execute(
        "INSERT INTO plans(deposit_id, version, kind, category, summary, actions, evidence_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (dep_id, version, kind, plan["category"], plan["summary"], json.dumps(plan["actions"]), evidence_id, now),
    )
    audit.record(conn, now, "rules" if kind == "initial" else "system", f"plan.{kind}", "deposit", dep_id,
                 {"version": version, "category": plan["category"], "actions": plan["actions"], "notes": plan.get("notes", [])})
    # Bump first so anything created below (e.g. an approval) binds to the new version.
    _bump_version(conn, dep_id, now, f"plan v{version}")
    deposit = db.row(conn, "SELECT * FROM deposits WHERE id = ?", (dep_id,))

    status = RECEIVED
    for action in plan["actions"]:
        t = action["type"]
        if t == "allocate":
            _allocate(conn, now, deposit, action["invoice_id"], action["amount_minor"])
        elif t == "write_off_fee":
            _write_off(conn, now, deposit, action["invoice_id"], action["amount_minor"])
        elif t == "payment_link":
            _payment_link_draft(conn, ctx, now, deposit, action["invoice_id"], action["amount_minor"])
        elif t == "credit":
            _credit(conn, now, deposit, action["customer_id"], action["amount_minor"], action.get("earmark_invoice_id"), evidence_id)
        elif t == "request_refund_approval":
            from .payouts import create_refund_approval

            create_refund_approval(conn, ctx, dep_id, amount_minor=action["amount_minor"], evidence_id=evidence_id,
                                   reason=action.get("reason", "verified duplicate payment"))

    cat = plan["category"]
    if cat in ("clean_match", "clean_with_fee", "verified_invoice_payment"):
        status = MATCHED
    elif cat == "partial_payment":
        status = PARTIAL
    elif cat == "verified_advance_credit":
        status = CREDITED
    elif cat == "verified_duplicate":
        status = REFUND_APPROVAL
    elif plan.get("needs_evidence"):
        status = AWAITING_EVIDENCE
    elif plan.get("needs_human"):
        status = ESCALATED
    if cat == "operator_resolution":
        b = deposit_buckets(conn, dep_id)
        if b["unapplied"] > 0:
            status, plan = ESCALATED, {**plan, "actions": plan["actions"] + [
                {"type": "escalate", "reason": f"partly resolved by operator; {fmt(b['unapplied'], deposit['currency'])} still unapplied"}]}
        else:
            status = MATCHED if b["allocated"] else CREDITED
    reason = None
    if status == ESCALATED:
        reason = next((a.get("reason") for a in plan["actions"] if a["type"] == "escalate"), plan["summary"])
    conn.execute(
        "UPDATE deposits SET status = ?, category = ?, customer_id = COALESCE(?, customer_id), escalation_reason = ? WHERE id = ?",
        (status, cat, plan.get("customer_id"), reason, dep_id),
    )
    return {"version": version, **plan, "status": status}


def _allocate(conn, now, deposit, invoice_id, amount):
    validate_minor(amount)
    inv = invoice_views(conn).get(invoice_id)
    if inv is None or inv.currency != deposit["currency"]:
        raise ReconcileError(f"cannot allocate {deposit['currency']} to {invoice_id}")
    if amount > inv.remaining_minor:
        raise ReconcileError(f"allocating {fmt(amount, inv.currency)} would overpay {invoice_id} "
                             f"({fmt(inv.remaining_minor, inv.currency)} remaining)")
    if amount > deposit_buckets(conn, deposit["id"])["unapplied"]:
        raise ReconcileError(f"allocation exceeds unapplied cash on {deposit['id']}")
    # One row per (deposit, invoice). A later allocation of the same deposit to the same invoice (an operator
    # applying more of a part-resolved payment) tops that row up; the two checks above still bound it.
    topped_up = conn.execute(
        "UPDATE allocations SET amount_minor = amount_minor + ? WHERE deposit_id = ? AND invoice_id = ?",
        (amount, deposit["id"], invoice_id),
    ).rowcount
    if not topped_up:
        conn.execute(
            "INSERT INTO allocations(deposit_id, invoice_id, currency, amount_minor, created_at) VALUES (?,?,?,?,?)",
            (deposit["id"], invoice_id, deposit["currency"], amount, now),
        )
    audit.post(conn, now, f"Apply {deposit['id']} to {invoice_id}", "allocation", f"{deposit['id']}:{invoice_id}",
               audit.move("unapplied_cash", "accounts_receivable", deposit["currency"], amount))
    audit.record(conn, now, "rules", "allocation.created", "invoice", invoice_id, {"deposit_id": deposit["id"], "amount_minor": amount})


def _write_off(conn, now, deposit, invoice_id, amount):
    inv = invoice_views(conn)[invoice_id]
    if amount > inv.remaining_minor:
        raise ReconcileError("write-off exceeds remaining balance")
    conn.execute(
        "INSERT INTO writeoffs(invoice_id, deposit_id, currency, amount_minor, reason, created_at) VALUES (?,?,?,?,?,?)",
        (invoice_id, deposit["id"], deposit["currency"], amount, "bank fee within tolerance", now),
    )
    audit.post(conn, now, f"Bank fee write-off on {invoice_id}", "writeoff", invoice_id,
               audit.move("bank_fee_expense", "accounts_receivable", deposit["currency"], amount))
    audit.record(conn, now, "rules", "writeoff.created", "invoice", invoice_id, {"deposit_id": deposit["id"], "amount_minor": amount})


def _payment_link_draft(conn, ctx, now, deposit, invoice_id, amount):
    link_id = "PL-" + uuid.uuid4().hex[:8].upper()
    conn.execute(
        "INSERT INTO payment_links VALUES (?,?,?,?,?,?,?,?,?,?)",
        (link_id, invoice_id, deposit["id"], deposit["currency"], amount, "local_draft", None, None,
         "Balance-due request drafted locally; not sent. Publish via provider to create a hosted link.", now),
    )
    audit.record(conn, now, "rules", "payment_link.drafted", "invoice", invoice_id,
                 {"deposit_id": deposit["id"], "amount_minor": amount, "link_id": link_id})


def _credit(conn, now, deposit, customer_id, amount, earmark, evidence_id):
    if amount > deposit_buckets(conn, deposit["id"])["unapplied"]:
        raise ReconcileError("credit exceeds unapplied cash")
    conn.execute(
        "INSERT INTO credits(deposit_id, customer_id, currency, amount_minor, earmark_invoice_id, evidence_id, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (deposit["id"], customer_id, deposit["currency"], amount, earmark, evidence_id, now),
    )
    audit.post(conn, now, f"Customer credit from {deposit['id']}", "credit", deposit["id"],
               audit.move("unapplied_cash", "customer_credit", deposit["currency"], amount))
    audit.record(conn, now, "system", "credit.created", "customer", customer_id,
                 {"deposit_id": deposit["id"], "amount_minor": amount, "earmark_invoice_id": earmark, "evidence_id": evidence_id})


# --------------------------------------------------------------------------- evidence
def pending_agent_questions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    out = []
    for d in db.rows(conn, "SELECT * FROM deposits WHERE status = ? ORDER BY received_at", (AWAITING_EVIDENCE,)):
        plan = latest_plan(conn, d["id"])
        ask = next((a for a in plan["actions"] if a["type"] == "ask_payer_agent"), None) if plan else None
        if ask:
            out.append({
                "customer_id": ask["customer_id"],
                "deposit_id": d["id"],
                "currency": d["currency"],
                "amount_minor": d["amount_minor"],
                "unapplied_minor": deposit_buckets(conn, d["id"])["unapplied"],
                "received_at": d["received_at"],
                "reference": d["reference"],
            })
    return out


def record_agent_answer(conn: sqlite3.Connection, ctx: AppContext, deposit_id: str, asked_customer_id: str,
                        answer: dict[str, Any], transport: str) -> dict[str, Any]:
    """Verify a payer agent's answer and revise the plan. Must be called inside a transaction."""
    deposit = db.row(conn, "SELECT * FROM deposits WHERE id = ?", (deposit_id,))
    if deposit is None:
        raise ReconcileError(f"unknown deposit {deposit_id}")
    if deposit["status"] != AWAITING_EVIDENCE:
        raise ReconcileError(f"{deposit_id} is not awaiting evidence (status {deposit['status']})")
    plan_now = latest_plan(conn, deposit_id)
    expected_agent = next((a["customer_id"] for a in plan_now["actions"] if a["type"] == "ask_payer_agent"), None) if plan_now else None
    if asked_customer_id != expected_agent or asked_customer_id != deposit["customer_id"]:
        raise ReconcileError(f"{asked_customer_id} is not the payer we asked about {deposit_id}")
    now_dt = ctx.clock.now()
    now = iso(now_dt)
    policy = ctx.policy(conn)
    envelope = answer.get("envelope") if answer.get("status") == "answered" else None
    invoices = invoice_views(conn)
    applicable = deposit_buckets(conn, deposit_id)["unapplied"]

    if envelope is None:
        result = {
            "checks": [],
            "verdict": "rejected",
            "reason": f"payer agent returned '{answer.get('status')}': {answer.get('detail', 'no explanation')}",
            "claim": None,
        }
    else:
        result = verify(
            envelope,
            deposit=deposit,
            asked_customer_id=asked_customer_id,
            registry=key_registry(conn),
            invoices=invoices,
            now=now_dt,
            max_ttl_seconds=policy["evidence_max_ttl_seconds"],
            skew_seconds=policy["evidence_clock_skew_seconds"],
            applicable_minor=applicable,
        ).to_dict()

    raw = json.dumps(envelope if envelope is not None else answer, sort_keys=True)
    claim_hash = crypto.sha256_hex(raw.encode())
    if result["verdict"] == "verified" and db.row(
        conn, "SELECT id FROM evidence WHERE claim_hash = ? AND verdict = 'verified'", (claim_hash,)
    ):
        result["verdict"] = "rejected"
        result["reason"] = "replayed answer: this exact signed claim was already used"
    ev_version = int(conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM evidence WHERE deposit_id = ?", (deposit_id,)).fetchone()[0])
    ev_id = f"EV-{deposit_id}-{ev_version}"
    conn.execute(
        "INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (ev_id, deposit_id, asked_customer_id, ev_version, "mcp_signed", transport, raw, claim_hash,
         json.dumps(result["checks"]), result["verdict"], result["reason"], now),
    )
    audit.record(conn, now, f"payer_agent:{asked_customer_id}", "evidence.received", "deposit", deposit_id,
                 {"evidence_id": ev_id, "transport": transport, "verdict": result["verdict"], "reason": result["reason"],
                  "checks": [{c["name"]: c["passed"]} for c in result["checks"]]})

    claim = result["claim"]
    # Only the still-unapplied part is decided by this evidence (overpayments were partly allocated already).
    amount = applicable
    if result["verdict"] != "verified":
        plan = {
            "category": "evidence_rejected",
            "summary": "Payer agent's answer failed verification and was ignored. A person decides.",
            "customer_id": deposit["customer_id"],
            "actions": [{"type": "escalate", "reason": result["reason"]}, {"type": "hold_unapplied", "amount_minor": amount}],
            "needs_human": True,
        }
    elif claim["reason"] == "invoice_payment":
        plan = {
            "category": "verified_invoice_payment",
            "summary": f"Verified: payment for {claim['invoice_id']}. {fmt(amount, deposit['currency'])} applied.",
            "customer_id": claim["customer_id"],
            "actions": [{"type": "allocate", "invoice_id": claim["invoice_id"], "amount_minor": amount}],
        }
    elif claim["reason"] == "advance_payment":
        plan = {
            "category": "verified_advance_credit",
            "summary": f"Verified advance for {claim['invoice_id']}. Proposed refund dropped before any money moved; held as customer credit.",
            "customer_id": claim["customer_id"],
            "actions": [{"type": "cancel_proposed_refund"},
                        {"type": "credit", "customer_id": claim["customer_id"], "amount_minor": amount,
                         "earmark_invoice_id": claim["invoice_id"]}],
        }
    else:  # duplicate_payment
        plan = {
            "category": "verified_duplicate",
            "summary": f"Verified duplicate of {claim['invoice_id']}. Refund requires approval bound to amount, destination and this evidence.",
            "customer_id": claim["customer_id"],
            "actions": [{"type": "request_refund_approval", "amount_minor": amount,
                         "reason": f"verified duplicate of {claim['invoice_id']}"}],
        }
    revised = _store_and_apply(conn, ctx, deposit, plan, kind="revised", evidence_id=ev_id)
    return {"evidence_id": ev_id, "verification": result, "plan": revised}
