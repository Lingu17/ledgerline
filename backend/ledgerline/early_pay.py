"""Closing a cash gap by bringing money in: a capped early-payment discount, offered through a hosted link.

- The discount and the link amount are computed in code and capped by policy; nothing is emailed.
- One live offer per invoice. An uncertain link creation is never retried automatically.
- Nothing is booked until the bank reports the link paid. Then the discount is an explicit journaled adjustment and the
  cash goes through the normal deposit path, in one transaction, idempotently on the link id.
- If the invoice balance changed after the offer, no discount is given and ordinary matching rules decide.
"""
from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.parse import urlsplit

from . import audit, db, treasury
from .clock import iso, parse_iso
from .context import AppContext
from .payouts import PayoutError
from .providers.base import ProviderAmbiguous, ProviderError, ProviderUnsupported
from .reconcile import ingest_deposit, invoice_views

DEFAULT_BPS = 150


def _terms(remaining: int, bps: int) -> tuple[int, int]:
    discount = remaining * bps // 10_000
    return discount, remaining - discount


def options(ctx: AppContext) -> dict[str, Any]:
    """The gap per currency, and invoices not yet due that could pay early to help close it. Decides nothing."""
    rates = treasury.decision_rates(ctx)
    with ctx.conn() as conn:
        now = ctx.clock.now()
        cap = ctx.policy(conn)["early_pay_max_bps"]
        decisions = treasury.rank_bills(conn, ctx, rates)
        gaps: dict[str, int] = {}
        for d in decisions:
            if d["decision"] in ("defer", "escalate"):
                gaps[d["currency"]] = gaps.get(d["currency"], 0) + d["shortfall_minor"]
        taken = {r["invoice_id"] for r in db.rows(conn, "SELECT invoice_id FROM early_pay_offers WHERE status IN ('creating','open','unknown')")}
        names = {c["id"]: c["name"] for c in db.rows(conn, "SELECT id, name FROM customers")}
        out = []
        for inv in invoice_views(conn).values():
            if inv.currency in gaps and inv.status == "open" and inv.remaining_minor > 0 and inv.id not in taken and parse_iso(inv.due_at) > now:
                bps = min(DEFAULT_BPS, cap)
                discount, cash = _terms(inv.remaining_minor, bps)
                out.append({"invoice_id": inv.id, "customer": names.get(inv.customer_id), "currency": inv.currency, "due_at": inv.due_at,
                            "remaining_minor": inv.remaining_minor, "discount_bps": bps, "discount_minor": discount, "cash_minor": cash,
                            "closes_gap": cash >= gaps[inv.currency]})
    out.sort(key=lambda o: (o["currency"], o["discount_minor"] if o["closes_gap"] else 10**15, -o["cash_minor"]))
    return {"gaps": gaps, "max_bps": cap, "options": out}


def create_offer(ctx: AppContext, invoice_id: str, bps: Any, actor: str) -> dict[str, Any]:
    if isinstance(bps, bool) or not isinstance(bps, int) or bps <= 0:
        raise PayoutError("discount must be a whole number of basis points above zero")
    with ctx.conn() as conn, db.transaction(conn):
        now_dt = ctx.clock.now()
        now = iso(now_dt)
        cap = ctx.policy(conn)["early_pay_max_bps"]
        if bps > cap:
            raise PayoutError(f"the policy allows at most {cap} basis points")
        inv = invoice_views(conn).get(invoice_id)
        if inv is None or inv.status != "open" or inv.remaining_minor <= 0:
            raise PayoutError("only an open invoice with a balance can be offered early payment")
        if parse_iso(inv.due_at) <= now_dt:
            raise PayoutError("this invoice is already due; there is nothing to pay early")
        if db.row(conn, "SELECT id FROM early_pay_offers WHERE invoice_id = ? AND status IN ('creating','open','unknown')", (invoice_id,)):
            raise PayoutError("this invoice already has a live early-payment offer")
        discount, amount = _terms(inv.remaining_minor, bps)
        if discount <= 0:
            raise PayoutError("this discount rounds to nothing on this balance")
        oid = "EPO-" + uuid.uuid4().hex[:8].upper()
        conn.execute("INSERT INTO early_pay_offers(id, invoice_id, customer_id, currency, invoice_remaining_minor, discount_bps, discount_minor, amount_minor, status, offered_by, created_at, updated_at)"
                     " VALUES (?,?,?,?,?,?,?,?,'creating',?,?,?)",
                     (oid, invoice_id, inv.customer_id, inv.currency, inv.remaining_minor, bps, discount, amount, actor, now, now))
        audit.record(conn, now, actor, "early_pay.offered", "invoice", invoice_id,
                     {"offer_id": oid, "discount_bps": bps, "discount_minor": discount, "amount_minor": amount})
        currency = inv.currency
    url, provider_id = None, None
    if ctx.sandbox is None:
        status, note = "open", "Practice offer: no hosted link exists on the simulated bank."
    else:
        try:
            result = ctx.sandbox.create_payment_link(title=f"Early payment for {invoice_id}", amount_minor=amount, currency=currency, reference=invoice_id)
            parsed = urlsplit(result.url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ProviderError("payment link response had no safe HTTPS URL")
            status, url, provider_id, note = "open", result.url, result.provider_id, "Hosted link created. Nothing was emailed; share it with the customer."
        except (ProviderUnsupported, ProviderError) as exc:
            status, note = "failed", f"Airwallex did not create a link: {str(exc)[:200]}. No automatic retry."
        except ProviderAmbiguous as exc:
            status, note = "unknown", f"Link outcome unknown ({str(exc)[:160]}). No URL recorded and no automatic retry."
    with ctx.conn() as conn, db.transaction(conn):
        now = iso(ctx.clock.now())
        conn.execute("UPDATE early_pay_offers SET status=?, url=?, provider_id=?, note=?, updated_at=? WHERE id=?", (status, url, provider_id, note, now, oid))
        audit.record(conn, now, actor, f"early_pay.link_{status}", "invoice", invoice_id, {"offer_id": oid, "provider_id": provider_id, "note": note})
        return db.row(conn, "SELECT * FROM early_pay_offers WHERE id = ?", (oid,))


def _settle(ctx: AppContext, offer_id: str, source: str, actor: str) -> dict[str, Any]:
    with ctx.conn() as conn, db.transaction(conn):
        o = db.row(conn, "SELECT * FROM early_pay_offers WHERE id = ?", (offer_id,))
        if o is None:
            raise PayoutError("unknown offer")
        if o["status"] != "open":
            return o
        now_dt = ctx.clock.now()
        now = iso(now_dt)
        inv = invoice_views(conn).get(o["invoice_id"])
        unchanged = inv is not None and inv.status == "open" and inv.remaining_minor == o["invoice_remaining_minor"]
        if unchanged:  # the agreed discount is written off first, so the payment then settles the invoice exactly
            adj = "ADJ-" + uuid.uuid4().hex[:8].upper()
            conn.execute("INSERT INTO invoice_adjustments VALUES (?,?,?,?,?,?,?)",
                         (adj, o["invoice_id"], o["currency"], -o["discount_minor"], f"Early-payment discount {o['id']}", actor, now))
            audit.post(conn, now, f"Early-payment discount on {o['invoice_id']}", "invoice_adjustment", adj,
                       audit.move("revenue", "accounts_receivable", o["currency"], o["discount_minor"]))
        customer = db.row(conn, "SELECT payer_names, name FROM customers WHERE id = ?", (o["customer_id"],))
        payer = (json.loads(customer["payer_names"]) or [customer["name"]])[0]
        deposit_id, _ = ingest_deposit(conn, ctx, {
            "provider_ref": f"LINK:{o['provider_id'] or o['id']}", "currency": o["currency"], "amount_minor": o["amount_minor"],
            "payer_name": payer, "reference": o["invoice_id"], "received_at": now}, source=source)
        conn.execute("UPDATE early_pay_offers SET status='paid', deposit_id=?, note=?, updated_at=? WHERE id=?",
                     (deposit_id, None if unchanged else "The invoice changed after the offer, so no discount was given.", now, offer_id))
        audit.record(conn, now, actor, "early_pay.paid", "invoice", o["invoice_id"],
                     {"offer_id": offer_id, "deposit_id": deposit_id, "amount_minor": o["amount_minor"],
                      "discount_applied_minor": o["discount_minor"] if unchanged else 0})
    treasury.refresh_decisions(ctx, f"early payment for {o['invoice_id']} received", actor)
    with ctx.conn() as conn:
        return db.row(conn, "SELECT * FROM early_pay_offers WHERE id = ?", (offer_id,))


def check(ctx: AppContext, offer_id: str, actor: str) -> dict[str, Any]:
    with ctx.conn() as conn:
        o = db.row(conn, "SELECT * FROM early_pay_offers WHERE id = ?", (offer_id,))
    if o is None:
        raise PayoutError("unknown offer")
    if o["status"] != "open" or not o["provider_id"] or ctx.sandbox is None:
        return o
    if not ctx.sandbox.payment_link_paid(o["provider_id"]):
        return o
    return _settle(ctx, offer_id, "airwallex_payment_link", actor)


def practice_paid(ctx: AppContext, offer_id: str, actor: str) -> dict[str, Any]:
    """Simulated bank only: the customer pays. A connected account must report the payment itself."""
    if ctx.sandbox is not None:
        raise PayoutError("on a connected account the payment must be reported by Airwallex")
    return _settle(ctx, offer_id, "practice_payment_link", actor)


def list_offers(ctx: AppContext) -> list[dict[str, Any]]:
    with ctx.conn() as conn:
        return db.rows(conn, "SELECT o.*, c.name AS customer FROM early_pay_offers o JOIN customers c ON c.id = o.customer_id ORDER BY o.created_at DESC")

