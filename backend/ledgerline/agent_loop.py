"""The agent acts on its own: an unclear payment gets its question asked as soon as it arrives, with nobody clicking.

The answer goes through the same three checks as ever, and money rules do not change: anything over the limit still
waits for a person. A practice company stays paused on purpose, so someone can watch the decision change, unless the
payment is delivered as a new arrival. If an agent cannot be reached, the payment simply stays waiting and is retried.
"""
from __future__ import annotations

import logging
from typing import Any

from . import audit, db, payouts, treasury
from .clock import iso
from .context import AppContext
from .payer_agents.client import ask_agents, explain_payments
from .reconcile import ReconcileError, pending_agent_questions, record_agent_answer

log = logging.getLogger("ledgerline.agent")
ACTOR = "agent:auto"


def ask_pending(ctx: AppContext, only: str | None = None) -> dict[str, Any]:
    """Ask about waiting payments and apply the verified outcome. Safe to call repeatedly and alongside the button."""
    with ctx.conn() as conn:
        questions = [q for q in pending_agent_questions(conn) if only is None or q["deposit_id"] == only]
    if not questions:
        return {"asked": 0, "results": []}
    try:
        asked = ask_agents(ctx, questions, simulated=explain_payments)
    except Exception as exc:  # noqa: BLE001 - an unreachable agent must never lose the payment; it stays waiting
        log.warning("payer agent unavailable: %s", type(exc).__name__)
        return {"asked": 0, "results": [], "error": type(exc).__name__}
    results = []
    transport = None
    for q, answer, transport, problem in asked:
        if answer is None:  # the customer's own agent could not be asked this time; the payment stays waiting
            log.warning("payer agent for %s not asked: %s", q["deposit_id"], problem)
            continue
        try:
            with ctx.conn() as conn, db.transaction(conn):
                r = record_agent_answer(conn, ctx, q["deposit_id"], q["customer_id"], answer, transport)
                audit.record(conn, iso(ctx.clock.now()), ACTOR, "agent.asked_automatically", "deposit", q["deposit_id"],
                             {"customer_id": q["customer_id"], "verdict": r["verification"]["verdict"]})
        except ReconcileError:  # someone else answered it first
            continue
        results.append({"deposit_id": q["deposit_id"], "verdict": r["verification"]["verdict"], "category": r["plan"]["category"]})
    if results:
        payouts.auto_execute_ready(ctx, ACTOR)
        treasury.refresh_decisions(ctx, "payer agent answered", ACTOR)
    return {"asked": len(results), "results": results, "transport": transport}


def on_arrival(ctx: AppContext) -> None:
    """Called after a payment arrives. Real companies are handled at once; a practice company waits to be watched."""
    if ctx.org and ctx.org.get("kind") != "sample" and ctx.org.get("agent_auto_ask", True):
        ask_pending(ctx)
