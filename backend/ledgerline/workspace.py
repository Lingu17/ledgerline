"""Ordinary workspace input: customers, invoices, manually recorded payments and operator resolutions.

Every path goes through the same validation, journals, audit and plan machinery
as webhook-driven deposits. Nothing here can bypass ownership, conservation,
approval, pause or idempotency checks.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from . import audit, crypto, db
from .clock import iso, parse_iso
from .context import AppContext
from .money import MoneyError, fmt, to_minor, validate_currency
from .reconcile import (
    ESCALATED,
    ReconcileError,
    _store_and_apply,
    deposit_buckets,
    ingest_deposit,
    invoice_views,
)


class InputError(ValueError):
    """Validation failure on operator input (HTTP 422)."""


def _text(value: Any, field: str, lo: int, hi: int) -> str:
    if not isinstance(value, str) or not lo <= len(value.strip()) <= hi:
        raise InputError(f"{field} must be {lo}-{hi} characters")
    return value.strip()


def _payer_names(conn, names: Any, exclude_customer: str | None = None) -> list[str]:
    if not isinstance(names, list) or not 1 <= len(names) <= 5:
        raise InputError("payer_names must list 1-5 remitter names as they appear on bank statements")
    out = [_text(n, "payer name", 2, 80).upper() for n in names]
    for c in db.rows(conn, "SELECT id, payer_names FROM customers"):
        if c["id"] == exclude_customer:
            continue
        clash = set(out) & {n.upper() for n in json.loads(c["payer_names"])}
        if clash:
            raise InputError(f"payer name {sorted(clash)[0]} already identifies {c['id']}; payer names must be unambiguous")
    return out


def create_customer(ctx: AppContext, body: dict[str, Any], actor: str) -> dict[str, Any]:
    name = _text(body.get("name"), "name", 2, 80)
    country = body.get("country")
    if not isinstance(country, str) or not re.fullmatch(r"[A-Z]{2}", country):
        raise InputError("country must be a 2-letter ISO code")
    beneficiary = _text(body.get("refund_beneficiary"), "refund_beneficiary", 2, 120)
    pub = body.get("agent_public_key") or None
    key_id = None
    if pub is not None:
        try:
            if len(crypto.b64d(pub)) != 32:
                raise ValueError
        except ValueError as exc:
            raise InputError("agent_public_key must be a base64 raw Ed25519 public key (32 bytes)") from exc
        key_id = crypto.key_id_for(pub)
    with ctx.conn() as conn, db.transaction(conn):
        payers = _payer_names(conn, body.get("payer_names"))
        slug = re.sub(r"[^A-Z0-9]+", "", name.upper())[:12] or "CUSTOMER"
        cid = f"CUST-{slug}"
        if db.row(conn, "SELECT id FROM customers WHERE id = ?", (cid,)):
            cid = f"{cid}-{uuid.uuid4().hex[:4].upper()}"
        conn.execute("INSERT INTO customers(id, name, country, payer_names, agent_key_id, agent_public_key, refund_beneficiary, demo_only) VALUES (?,?,?,?,?,?,?,0)",
                     (cid, name, country, json.dumps(payers), key_id, pub, beneficiary))
        audit.record(conn, iso(ctx.clock.now()), actor, "customer.created", "customer", cid,
                     {"name": name, "payer_names": payers, "agent_key_id": key_id})
        return db.row(conn, "SELECT * FROM customers WHERE id = ?", (cid,))


def create_invoice(ctx: AppContext, body: dict[str, Any], actor: str) -> dict[str, Any]:
    try:
        ccy = validate_currency(body.get("currency"))
        amount = to_minor(body.get("amount"), ccy)
    except MoneyError as exc:
        raise InputError(str(exc)) from exc
    if amount <= 0:
        raise InputError("amount must be greater than zero")
    description = _text(body.get("description"), "description", 1, 200)
    try:
        due = date.fromisoformat(str(body.get("due_date")))
    except ValueError as exc:
        raise InputError("due_date must be YYYY-MM-DD") from exc
    with ctx.conn() as conn, db.transaction(conn):
        cust = db.row(conn, "SELECT id FROM customers WHERE id = ?", (body.get("customer_id"),))
        if cust is None:
            raise InputError("customer_id does not exist")
        last = conn.execute("SELECT MAX(CAST(substr(id, 5) AS INTEGER)) FROM invoices WHERE id LIKE 'INV-%'").fetchone()[0] or 2300
        inv_id = f"INV-{max(int(last) + 1, 2301)}"
        now = ctx.clock.now()
        conn.execute("INSERT INTO invoices(id, customer_id, currency, amount_minor, prior_paid_minor, status, issued_at, due_at, description) VALUES (?,?,?,?,0,'open',?,?,?)",
                     (inv_id, cust["id"], ccy, amount, iso(now),
                      iso(datetime.combine(due, time(23, 59, 59), tzinfo=timezone.utc)), description))
        audit.post(conn, iso(now), f"Invoice {inv_id} issued", "invoice", inv_id, audit.move("accounts_receivable", "revenue", ccy, amount))
        audit.record(conn, iso(now), actor, "invoice.created", "invoice", inv_id,
                     {"customer_id": cust["id"], "currency": ccy, "amount_minor": amount})
        return db.row(conn, "SELECT * FROM invoices WHERE id = ?", (inv_id,))


_REF_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def record_manual_payment(ctx: AppContext, body: dict[str, Any], actor: str) -> dict[str, Any]:
    """Record a received payment typed in or imported by an operator (local workspace only).

    It is labelled manual_import (not bank-verified) and is idempotent on the
    external reference: the same reference with the same details returns the
    existing deposit; with different details it is refused.
    """
    if ctx.local_bank is None:
        raise InputError("manual payment entry is only available in the local workspace; sandbox deposits arrive via webhook")
    ref = body.get("external_ref")
    if not isinstance(ref, str) or not _REF_RE.match(ref):
        raise InputError("external_ref must be 1-64 characters of letters, digits and . _ : -")
    try:
        ccy = validate_currency(body.get("currency"))
        amount = to_minor(body.get("amount"), ccy)
    except MoneyError as exc:
        raise InputError(str(exc)) from exc
    if amount <= 0:
        raise InputError("amount must be greater than zero")
    payer = _text(body.get("payer_name"), "payer_name", 2, 80).upper()
    reference = body.get("reference") or ""
    if not isinstance(reference, str) or len(reference) > 140:
        raise InputError("reference must be at most 140 characters")
    received = body.get("received_at")
    now = ctx.clock.now()
    if received:
        try:
            day = None if "T" in str(received) else date.fromisoformat(str(received))
            received_dt = parse_iso(received) if day is None else datetime.combine(day, time(12), tzinfo=timezone.utc)
        except ValueError as exc:
            raise InputError("received_at must be an ISO date or timestamp") from exc
        if day is not None:
            # A statement date is a calendar day in the operator's time zone, up to 14 h ahead
            # of UTC. Accept today there, and never record a time later than now.
            if day > (now + timedelta(hours=14)).date():
                raise InputError("received_at cannot be in the future")
            received_dt = min(received_dt, now)
        if received_dt > now:
            raise InputError("received_at cannot be in the future")
    else:
        received_dt = now
    provider_ref = f"MANUAL:{ref}"
    fields = {"provider_ref": provider_ref, "currency": ccy, "amount_minor": amount, "payer_name": payer,
              "reference": reference.strip(), "received_at": iso(received_dt)}
    with ctx.conn() as conn, db.transaction(conn):
        existing = db.row(conn, "SELECT * FROM deposits WHERE provider_ref = ?", (provider_ref,))
        if existing:
            same = (existing["currency"], existing["amount_minor"], existing["payer_name"], existing["reference"]) == (
                ccy, amount, payer, fields["reference"])
            if not same:
                raise ReconcileError(f"external_ref {ref} was already recorded with different details ({existing['id']})")
            return {"deposit_id": existing["id"], "created": False}
        dep_id, created = ingest_deposit(conn, ctx, fields, source="manual_import")
        audit.record(conn, iso(now), actor, "payment.recorded_manually", "deposit", dep_id,
                     {"external_ref": ref, "note": "manually recorded, not bank-verified"})
        return {"deposit_id": dep_id, "created": created}


def resolve_deposit(ctx: AppContext, deposit_id: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
    """Operator resolution of an escalated deposit: allocate to the payer's own invoice, or hold as credit."""
    action = body.get("action")
    if action not in ("allocate", "credit"):
        raise InputError("action must be 'allocate' or 'credit' (use return-to-sender for refunds)")
    note = _text(body.get("note") or "", "note", 3, 300) if body.get("note") else None
    if note is None:
        raise InputError("a short note explaining the decision is required")
    with ctx.conn() as conn, db.transaction(conn):
        d = db.row(conn, "SELECT * FROM deposits WHERE id = ?", (deposit_id,))
        if d is None:
            raise InputError("unknown deposit")
        if d["status"] != ESCALATED:
            raise ReconcileError(f"{deposit_id} is {d['status']}; only escalated deposits are resolved manually")
        try:
            amount = to_minor(body.get("amount"), d["currency"])
        except MoneyError as exc:
            raise InputError(str(exc)) from exc
        if amount <= 0:
            raise InputError("amount must be greater than zero")
        unapplied = deposit_buckets(conn, deposit_id)["unapplied"]
        if amount > unapplied:
            raise InputError(f"amount exceeds the {fmt(unapplied, d['currency'])} still unapplied")
        customer_id = d["customer_id"]
        requested = body.get("customer_id") or None
        if customer_id and requested and requested != customer_id:
            raise InputError(f"this deposit was paid by {customer_id}; it cannot be applied to another customer")
        if not customer_id:
            if not requested or not db.row(conn, "SELECT id FROM customers WHERE id = ?", (requested,)):
                raise InputError("identify the paying customer (customer_id) before resolving an unidentified payment")
            customer_id = requested
        if action == "allocate":
            inv = invoice_views(conn).get(body.get("invoice_id") or "")
            if inv is None:
                raise InputError("invoice_id does not exist")
            if inv.customer_id != customer_id:
                raise InputError(f"{inv.id} belongs to {inv.customer_id}, not the payer {customer_id}")
            if inv.currency != d["currency"]:
                raise InputError(f"{inv.id} is billed in {inv.currency}; no implied FX on customer receipts")
            if inv.status != "open" or inv.remaining_minor < amount:
                raise InputError(f"{inv.id} has only {fmt(inv.remaining_minor, inv.currency)} outstanding")
            actions = [{"type": "allocate", "invoice_id": inv.id, "amount_minor": amount}]
            summary = f"Operator allocated {amount} to {inv.id}: {note}"
        else:
            if db.row(conn, "SELECT id FROM credits WHERE deposit_id = ?", (deposit_id,)):
                raise InputError("this deposit already funded a customer credit")
            actions = [{"type": "credit", "customer_id": customer_id, "amount_minor": amount, "earmark_invoice_id": None}]
            summary = f"Operator held {amount} as customer credit: {note}"
        plan = {"category": "operator_resolution", "summary": summary, "customer_id": customer_id, "actions": actions}
        result = _store_and_apply(conn, ctx, d, plan, kind="operator", evidence_id=None)
        audit.record(conn, iso(ctx.clock.now()), actor, "deposit.resolved_by_operator", "deposit", deposit_id,
                     {"action": action, "amount_minor": amount, "note": note, "customer_id": customer_id})
        return result


# --------------------------------------------------------------------------- edits and adjustments
def update_customer(ctx: AppContext, customer_id: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
    """Edit customer details. Changing the refund account invalidates any approval bound to the old one
    (the approval scope recheck sees a different destination)."""
    with ctx.conn() as conn, db.transaction(conn):
        cur = db.row(conn, "SELECT * FROM customers WHERE id = ?", (customer_id,))
        if cur is None:
            raise InputError("unknown customer")
        changes: dict[str, Any] = {}
        if "name" in body:
            changes["name"] = _text(body["name"], "name", 2, 80)
        if "country" in body:
            if not isinstance(body["country"], str) or not re.fullmatch(r"[A-Z]{2}", body["country"]):
                raise InputError("country must be a 2-letter ISO code")
            changes["country"] = body["country"]
        if "payer_names" in body:
            changes["payer_names"] = json.dumps(_payer_names(conn, body["payer_names"], exclude_customer=customer_id))
        if "refund_beneficiary" in body:
            changes["refund_beneficiary"] = _text(body["refund_beneficiary"], "refund_beneficiary", 2, 120)
        if "agent_public_key" in body:
            pub = body["agent_public_key"] or None
            if pub is not None:
                try:
                    if len(crypto.b64d(pub)) != 32:
                        raise ValueError
                except ValueError as exc:
                    raise InputError("agent_public_key must be a base64 raw Ed25519 public key (32 bytes)") from exc
            changes["agent_public_key"] = pub
            changes["agent_key_id"] = crypto.key_id_for(pub) if pub else None
        if not changes:
            raise InputError("nothing to change")
        now = iso(ctx.clock.now())
        for k, v in changes.items():
            conn.execute(f"UPDATE customers SET {k} = ? WHERE id = ?", (v, customer_id))  # keys whitelisted above
        conn.execute("UPDATE customers SET updated_at = ? WHERE id = ?", (now, customer_id))
        audit.record(conn, now, actor, "customer.updated", "customer", customer_id,
                     {k: {"from": cur.get(k), "to": v} for k, v in changes.items()})
        return db.row(conn, "SELECT * FROM customers WHERE id = ?", (customer_id,))


def update_invoice(ctx: AppContext, invoice_id: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
    """Edit non-monetary invoice fields. Amounts change only through audited adjustments."""
    if "amount" in body or "currency" in body or "customer_id" in body:
        raise InputError("amount, currency and customer cannot be edited; post an adjustment or void the invoice")
    with ctx.conn() as conn, db.transaction(conn):
        cur = db.row(conn, "SELECT * FROM invoices WHERE id = ?", (invoice_id,))
        if cur is None:
            raise InputError("unknown invoice")
        changes: dict[str, Any] = {}
        if "description" in body:
            changes["description"] = _text(body["description"], "description", 1, 200)
        if "due_date" in body:
            try:
                due = date.fromisoformat(str(body["due_date"]))
            except ValueError as exc:
                raise InputError("due_date must be YYYY-MM-DD") from exc
            changes["due_at"] = iso(datetime.combine(due, time(23, 59, 59), tzinfo=timezone.utc))
        if not changes:
            raise InputError("nothing to change")
        now = iso(ctx.clock.now())
        for k, v in changes.items():
            conn.execute(f"UPDATE invoices SET {k} = ? WHERE id = ?", (v, invoice_id))  # keys whitelisted above
        audit.record(conn, now, actor, "invoice.updated", "invoice", invoice_id,
                     {k: {"from": cur.get(k), "to": v} for k, v in changes.items()})
        return db.row(conn, "SELECT * FROM invoices WHERE id = ?", (invoice_id,))


def adjust_invoice(ctx: AppContext, invoice_id: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
    """Post an explicit, journaled adjustment (credit note or extra charge), or void an unpaid invoice."""
    kind = body.get("kind")
    if kind not in ("decrease", "increase", "void"):
        raise InputError("kind must be decrease, increase or void")
    reason = _text(body.get("reason") or "", "reason", 3, 200)
    with ctx.conn() as conn, db.transaction(conn):
        inv = invoice_views(conn).get(invoice_id)
        if inv is None:
            raise InputError("unknown invoice")
        if inv.status == "void":
            raise InputError("invoice is already void")
        if kind == "void":
            paid = db.row(conn, "SELECT 1 FROM allocations WHERE invoice_id = ?", (invoice_id,)) \
                or db.row(conn, "SELECT 1 FROM writeoffs WHERE invoice_id = ?", (invoice_id,)) \
                or db.row(conn, "SELECT 1 FROM invoices WHERE id = ? AND prior_paid_minor > 0", (invoice_id,))
            if paid:
                raise InputError("only invoices with no payments can be voided; post a decrease for the unpaid part instead")
            delta = -inv.amount_minor
        else:
            try:
                amount = to_minor(body.get("amount"), inv.currency)
            except MoneyError as exc:
                raise InputError(str(exc)) from exc
            if amount <= 0:
                raise InputError("amount must be greater than zero")
            if kind == "decrease" and amount > inv.remaining_minor:
                raise InputError(f"a decrease cannot exceed the {fmt(inv.remaining_minor, inv.currency)} outstanding")
            delta = -amount if kind == "decrease" else amount
        now = iso(ctx.clock.now())
        adj_id = "ADJ-" + uuid.uuid4().hex[:8].upper()
        conn.execute("INSERT INTO invoice_adjustments VALUES (?,?,?,?,?,?,?)",
                     (adj_id, invoice_id, inv.currency, delta, reason, actor, now))
        if inv.status != "scheduled":  # scheduled invoices were never posted to receivables
            lines = (audit.move("revenue", "accounts_receivable", inv.currency, -delta) if delta < 0
                     else audit.move("accounts_receivable", "revenue", inv.currency, delta))
            audit.post(conn, now, f"Invoice {invoice_id} adjustment {adj_id}", "invoice_adjustment", adj_id, lines)
        if kind == "void":
            conn.execute("UPDATE invoices SET voided_at = ? WHERE id = ?", (now, invoice_id))
        audit.record(conn, now, actor, "invoice.voided" if kind == "void" else "invoice.adjusted", "invoice", invoice_id,
                     {"adjustment_id": adj_id, "delta_minor": delta, "reason": reason})
        return {"adjustment_id": adj_id, "delta_minor": delta, "invoice_id": invoice_id}


# --------------------------------------------------------------------------- bulk payment import
_CSV_COLUMNS = ["external_ref", "received_at", "currency", "amount", "payer_name", "reference"]


def import_payments_csv(ctx: AppContext, text: Any, actor: str) -> dict[str, Any]:
    """Import statement lines (local workspace only). Each row goes through record_manual_payment, so
    idempotency and validation are identical; one bad row does not block the others."""
    import csv
    import io

    if not isinstance(text, str) or not text.strip():
        raise InputError("paste CSV text with a header row")
    if len(text) > 200_000:
        raise InputError("CSV is too large (max 200 KB per import)")
    reader = csv.DictReader(io.StringIO(text.strip()))
    if [h.strip() for h in (reader.fieldnames or [])] != _CSV_COLUMNS:
        raise InputError("header must be: " + ",".join(_CSV_COLUMNS))
    results = []
    for n, row in enumerate(reader, start=2):
        if n > 502:
            raise InputError("at most 500 rows per import")
        body = {k: (row.get(k) or "").strip() for k in _CSV_COLUMNS}
        try:
            r = record_manual_payment(ctx, body, actor)
            results.append({"line": n, "external_ref": body["external_ref"], "status": "created" if r["created"] else "duplicate",
                            "deposit_id": r["deposit_id"]})
        except (InputError, ReconcileError) as exc:
            results.append({"line": n, "external_ref": body["external_ref"], "status": "error", "error": str(exc)})
    return {"rows": len(results), "created": sum(r["status"] == "created" for r in results),
            "duplicates": sum(r["status"] == "duplicate" for r in results),
            "errors": sum(r["status"] == "error" for r in results), "results": results}


# --------------------------------------------------------------------------- treasury setup
def create_obligation(ctx: AppContext, body: dict[str, Any], actor: str) -> dict[str, Any]:
    payee = _text(body.get("payee"), "payee", 2, 80)
    description = _text(body.get("description") or payee, "description", 1, 200)
    try:
        ccy = validate_currency(body.get("currency"))
        amount = to_minor(body.get("amount"), ccy)
        due = date.fromisoformat(str(body.get("due_date")))
    except MoneyError as exc:
        raise InputError(str(exc)) from exc
    except ValueError as exc:
        raise InputError("due_date must be YYYY-MM-DD") from exc
    if amount <= 0:
        raise InputError("amount must be greater than zero")
    with ctx.conn() as conn, db.transaction(conn):
        ob_id = "OBL-" + uuid.uuid4().hex[:8].upper()
        conn.execute("INSERT INTO obligations VALUES (?,?,?,?,?,?, 'scheduled')",
                     (ob_id, payee, ccy, amount, iso(datetime.combine(due, time(12), tzinfo=timezone.utc)), description))
        audit.record(conn, iso(ctx.clock.now()), actor, "obligation.created", "obligation", ob_id,
                     {"payee": payee, "currency": ccy, "amount_minor": amount})
        return db.row(conn, "SELECT * FROM obligations WHERE id = ?", (ob_id,))


def set_opening_balance(ctx: AppContext, body: dict[str, Any], actor: str) -> dict[str, Any]:
    """Record a wallet's opening balance once, before any activity in that currency."""
    if ctx.local_bank is None:
        raise InputError("in sandbox mode balances come from Airwallex, not manual entry")
    try:
        ccy = validate_currency(body.get("currency"))
        amount = to_minor(body.get("amount"), ccy)
    except MoneyError as exc:
        raise InputError(str(exc)) from exc
    with ctx.conn() as conn, db.transaction(conn):
        if db.row(conn, "SELECT 1 FROM wallet_opening WHERE currency = ?", (ccy,)):
            raise InputError(f"{ccy} opening balance is already set; later corrections need an explicit journal adjustment")
        if db.row(conn, "SELECT 1 FROM journal_lines WHERE currency = ? AND account LIKE 'cash:%' LIMIT 1", (ccy,)):
            raise InputError(f"{ccy} already has cash activity; the opening balance must be set first")
        now = iso(ctx.clock.now())
        conn.execute("INSERT INTO wallet_opening VALUES (?,?)", (ccy, amount))
        if amount:
            audit.post(conn, now, f"Opening {ccy} wallet balance", "opening", ccy, audit.move(f"cash:{ccy}", "opening_equity", ccy, amount))
        audit.record(conn, now, actor, "wallet.opening_balance_set", "wallet", ccy, {"amount_minor": amount})
        return {"currency": ccy, "amount_minor": amount}
