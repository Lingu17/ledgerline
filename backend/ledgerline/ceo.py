"""One screen for whoever runs the company. Reads only; every figure comes from the same records as the detailed pages."""
from __future__ import annotations

from typing import Any

from . import audit, db, demo, ledger, treasury
from .clock import parse_iso
from .context import AppContext
from .money import CURRENCY_EXPONENT
from .reconcile import invoice_views

# An assumption, shown beside the figure it produces. Nothing has measured how long a payment takes a real team.
MINUTES_PER_PAYMENT = 15


def _needing(n: int) -> str:
    return "1 item needs a person." if n == 1 else f"{n} items need a person."


def summary(ctx: AppContext, work_queue: list[dict[str, Any]]) -> dict[str, Any]:
    rates = treasury.decision_rates(ctx)
    score = demo.scorecard(ctx)
    with ctx.conn() as conn:
        now = ctx.clock.now()
        pos = treasury.wallet_position(conn, ctx)
        bills = treasury.rank_bills(conn, ctx, rates)
        open_invoices = [i for i in invoice_views(conn).values() if i.status == "open" and i.remaining_minor > 0]
        currencies = []
        for ccy in CURRENCY_EXPONENT:
            p = pos[ccy]
            mine = [i for i in open_invoices if i.currency == ccy]
            currencies.append({
                "currency": ccy, "cash": p["cash"], "reserve": p["reserve"], "bills_due": p["obligations_due_in_window"], "free": p["free_after_commitments"],
                "held": p["unapplied_held"], "owed_to_us": sum(i.remaining_minor for i in mine),
                "overdue": sum(i.remaining_minor for i in mine if parse_iso(i.due_at) <= now),
            })
        refunds_avoided = int(conn.execute("SELECT COUNT(*) FROM deposits WHERE category = 'verified_advance_credit'").fetchone()[0])
        false_claims = int(conn.execute("SELECT COUNT(DISTINCT deposit_id) FROM evidence WHERE verdict = 'rejected'").fetchone()[0])
        chain = audit.verify_chain(conn)
        balanced = ledger.conservation(conn)["all_balanced"]
        paused = ctx.paused(conn)
        lookahead = ctx.policy(conn)["obligation_lookahead_days"]
        offers = db.rows(conn, "SELECT discount_minor, currency FROM early_pay_offers WHERE status = 'paid'")
    short = [b for b in bills if b["decision"] in ("defer", "escalate")]
    trusted = balanced and chain["ok"] and score["double_payments"] == 0
    if not trusted:
        verdict, headline = "problem", "Stop and check: the records do not reconcile."
    elif short or work_queue:
        verdict, headline = "attention", f"The books are sound. {_needing(len(work_queue) + len(short))}"
    else:
        verdict, headline = "ok", "Nothing needs you today."
    return {
        "verdict": verdict, "headline": headline, "lookahead_days": lookahead, "paused": paused, "currencies": currencies,
        "agent": {"payments": score["deposits"], "settled_without_person": score["settled_without_human"], "refunds_avoided": refunds_avoided,
                  "false_claims_caught": false_claims, "early_cash_offers_paid": len(offers),
                  "estimated_minutes_saved": score["settled_without_human"] * MINUTES_PER_PAYMENT, "minutes_per_payment_assumed": MINUTES_PER_PAYMENT},
        "needs_you": work_queue[:10], "needs_you_total": len(work_queue), "short_bills": short,
        "trust": {"ledger_balanced": balanced, "log_intact": chain["ok"], "log_events": chain["events"], "double_payments": score["double_payments"]},
    }
