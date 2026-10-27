"""Cash placement: keep reserves, cover upcoming obligations, convert only the deficit."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from . import audit, db
from .clock import iso, parse_iso
from .context import AppContext
from .money import CURRENCY_EXPONENT, convert_round, fmt
from .payouts import Paused, PayoutError
from .providers.base import ProviderAmbiguous, ProviderError, Quote
from .providers.local import DEMO_RATES


class TreasuryError(ValueError):
    pass


def _sum(conn, sql, params=()) -> int:
    return int(conn.execute(sql, params).fetchone()[0] or 0)


def wallet_position(conn: sqlite3.Connection, ctx: AppContext) -> dict[str, dict[str, Any]]:
    """Per-currency cash and what is already spoken for. Never mixes currencies."""
    policy = ctx.policy(conn)
    now = ctx.clock.now()
    horizon = now + timedelta(days=policy["obligation_lookahead_days"])
    out: dict[str, dict[str, Any]] = {}
    for ccy in CURRENCY_EXPONENT:
        cash = _sum(conn, "SELECT COALESCE(SUM(debit_minor - credit_minor),0) FROM journal_lines WHERE account = ? AND currency = ?",
                    (f"cash:{ccy}", ccy))
        credits = -_sum(conn, "SELECT COALESCE(SUM(debit_minor - credit_minor),0) FROM journal_lines WHERE account='customer_credit' AND currency = ?", (ccy,))
        unapplied = -_sum(conn, "SELECT COALESCE(SUM(debit_minor - credit_minor),0) FROM journal_lines WHERE account='unapplied_cash' AND currency = ?", (ccy,))
        refunds_reserved = _sum(conn, "SELECT COALESCE(SUM(amount_minor),0) FROM operations WHERE kind='refund' AND currency = ? AND status IN ('pending','processing') AND COALESCE(CAST(json_extract(detail,'$.cash_out_posted') AS TEXT),'0') IN ('0','false')", (ccy,))
        obligations = db.rows(conn, "SELECT * FROM obligations WHERE currency = ? AND status = 'scheduled' ORDER BY due_at", (ccy,))
        due_soon = sum(o["amount_minor"] for o in obligations if parse_iso(o["due_at"]) <= horizon)
        reserve = policy["reserve_minor"][ccy]
        held = credits + unapplied + refunds_reserved
        # In-flight conversions (persisted when booked): the sell side is reserved, the buy side counts as pending cover.
        fx_out_reserved = _sum(conn, "SELECT COALESCE(SUM(amount_minor),0) FROM operations WHERE kind='fx_conversion' AND currency = ? AND status IN ('pending','processing')", (ccy,))
        fx_in_pending = _sum(conn, "SELECT COALESCE(SUM(CAST(json_extract(detail,'$.buy_amount_minor') AS BIGINT)),0) FROM operations WHERE kind='fx_conversion' AND json_extract(detail,'$.buy_currency') = ? AND status IN ('pending','processing')", (ccy,))
        out[ccy] = {
            "currency": ccy,
            "cash": cash,
            "reserve": reserve,
            "customer_credits": credits,
            "unapplied_held": unapplied,
            "refunds_reserved": refunds_reserved,
            "obligations_due_in_window": due_soon,
            "fx_out_reserved": fx_out_reserved,
            "fx_in_pending": fx_in_pending,
            # Spendable: settled cash only. Pending FX proceeds are never spendable.
            "free_after_commitments": cash - reserve - held - due_soon - fx_out_reserved,
            # Forecast: counts pending inbound conversions as cover, used only to decide whether more FX is needed.
            "projected_after_pending_fx": cash - reserve - held - due_soon - fx_out_reserved + fx_in_pending,
            "obligations": obligations,
        }
    return out


def plan_for_obligation(conn: sqlite3.Connection, ctx: AppContext, obligation_id: str) -> dict[str, Any]:
    ob = db.row(conn, "SELECT * FROM obligations WHERE id = ?", (obligation_id,))
    if ob is None:
        raise TreasuryError("unknown obligation")
    pos = wallet_position(conn, ctx)
    target = pos[ob["currency"]]
    deficit = max(0, -target["projected_after_pending_fx"])
    candidates = []
    for ccy, p in pos.items():
        if ccy == ob["currency"] or (ccy, ob["currency"]) not in DEMO_RATES:
            continue
        surplus = p["free_after_commitments"]
        if surplus <= 0:
            continue
        rate = DEMO_RATES[(ccy, ob["currency"])]
        candidates.append({"currency": ccy, "surplus": surplus, "indicative_rate": str(rate),
                           "surplus_in_target": convert_round(surplus, ccy, ob["currency"], rate)})
    candidates.sort(key=lambda c: -c["surplus_in_target"])
    source = next((c for c in candidates if c["surplus_in_target"] >= deficit), None)
    return {
        "obligation": ob,
        "target": {k: v for k, v in target.items() if k != "obligations"},
        "deficit": deficit,
        "source_candidates": candidates,
        "source_currency": source["currency"] if source and deficit > 0 else None,
        "explanation": (
            f"{ob['currency']} cash covers this obligation, the reserve and held funds; no conversion needed."
            if deficit == 0 else
            f"Convert only the {ob['currency']} shortfall of {fmt(deficit, ob['currency'])}; reserves in every currency are preserved."
        ),
    }


def create_quote(ctx: AppContext, obligation_id: str, actor: str) -> dict[str, Any]:
    with ctx.conn() as conn:
        plan = plan_for_obligation(conn, ctx, obligation_id)
    if plan["deficit"] == 0:
        raise TreasuryError("no shortfall: nothing to convert")
    if not plan["source_currency"]:
        raise TreasuryError("no currency has enough surplus above its reserve to cover the shortfall")
    q: Quote = ctx.provider.create_quote(sell_currency=plan["source_currency"], buy_currency=plan["obligation"]["currency"],
                                         buy_amount_minor=plan["deficit"])
    with ctx.conn() as conn, db.transaction(conn):
        now = iso(ctx.clock.now())
        qid = "FXQ-" + uuid.uuid4().hex[:8].upper()
        conn.execute(
            "INSERT INTO fx_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (qid, q.provider_quote_id, q.source, q.sell_currency, q.buy_currency, q.sell_amount_minor, q.buy_amount_minor,
             str(q.rate), obligation_id, iso(q.valid_to), None, now),
        )
        audit.record(conn, now, actor, "fx.quote", "obligation", obligation_id,
                     {"quote_id": qid, "sell": [q.sell_currency, q.sell_amount_minor], "buy": [q.buy_currency, q.buy_amount_minor],
                      "rate": str(q.rate), "valid_to": iso(q.valid_to), "source": q.source})
        return quote_preview(conn, ctx, qid)


def quote_preview(conn: sqlite3.Connection, ctx: AppContext, quote_id: str) -> dict[str, Any]:
    q = db.row(conn, "SELECT * FROM fx_quotes WHERE id = ?", (quote_id,))
    if q is None:
        raise TreasuryError("unknown quote")
    pos = wallet_position(conn, ctx)
    s, b = pos[q["sell_currency"]], pos[q["buy_currency"]]
    now = ctx.clock.now()
    return {
        "quote": q,
        "expired": parse_iso(q["valid_to"]) <= now,
        "used": q["used_by_operation"] is not None,
        "seconds_left": max(0, int((parse_iso(q["valid_to"]) - now).total_seconds())),
        "before": {q["sell_currency"]: s["cash"], q["buy_currency"]: b["cash"]},
        "after": {q["sell_currency"]: s["cash"] - q["sell_amount_minor"], q["buy_currency"]: b["cash"] + q["buy_amount_minor"]},
        "source_reserve": s["reserve"],
        "source_free_after": s["free_after_commitments"] - q["sell_amount_minor"],
        "target_projected_after": b["projected_after_pending_fx"] + q["buy_amount_minor"],
    }


def execute_conversion(ctx: AppContext, quote_id: str, actor: str) -> dict[str, Any]:
    """Book a conversion: the quote is consumed and the sell amount reserved in one IMMEDIATE transaction,
    so a second quote for the same shortfall sees the pending cover and cannot book the same money."""
    with ctx.conn() as conn:
        with db.transaction(conn):
            now_dt = ctx.clock.now()
            now = iso(now_dt)
            q = db.row(conn, "SELECT * FROM fx_quotes WHERE id = ?", (quote_id,))
            if q is None:
                raise TreasuryError("unknown quote")
            if q["used_by_operation"]:
                raise TreasuryError("quote already used; quotes are single-use")
            if parse_iso(q["valid_to"]) <= now_dt:
                raise TreasuryError("quote expired; request a new quote")
            if ctx.paused(conn):
                raise Paused("money movement is paused")
            plan = plan_for_obligation(conn, ctx, q["obligation_id"])
            if plan["deficit"] != q["buy_amount_minor"]:
                raise TreasuryError(f"shortfall is now {plan['deficit']} (pending conversions included); request a new quote")
            src = wallet_position(conn, ctx)[q["sell_currency"]]
            if src["free_after_commitments"] < q["sell_amount_minor"]:
                raise TreasuryError(f"selling {q['sell_amount_minor']} {q['sell_currency']} would breach its reserve")
            op_id = "OP-" + uuid.uuid4().hex[:8].upper()
            request_id = str(uuid.uuid4())
            detail = {"quote_id": quote_id, "buy_currency": q["buy_currency"], "buy_amount_minor": q["buy_amount_minor"],
                      "obligation_id": q["obligation_id"], "rate": q["rate"]}
            conn.execute(
                "INSERT INTO operations(id, kind, deposit_id, request_id, currency, amount_minor, destination, status, detail,"
                " needs_reconciliation, created_at, updated_at, attempts) VALUES (?,?,?,?,?,?,?,?,?,1,?,?,1)",
                (op_id, "fx_conversion", None, request_id, q["sell_currency"], q["sell_amount_minor"],
                 f"{q['buy_currency']} wallet", "processing", json.dumps(detail), now, now),
            )
            conn.execute("UPDATE fx_quotes SET used_by_operation = ? WHERE id = ?", (op_id, quote_id))
            _fx_event(conn, op_id, None, "processing", "booked; sell amount reserved", now)
            audit.record(conn, now, actor, "fx.conversion.requested", "operation", op_id,
                         {"quote_id": quote_id, "request_id": request_id, "sell": [q["sell_currency"], q["sell_amount_minor"]],
                          "buy": [q["buy_currency"], q["buy_amount_minor"]]}, operation_id=op_id)

    quote = Quote(q["provider_quote_id"], q["sell_currency"], q["buy_currency"], q["sell_amount_minor"],
                  q["buy_amount_minor"], Decimal(q["rate"]), parse_iso(q["valid_to"]), q["source"])
    try:
        res = ctx.provider.create_conversion(request_id=request_id, quote=quote)
        outcome: tuple[str, str | None, str | None] = (res.status, res.provider_id, None)
    except ProviderAmbiguous as exc:
        outcome = ("ambiguous", None, str(exc))
    except ProviderError as exc:
        outcome = ("failed", None, str(exc))
    op = _record_fx_outcome(ctx, op_id, *outcome)
    if op["status"] == "failed":
        raise PayoutError(f"conversion failed: {op['last_error']}")
    return op


def _fx_event(conn, op_id, frm, to, detail, now):
    conn.execute("INSERT INTO operation_events(operation_id, from_status, to_status, detail, at) VALUES (?,?,?,?,?)",
                 (op_id, frm, to, detail, now))


def _record_fx_outcome(ctx: AppContext, op_id: str, status: str, provider_id: str | None, error: str | None) -> dict[str, Any]:
    """Apply a provider answer. Cash moves only on a verified SETTLED status; anything else keeps the reservation."""
    with ctx.conn() as conn, db.transaction(conn):
        now = iso(ctx.clock.now())
        op = db.row(conn, "SELECT * FROM operations WHERE id = ?", (op_id,))
        if op["status"] in ("settled", "failed"):
            return op  # already final; never post twice
        detail = json.loads(op["detail"])
        if provider_id:
            conn.execute("UPDATE operations SET provider_id = ? WHERE id = ?", (provider_id, op_id))
        if status == "ambiguous":
            conn.execute("UPDATE operations SET needs_reconciliation=1, last_error=?, updated_at=? WHERE id = ?", (error, now, op_id))
            _fx_event(conn, op_id, op["status"], "processing", f"ambiguous: {error}; reservation held, reconcile by request_id", now)
        elif status not in ("settled", "failed"):  # processing, or any unexpected status: treat as unknown
            conn.execute("UPDATE operations SET needs_reconciliation=0, last_error=NULL, updated_at=? WHERE id = ?", (now, op_id))
            _fx_event(conn, op_id, op["status"], "processing", "provider reports not yet settled; reservation held", now)
        elif status == "settled":
            conn.execute("UPDATE operations SET status='settled', needs_reconciliation=0, last_error=NULL, updated_at=? WHERE id = ?",
                         (now, op_id))
            _fx_event(conn, op_id, op["status"], "settled", "provider reports SETTLED", now)
            audit.post(conn, now, f"FX {op_id}: sell {op['currency']}", "operation", op_id,
                       audit.move("fx_clearing", f"cash:{op['currency']}", op["currency"], op["amount_minor"]))
            audit.post(conn, now, f"FX {op_id}: buy {detail['buy_currency']}", "operation", op_id,
                       audit.move(f"cash:{detail['buy_currency']}", "fx_clearing", detail["buy_currency"], detail["buy_amount_minor"]))
        else:  # failed or cancelled: release the reservation, no cash moved
            conn.execute("UPDATE operations SET status='failed', needs_reconciliation=0, last_error=?, updated_at=? WHERE id = ?",
                         (error or "provider reports CANCELLED", now, op_id))
            _fx_event(conn, op_id, op["status"], "failed", (error or "provider reports CANCELLED") + "; reservation released", now)
        audit.record(conn, now, "provider", f"fx.conversion.{status}", "operation", op_id, {"error": error}, operation_id=op_id)
        return db.row(conn, "SELECT * FROM operations WHERE id = ?", (op_id,))


def sync_conversion(ctx: AppContext, op_id: str) -> dict[str, Any]:
    """Reconcile an in-flight conversion with the provider (by id, or by request_id after an ambiguous call)."""
    with ctx.conn() as conn:
        op = db.row(conn, "SELECT * FROM operations WHERE id = ? AND kind = 'fx_conversion'", (op_id,))
    if op is None:
        raise TreasuryError("unknown conversion")
    if op["status"] != "processing":
        return op
    try:
        if op["provider_id"]:
            res = ctx.provider.get_conversion(op["provider_id"])
        else:
            res = ctx.provider.find_conversion(op["request_id"])
    except ProviderAmbiguous as exc:
        return _record_fx_outcome(ctx, op_id, "ambiguous", None, str(exc))
    if res is None:
        # A missing lookup result is not proof of rejection (it may be delayed): stay reserved and unresolved.
        return _record_fx_outcome(ctx, op_id, "ambiguous", None, "provider lookup found no conversion yet; still unresolved")
    return _record_fx_outcome(ctx, op_id, res.status, res.provider_id, None)
