"""A customer paid in the wrong currency: convert only what the invoice needs, or hold it for a bill in that currency.

- Rules in code work out the amounts and recommend convert or hold. A person chooses; nothing converts by itself.
- The quote comes from the bank and is booked once. The sold amount leaves the deposit's unapplied balance at booking,
  and the invoice's balance is reserved, so another payment or a refund cannot use the same money.
- Cash and the invoice are posted only when the bank reports SETTLED (treasury._record_fx_outcome). A failure releases both.
- Anything left after the invoice is covered stays on the deposit, in its original currency, for a person to place.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from . import audit, db, treasury
from .clock import iso, parse_iso
from .context import AppContext
from .money import convert_round, fmt
from .payouts import NO_BANK, Paused, PayoutError, records_only
from .providers.base import ProviderAmbiguous, ProviderError
from .reconcile import ESCALATED, deposit_buckets, invoice_views
from .treasury import TreasuryError
from .sender import through_sender

_MARGIN = 99  # when the deposit cannot cover the invoice, buy a little less than the indicative rate suggests, so the real quote fits


def _buy_amount(unapplied: int, ccy: str, remaining: int, target: str, rates: dict) -> int:
    value = convert_round(unapplied, ccy, target, rates[(ccy, target)])
    return remaining if value * _MARGIN // 100 >= remaining else value * _MARGIN // 100


def options(ctx: AppContext, deposit_id: str) -> dict[str, Any]:
    """What converting would do for each of this customer's invoices in another currency, and what the rules recommend."""
    rates = treasury.decision_rates(ctx)
    with ctx.conn() as conn:
        d = db.row(conn, "SELECT * FROM deposits WHERE id = ?", (deposit_id,))
        if d is None:
            raise PayoutError("unknown deposit")
        if d["category"] != "wrong_currency" or d["status"] != ESCALATED:
            return {"applies": False}
        unapplied = deposit_buckets(conn, deposit_id)["unapplied"]
        pos = treasury.wallet_position(conn, ctx)[d["currency"]]
        rows = []
        for inv in invoice_views(conn).values():
            if inv.customer_id == d["customer_id"] and inv.currency != d["currency"] and inv.status == "open" and inv.remaining_minor > 0 \
                    and (d["currency"], inv.currency) in rates and unapplied > 0:
                buy = _buy_amount(unapplied, d["currency"], inv.remaining_minor, inv.currency, rates)
                if buy > 0:
                    sell = min(unapplied, convert_round(buy, inv.currency, d["currency"], 1 / rates[(d["currency"], inv.currency)]))
                    rows.append({"invoice_id": inv.id, "currency": inv.currency, "remaining_minor": inv.remaining_minor,
                                 "buy_minor": buy, "estimated_sell_minor": sell, "covers_invoice": buy == inv.remaining_minor})
        live = db.row(conn, "SELECT * FROM deposit_conversions WHERE deposit_id = ? AND status = 'processing'", (deposit_id,))
    bills = pos["obligations_due_in_window"]
    needs_it = bills > 0 and pos["free_after_commitments"] < 0
    if needs_it:
        advice, why = "hold", (f"{fmt(bills, d['currency'])} of bills fall due soon and this currency is short by "
                               f"{fmt(-pos['free_after_commitments'], d['currency'])}, so keeping this money may save a conversion later.")
    elif rows:
        advice, why = "convert", "No bill in this currency needs the money, so converting only what the invoice needs settles it."
    else:
        advice, why = "hold", "This customer has no open invoice this payment could settle."
    return {"applies": True, "unapplied_minor": unapplied, "currency": d["currency"], "advice": advice, "why": why, "invoices": rows, "live": live}


@through_sender("convert_deposit")
def convert(ctx: AppContext, deposit_id: str, invoice_id: Any, actor: str) -> dict[str, Any]:
    if records_only(ctx):
        raise TreasuryError(NO_BANK.replace("make the payment in your bank, then record it here", "convert in your bank, then record the payment as resolved"))
    rates = treasury.decision_rates(ctx)
    with ctx.conn() as conn:
        d = db.row(conn, "SELECT * FROM deposits WHERE id = ?", (deposit_id,))
        inv = invoice_views(conn).get(invoice_id) if isinstance(invoice_id, str) else None
        if d is None or inv is None:
            raise PayoutError("unknown deposit or invoice")
        if d["category"] != "wrong_currency" or d["status"] != ESCALATED:
            raise PayoutError("only a held wrong-currency payment can be converted this way")
        if inv.customer_id != d["customer_id"]:
            raise PayoutError(f"{inv.id} belongs to another customer")
        if inv.currency == d["currency"] or inv.status != "open" or inv.remaining_minor <= 0:
            raise PayoutError(f"{inv.id} cannot take a conversion from {d['currency']}")
        if (d["currency"], inv.currency) not in rates:
            raise PayoutError("no current rate for this pair; try again shortly")
        unapplied = deposit_buckets(conn, deposit_id)["unapplied"]
    if unapplied <= 0:
        raise PayoutError("nothing on this payment is left to convert")
    buy = _buy_amount(unapplied, d["currency"], inv.remaining_minor, inv.currency, rates)
    if buy <= 0:
        raise PayoutError("this payment is too small to convert")
    q = ctx.provider.create_quote(sell_currency=d["currency"], buy_currency=inv.currency, buy_amount_minor=buy)
    with ctx.conn() as conn, db.transaction(conn):
        now = iso(ctx.clock.now())
        if ctx.paused(conn):
            raise Paused("money movement is paused")
        if parse_iso(iso(q.valid_to)) <= ctx.clock.now():
            raise TreasuryError("quote expired; try again")
        cur = db.row(conn, "SELECT status FROM deposits WHERE id = ?", (deposit_id,))
        if cur["status"] != ESCALATED or db.row(conn, "SELECT id FROM deposit_conversions WHERE deposit_id = ? AND status = 'processing'", (deposit_id,)):
            raise PayoutError("a conversion for this payment is already under way")
        if q.sell_amount_minor > deposit_buckets(conn, deposit_id)["unapplied"]:
            raise TreasuryError("the rate moved and this payment no longer covers the quote; try again")
        if invoice_views(conn)[inv.id].remaining_minor < buy:
            raise PayoutError(f"{inv.id} changed; review it again")
        cid, op_id, request_id = "DCV-" + uuid.uuid4().hex[:8].upper(), "OP-" + uuid.uuid4().hex[:8].upper(), str(uuid.uuid4())
        detail = {"deposit_conversion": cid, "invoice_id": inv.id, "buy_currency": q.buy_currency, "buy_amount_minor": q.buy_amount_minor,
                  "rate": str(q.rate), "provider_quote_id": q.provider_quote_id}
        conn.execute(
            "INSERT INTO operations(id, kind, deposit_id, request_id, currency, amount_minor, destination, status, detail,"
            " needs_reconciliation, created_at, updated_at, attempts) VALUES (?,?,?,?,?,?,?,?,?,1,?,?,1)",
            (op_id, "fx_conversion", deposit_id, request_id, q.sell_currency, q.sell_amount_minor, f"{q.buy_currency} wallet", "processing", json.dumps(detail), now, now))
        conn.execute("INSERT INTO deposit_conversions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (cid, deposit_id, inv.id, op_id, q.sell_currency, q.sell_amount_minor, q.buy_currency, q.buy_amount_minor, "processing", actor, now))
        treasury._fx_event(conn, op_id, None, "processing", "booked for a wrong-currency payment; deposit and invoice amounts reserved", now)
        audit.record(conn, now, actor, "deposit.conversion_requested", "deposit", deposit_id,
                     {"conversion": cid, "invoice_id": inv.id, "sell": [q.sell_currency, q.sell_amount_minor], "buy": [q.buy_currency, q.buy_amount_minor],
                      "rate": str(q.rate), "request_id": request_id}, operation_id=op_id)
    try:
        res = ctx.provider.create_conversion(request_id=request_id, quote=q)
        outcome: tuple[str, str | None, str | None] = (res.status, res.provider_id, None)
    except ProviderAmbiguous as exc:
        outcome = ("ambiguous", None, str(exc))
    except ProviderError as exc:
        outcome = ("failed", None, str(exc))
    op = treasury._record_fx_outcome(ctx, op_id, *outcome)
    if op["status"] == "failed":
        raise PayoutError(f"conversion failed: {op['last_error']}; the payment stays held")
    return op
