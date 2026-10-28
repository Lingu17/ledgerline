"""Guided demo runner and scorecard. Every number comes from the database."""
from __future__ import annotations

import uuid
from typing import Any

from . import audit, db, payouts, treasury
from .clock import iso
from .context import AppContext
from .money import to_major
from .payer_agents.client import explain_payments
from .payer_agents.keys import key_location
from .providers.base import ProviderError, ProviderUnsupported
from .reconcile import pending_agent_questions, record_agent_answer
from .scenario import reset_demo, scenario_deposit_payloads
from .webhooks import build_deposit_event, handle, sign

STEPS = [
    ("seed", "Reset demo data", "Seed customers, invoices, obligations and opening balances (synthetic)."),
    ("deposits", "Receive six deposits", "Six signed deposit.settled webhooks run through verification, dedupe and the rules engine."),
    ("links", "Request the short balance", "Publish a payment link for the exact balance, or record an honest draft if links are unavailable."),
    ("agents", "Ask payer agents", "Call explain_payment over MCP, verify the three checks, revise plans."),
    ("treasury", "Cover the EUR bill", "Quote and convert only the EUR shortfall above reserve."),
    ("approve", "Approve the refund", "A person approves the over-limit refund on the Approvals page, then it executes under the duplicate lock."),
    ("bank_sent", "Bank reports SENT", "The refund is SENT. Not final: the liability stays on the books."),
    ("bank_paid", "Bank reports PAID", "Final. Liability released; conservation checked to the cent."),
]
STEP_IDS = [s[0] for s in STEPS]


class DemoError(ValueError):
    pass


def state(ctx: AppContext) -> dict[str, Any]:
    with ctx.conn() as conn:
        done = db.get_setting(conn, "demo_steps_done", [])
        nxt = next((s for s in STEP_IDS if s not in done), None)
        blocked = None
        if nxt == "approve":
            a = db.row(conn, "SELECT * FROM approvals WHERE operation_type='refund' AND status IN ('pending','approved') ORDER BY created_at LIMIT 1")
            executed = db.row(conn, "SELECT id FROM operations WHERE kind='refund' AND deposit_id='DEP-1006'")
            if a is None and executed:
                blocked = None
            elif a is None:
                blocked = "no refund approval is waiting"
            elif a["status"] == "pending":
                blocked = f"waiting for a person to approve {a['id']} on the Approvals page"
        return {
            "steps": [{"id": i, "title": t, "description": d, "done": i in done} for i, t, d in STEPS],
            "next": nxt,
            "blocked": blocked,
            "provider": ctx.provider.label,
        }


def _mark(ctx: AppContext, step: str) -> None:
    with ctx.conn() as conn, db.transaction(conn):
        done = db.get_setting(conn, "demo_steps_done", [])
        if step not in done:
            done.append(step)
        db.set_setting(conn, "demo_steps_done", done)


def run_step(ctx: AppContext, step: str, actor: str) -> dict[str, Any]:
    st = state(ctx)
    if step != "seed" and step != st["next"]:
        raise DemoError(f"next step is {st['next']!r}, not {step!r}")
    result: dict[str, Any]
    if step == "seed":
        with ctx.conn() as conn:
            reset_demo(conn, key_location(ctx.settings), ctx.clock.now())
            with db.transaction(conn):
                db.set_setting(conn, "demo_steps_done", [])
        if ctx.local_bank is not None:
            ctx.local_bank.reset()
        result = {"seeded": True}
    elif step == "deposits":
        result = {"webhooks": ingest_scenario_deposits(ctx)}
        if any(item.get("status") == "awaiting_webhook" for item in result["webhooks"]):
            return {"step": step, "result": result, "state": state(ctx)}
    elif step == "links":
        result = {"links": publish_payment_links(ctx, actor)}
    elif step == "agents":
        result = ask_payer_agents(ctx)
    elif step == "treasury":
        with ctx.conn() as conn:
            covered = treasury.plan_for_obligation(conn, ctx, "OBL-EUR-HOSTING")["deficit"] == 0
        if covered:  # already converted from the Treasury page
            _mark(ctx, step)
            return {"step": step, "result": {"already_done": True}, "state": state(ctx)}
        quote = treasury.create_quote(ctx, "OBL-EUR-HOSTING", actor)
        op = treasury.execute_conversion(ctx, quote["quote"]["id"], actor)
        result = {"quote": quote, "operation": op}
    elif step == "approve":
        if st["blocked"]:
            raise DemoError(st["blocked"])
        with ctx.conn() as conn:
            a = db.row(conn, "SELECT id FROM approvals WHERE operation_type='refund' AND status='approved' ORDER BY created_at LIMIT 1")
        result = payouts.execute_refund(ctx, a["id"], actor) if a else {"already_done": True}
    elif step in ("bank_sent", "bank_paid"):
        with ctx.conn() as conn:
            op = db.row(conn, "SELECT * FROM operations WHERE kind='refund' AND status IN ('processing','sent') ORDER BY created_at LIMIT 1")
        if op is None:
            with ctx.conn() as conn:
                done = db.row(conn, "SELECT status FROM operations WHERE kind='refund' AND status IN ('sent','paid') ORDER BY created_at LIMIT 1")
            if done and (step == "bank_sent" or done["status"] == "paid"):
                _mark(ctx, step)
                return {"step": step, "result": {"already_done": True}, "state": state(ctx)}
            raise DemoError("no refund in flight")
        if op["needs_reconciliation"]:
            op = payouts.sync_operation(ctx, op["id"])
        result = {"operation": payouts.simulate_bank_status(ctx, op["id"], "SENT" if step == "bank_sent" else "PAID")}
    else:
        raise DemoError(f"unknown step {step}")
    _mark(ctx, step)
    return {"step": step, "result": result, "state": state(ctx)}


def ingest_scenario_deposits(ctx: AppContext) -> list[dict[str, Any]]:
    """LOCAL DEMO: deliver each scenario deposit as a signed webhook through the real handler.

    In sandbox mode the deposits are first created with POST /simulation/deposit/create
    against the configured global account for that currency.
    """
    out = []
    payloads = scenario_deposit_payloads(ctx.clock.now())
    if ctx.sandbox is not None:
        missing = sorted({f["currency"] for f in payloads} - set(ctx.settings.airwallex_global_account_ids))
        if missing:
            raise DemoError(f"configure dedicated sandbox global accounts for {', '.join(missing)} before simulating deposits")
    for fields in payloads:
        source = "local_simulated_webhook"
        if ctx.sandbox is not None:
            gid = ctx.settings.airwallex_global_account_ids.get(fields["currency"])
            # Simulation has no documented request_id. Reserve the attempt durably before
            # dispatch, so a timeout/retry cannot silently create the same deposit twice.
            marker = f"sandbox_demo_deposit:{fields['provider_ref']}"
            with ctx.conn() as conn, db.transaction(conn):
                attempt = db.get_setting(conn, marker, None)
                if attempt is None:
                    db.set_setting(conn, marker, {"status": "submitting"})
            if attempt is None:
                created = ctx.sandbox.simulate_deposit(global_account_id=gid, currency=fields["currency"],
                                                       amount_minor=fields["amount_minor"], payer_name=fields["payer_name"],
                                                       reference=fields["reference"])
                if not isinstance(created.get("id"), str) or not created["id"]:
                    raise DemoError("sandbox response has no deposit id; reconcile the attempt before retrying")
                attempt = {"id": created["id"]}
                with ctx.conn() as conn, db.transaction(conn):
                    db.set_setting(conn, marker, attempt)
                    conn.execute("INSERT OR IGNORE INTO deposit_hints VALUES (?,?,?,?)",
                                 (created["id"], fields["payer_name"], fields["reference"], iso(ctx.clock.now())))
            if not attempt.get("id"):
                raise DemoError("sandbox deposit attempt needs reconciliation; it will not be automatically repeated")
            with ctx.conn() as conn:
                received = db.row(conn, "SELECT id FROM deposits WHERE provider_ref = ?", (attempt["id"],))
            out.append({"status": "processed" if received else "awaiting_webhook", "provider_ref": attempt["id"]})
            # Only Airwallex's authenticated settled event may make sandbox money spendable.
            # Never manufacture a local SETTLED event from a PENDING simulation response.
            continue
        body = build_deposit_event("evt_" + uuid.uuid4().hex[:16], fields, str(to_major(fields["amount_minor"], fields["currency"])))
        ts = str(int(ctx.clock.now().timestamp() * 1000))
        secret = ctx.settings.webhook_secret
        out.append(handle(ctx, raw_body=body, timestamp_ms=ts, signature=sign(secret, ts, body), secret=secret, source=source))
    return out


def publish_payment_links(ctx: AppContext, actor: str) -> list[dict[str, Any]]:
    with ctx.conn() as conn:
        drafts = db.rows(conn, "SELECT * FROM payment_links WHERE status = 'local_draft'")
    out = []
    for link in drafts:
        try:
            res = ctx.provider.create_payment_link(title=f"Balance due on {link['invoice_id']}", amount_minor=link["amount_minor"],
                                                   currency=link["currency"], reference=link["invoice_id"])
            status, url, pid, note = "sandbox_created", res.url, res.provider_id, "Hosted payment link created in Airwallex sandbox."
        except (ProviderUnsupported, ProviderError) as exc:
            status, url, pid = "draft_fallback", None, None
            note = f"Payment link not available ({exc}). Balance-due email drafted for a person to send; nothing was sent."
        with ctx.conn() as conn, db.transaction(conn):
            conn.execute("UPDATE payment_links SET status=?, url=?, provider_id=?, note=? WHERE id = ?", (status, url, pid, note, link["id"]))
            audit.record(conn, iso(ctx.clock.now()), actor, f"payment_link.{status}", "invoice", link["invoice_id"],
                         {"link_id": link["id"], "amount_minor": link["amount_minor"], "note": note})
        out.append({"id": link["id"], "status": status, "note": note})
    return out


def ask_payer_agents(ctx: AppContext) -> dict[str, Any]:
    with ctx.conn() as conn:
        questions = pending_agent_questions(conn)
    answers, transport = explain_payments(key_location(ctx.settings), questions, ctx.settings.payer_mcp_transport)
    results = []
    for q, ans in zip(questions, answers):
        with ctx.conn() as conn, db.transaction(conn):
            r = record_agent_answer(conn, ctx, q["deposit_id"], q["customer_id"], ans, transport)
        results.append({"deposit_id": q["deposit_id"], "verdict": r["verification"]["verdict"],
                        "reason": r["verification"]["reason"], "category": r["plan"]["category"]})
    # Refunds within the auto-limit execute immediately; larger ones wait for a person.
    payouts.auto_execute_ready(ctx)
    return {"transport": transport, "asked": len(questions), "results": results}


def scorecard(ctx: AppContext) -> dict[str, Any]:
    from .ledger import conservation

    with ctx.conn() as conn:
        deps = db.rows(conn, "SELECT id, status, category FROM deposits")
        human_touched = {r["deposit_id"] for r in db.rows(conn, "SELECT deposit_id FROM approvals WHERE decided_by NOT LIKE 'policy:%' OR status='pending'")}
        escalated = [d for d in deps if d["status"] == "escalated"]
        auto = [d for d in deps if d["id"] not in human_touched and d["status"] in ("matched", "partially_applied", "credited", "refunded")]
        live_refunds_per_deposit = db.rows(conn, "SELECT deposit_id, COUNT(*) AS n FROM operations WHERE kind='refund' AND status NOT IN ('failed','cancelled') GROUP BY deposit_id HAVING COUNT(*) > 1")
        provider_dupes = 0
        if ctx.local_bank is not None:
            for d in deps:
                if ctx.local_bank.count_transfers(f"Ledgerline refund {d['id']}") > 1:
                    provider_dupes += 1
        cons = conservation(conn)
        return {
            "deposits": len(deps),
            "settled_without_human": len(auto),
            "approvals_by_person": len(human_touched),
            "escalations": len(escalated),
            "escalation_reasons": [db.row(conn, "SELECT id, escalation_reason FROM deposits WHERE id = ?", (d["id"],)) for d in escalated],
            "double_payments": len(live_refunds_per_deposit) + provider_dupes,
            "ledger_balanced": cons["all_balanced"],
        }
