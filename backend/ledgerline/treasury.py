"""Cash placement: keep reserves, cover upcoming obligations, convert only the deficit."""
from __future__ import annotations

import json
import sqlite3
import time
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
        ring_fenced = policy["ring_fenced_minor"][ccy]
        held = credits + unapplied + refunds_reserved + ring_fenced
        # In-flight conversions (persisted when booked): the sell side is reserved, the buy side counts as pending cover.
        fx_out_reserved = _sum(conn, "SELECT COALESCE(SUM(amount_minor),0) FROM operations WHERE kind='fx_conversion' AND currency = ? AND status IN ('pending','processing')", (ccy,))
        fx_in_pending = _sum(conn, "SELECT COALESCE(SUM(CAST(json_extract(detail,'$.buy_amount_minor') AS BIGINT)),0) FROM operations WHERE kind='fx_conversion' AND json_extract(detail,'$.buy_currency') = ? AND status IN ('pending','processing')", (ccy,))
        out[ccy] = {
            "currency": ccy,
            "cash": cash,
            "reserve": reserve,
            "ring_fenced": ring_fenced,
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


# --------------------------------------------------------------------------- short-cash decisions
PRIORITY_ORDER = {"critical": 0, "normal": 1, "flexible": 2}
_RATE_CACHE: dict[str, tuple[float, dict[tuple[str, str], Decimal]]] = {}


def decision_rates(ctx: AppContext) -> dict[tuple[str, str], Decimal]:
    """Indicative rates for planning. Call outside a transaction: a connected account may need a network read.
    An unavailable rate leaves that pair out, so the plan escalates instead of guessing."""
    if ctx.provider.name != "airwallex_sandbox":
        return dict(DEMO_RATES)
    key = ctx.org["id"] if ctx.org else "default"
    hit = _RATE_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < 60:
        return hit[1]
    rates: dict[tuple[str, str], Decimal] = {}
    for sell, buy in DEMO_RATES:
        try:
            rates[(sell, buy)] = Decimal(ctx.provider.current_rate(sell, buy)["rate"])
        except (ProviderError, ProviderAmbiguous):
            continue
    _RATE_CACHE[key] = (time.monotonic(), rates)
    return rates


def rank_bills(conn: sqlite3.Connection, ctx: AppContext, rates: dict[tuple[str, str], Decimal]) -> list[dict[str, Any]]:
    """Rank the bills in the look-ahead window and decide each one: fund, convert, defer or escalate.

    Most important first, then earliest due. Each decision uses up cash, so a surplus is never promised twice.
    A source currency only offers what is left after its own reserve, held funds and bills in the window.
    """
    pos = wallet_position(conn, ctx)
    now = ctx.clock.now()
    horizon = now + timedelta(days=ctx.policy(conn)["obligation_lookahead_days"])
    available = {c: p["projected_after_pending_fx"] + p["obligations_due_in_window"] for c, p in pos.items()}
    surplus = {c: max(0, p["free_after_commitments"]) for c, p in pos.items()}
    bills = [b for b in db.rows(conn, "SELECT * FROM obligations WHERE status = 'scheduled'") if parse_iso(b["due_at"]) <= horizon]
    bills.sort(key=lambda b: (PRIORITY_ORDER.get(b["priority"], 1), b["due_at"], b["id"]))
    out = []
    for rank, bill in enumerate(bills, start=1):
        ccy, amount = bill["currency"], bill["amount_minor"]
        # A wallet already below its reserve must be refilled first, so that gap is part of the shortfall.
        shortfall = max(0, amount - available[ccy])
        source = None
        if shortfall == 0:
            decision = "fund"
            reason = f"{ccy} cash covers this bill after the reserve, held funds and higher-ranked bills."
        else:
            options = []
            for sell in surplus:
                rate = rates.get((sell, ccy))
                if sell != ccy and rate and surplus[sell] > 0 and convert_round(surplus[sell], sell, ccy, rate) >= shortfall:
                    options.append((convert_round(surplus[sell], sell, ccy, rate), sell))
            if options:
                decision, source = "convert", max(options)[1]
                # Round the amount to sell up, so the same surplus cannot also be offered to a lower-ranked bill.
                sell_minor = convert_round(shortfall, ccy, source, rates.get((ccy, source)) or 1 / rates[(source, ccy)]) + 1
                surplus[source] = max(0, surplus[source] - sell_minor)
                reason = f"Short {fmt(shortfall, ccy)}: convert only that amount from {source} surplus above its reserve."
            elif bill["defer_until"] and parse_iso(bill["defer_until"]) > max(now, parse_iso(bill["due_at"])):
                decision = "defer"
                reason = f"Short {fmt(shortfall, ccy)} with no surplus to convert: this bill may wait until {bill['defer_until'][:10]}."
            else:
                decision = "escalate"
                reason = f"Short {fmt(shortfall, ccy)}, no surplus to convert and no permitted later date: a person must decide."
        if decision in ("fund", "convert"):
            available[ccy] = max(0, available[ccy] - amount) if decision == "fund" else 0
        out.append({"obligation_id": bill["id"], "payee": bill["payee"], "currency": ccy, "amount_minor": amount,
                    "due_at": bill["due_at"], "priority": bill["priority"], "defer_until": bill["defer_until"], "rank": rank,
                    "decision": decision, "shortfall_minor": shortfall, "source_currency": source, "reason": reason})
    return out


def refresh_decisions(ctx: AppContext, trigger: str, actor: str = "system") -> dict[str, Any]:
    """Re-run the plan and reopen only the decisions the new position changes. Decides; moves no money."""
    rates = decision_rates(ctx)
    with ctx.conn() as conn, db.transaction(conn):
        now = iso(ctx.clock.now())
        ranked = rank_bills(conn, ctx, rates)
        stored = {d["obligation_id"]: d for d in db.rows(conn, "SELECT * FROM treasury_decisions")}
        changed, unchanged = [], 0
        live = set()
        for d in ranked:
            live.add(d["obligation_id"])
            old = stored.get(d["obligation_id"])
            same = old and (old["decision"], old["shortfall_minor"], old["source_currency"]) == (d["decision"], d["shortfall_minor"], d["source_currency"])
            if same:
                unchanged += 1
                if old["rank_no"] != d["rank"]:
                    conn.execute("UPDATE treasury_decisions SET rank_no = ? WHERE obligation_id = ?", (d["rank"], d["obligation_id"]))
                continue
            version = (old["version"] + 1) if old else 1
            conn.execute("DELETE FROM treasury_decisions WHERE obligation_id = ?", (d["obligation_id"],))
            conn.execute("INSERT INTO treasury_decisions(obligation_id, decision, rank_no, shortfall_minor, source_currency, reason, version, decided_at, trigger)"
                         " VALUES (?,?,?,?,?,?,?,?,?)",
                         (d["obligation_id"], d["decision"], d["rank"], d["shortfall_minor"], d["source_currency"], d["reason"], version, now, trigger))
            audit.record(conn, now, actor, "treasury.decision", "obligation", d["obligation_id"],
                         {"from": old["decision"] if old else None, "to": d["decision"], "shortfall_minor": d["shortfall_minor"],
                          "source_currency": d["source_currency"], "trigger": trigger, "reason": d["reason"]})
            changed.append({"obligation_id": d["obligation_id"], "from": old["decision"] if old else None, "to": d["decision"]})
        for gone in set(stored) - live:  # paid, or moved out of the window by an applied deferral
            conn.execute("DELETE FROM treasury_decisions WHERE obligation_id = ?", (gone,))
        kept = {d["obligation_id"]: d for d in db.rows(conn, "SELECT * FROM treasury_decisions")}
    return {"decisions": [{**d, "version": kept[d["obligation_id"]]["version"], "decided_at": kept[d["obligation_id"]]["decided_at"],
                           "trigger": kept[d["obligation_id"]]["trigger"]} for d in ranked],
            "changed": changed, "unchanged": unchanged, "rates_available": len(rates) == len(DEMO_RATES)}


def _live_payment(conn: sqlite3.Connection, obligation_id: str) -> bool:
    return bool(db.row(conn, "SELECT 1 FROM bill_payments WHERE obligation_id = ? AND status NOT IN ('rejected','invalidated','failed','cancelled')", (obligation_id,)))


def apply_deferral(ctx: AppContext, obligation_id: str, actor: str) -> dict[str, Any]:
    """A person accepts a deferral: the due date moves to the bill's permitted date, with the old date audited."""
    with ctx.conn() as conn, db.transaction(conn):
        bill = db.row(conn, "SELECT * FROM obligations WHERE id = ?", (obligation_id,))
        if bill is None:
            raise TreasuryError("unknown bill")
        d = db.row(conn, "SELECT * FROM treasury_decisions WHERE obligation_id = ?", (obligation_id,))
        if d is None or d["decision"] != "defer":
            raise TreasuryError("the current decision for this bill is not to defer it")
        if _live_payment(conn, obligation_id):
            raise TreasuryError("a payment for this bill is in progress")
        now = iso(ctx.clock.now())
        conn.execute("UPDATE obligations SET due_at = ?, defer_until = NULL WHERE id = ?", (bill["defer_until"], obligation_id))
        audit.record(conn, now, actor, "obligation.deferred", "obligation", obligation_id, {"from": bill["due_at"], "to": bill["defer_until"]})
    return refresh_decisions(ctx, f"{obligation_id} deferred", actor)


def mark_bill_paid(ctx: AppContext, obligation_id: str, actor: str) -> dict[str, Any]:
    """Record a bill paid from the business account. Ledgerline does not send supplier payments itself."""
    with ctx.conn() as conn, db.transaction(conn):
        bill = db.row(conn, "SELECT * FROM obligations WHERE id = ?", (obligation_id,))
        if bill is None or bill["status"] != "scheduled":
            raise TreasuryError("only a scheduled bill can be marked paid")
        if _live_payment(conn, obligation_id):
            raise TreasuryError("a payment for this bill is in progress; it will close when the bank reports it paid")
        now = iso(ctx.clock.now())
        conn.execute("UPDATE obligations SET status = 'paid' WHERE id = ?", (obligation_id,))
        audit.post(conn, now, f"Bill {obligation_id} paid: {bill['payee']}", "obligation", obligation_id,
                   audit.move("bills_paid", f"cash:{bill['currency']}", bill["currency"], bill["amount_minor"]))
        audit.record(conn, now, actor, "obligation.paid", "obligation", obligation_id, {"amount_minor": bill["amount_minor"], "currency": bill["currency"]})
    return refresh_decisions(ctx, f"{obligation_id} paid", actor)


def add_practice_squeeze(ctx: AppContext, actor: str) -> dict[str, Any]:
    """Practice companies only: add GBP bills sized from today's position so all four decisions appear.

    The last bills miss by about GBP 1,000, so paying off an open GBP invoice visibly reopens a decision.
    """
    rates = decision_rates(ctx)
    with ctx.conn() as conn, db.transaction(conn):
        if db.row(conn, "SELECT 1 FROM obligations WHERE id = 'OBL-SQUEEZE-PAYROLL'"):
            raise TreasuryError("the cash squeeze example is already in this practice company")
        now = ctx.clock.now()
        pos = wallet_position(conn, ctx)
        surplus = {c: max(0, p["free_after_commitments"]) for c, p in pos.items() if c != "GBP"}
        for d in rank_bills(conn, ctx, rates):  # conversions already planned use up their source
            if d["source_currency"] in surplus:
                back = rates.get((d["currency"], d["source_currency"])) or 1 / rates[(d["source_currency"], d["currency"])]
                surplus[d["source_currency"]] -= convert_round(d["shortfall_minor"], d["currency"], d["source_currency"], back)
        in_gbp = {c: convert_round(max(0, v), c, "GBP", rates[(c, "GBP")]) for c, v in surplus.items() if (c, "GBP") in rates}
        best = max(in_gbp, key=in_gbp.get)
        have = max(0, pos["GBP"]["projected_after_pending_fx"])
        payroll = have // 2 or 50_000
        to_convert = in_gbp[best] // 2
        left = max(in_gbp[best] - to_convert, *(v for c, v in in_gbp.items() if c != best))
        bills = [
            ("OBL-SQUEEZE-PAYROLL", "UK payroll", payroll, 2, "critical", None),
            ("OBL-SQUEEZE-SUPPLIER", "Harbour Packaging Ltd", have - payroll + to_convert, 3, "normal", None),
            ("OBL-SQUEEZE-TAX", "HMRC VAT", left + 100_000, 4, "normal", None),
            ("OBL-SQUEEZE-AGENCY", "Studio Fabrik", left + 100_000, 5, "flexible", 30),
        ]
        for oid, payee, amount, due, priority, later in bills:
            conn.execute("INSERT INTO obligations(id, payee, currency, amount_minor, due_at, description, status, priority, defer_until) VALUES (?,?,?,?,?,?, 'scheduled', ?, ?)",
                         (oid, payee, "GBP", amount, iso(now + timedelta(days=due)), "Practice cash squeeze", priority,
                          iso(now + timedelta(days=later)) if later else None))
        audit.record(conn, iso(now), actor, "practice.cash_squeeze_added", "treasury", "practice", {"bills": [b[0] for b in bills]})
    return refresh_decisions(ctx, "cash squeeze added", actor)


def _cover_needed(conn: sqlite3.Connection, ctx: AppContext, obligation_id: str,
                  rates: dict[tuple[str, str], Decimal]) -> tuple[int, str | None, str]:
    """(amount to buy, source, currency). A 'convert' decision buys this bill's shortfall; otherwise the whole wallet's.

    Ranked live from the connection's own view, never from a stored decision: inside execute_conversion's
    IMMEDIATE transaction this must see a conversion another request has just booked.
    """
    plan = plan_for_obligation(conn, ctx, obligation_id)
    d = next((x for x in rank_bills(conn, ctx, rates) if x["obligation_id"] == obligation_id), None)
    if d and d["decision"] == "convert":
        return d["shortfall_minor"], d["source_currency"], plan["obligation"]["currency"]
    return plan["deficit"], plan["source_currency"], plan["obligation"]["currency"]


def create_quote(ctx: AppContext, obligation_id: str, actor: str) -> dict[str, Any]:
    rates = decision_rates(ctx)
    with ctx.conn() as conn:
        need, source, currency = _cover_needed(conn, ctx, obligation_id, rates)
    if need == 0:
        raise TreasuryError("no shortfall: nothing to convert")
    if not source:
        raise TreasuryError("no currency has enough surplus above its reserve to cover the shortfall")
    q: Quote = ctx.provider.create_quote(sell_currency=source, buy_currency=currency, buy_amount_minor=need)
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
    rates = decision_rates(ctx)  # a connected account may need a network read, so before the lock
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
            need = _cover_needed(conn, ctx, q["obligation_id"], rates)[0]
            if need != q["buy_amount_minor"]:
                raise TreasuryError(f"shortfall is now {need} (pending conversions included); request a new quote")
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
