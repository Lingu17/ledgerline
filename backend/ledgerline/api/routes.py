"""HTTP routes. Thin: validation and orchestration live in the domain modules."""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from .. import agent_loop, audit, bill_payments, ceo, claude_reader, db, demo, early_pay, ledger, payouts, treasury, webhooks, workspace, wrong_currency
from ..clock import iso
from ..context import AppContext, validate_policy
from ..payer_agents.client import SimulatedAgentFailed, ask_agents, explain_payments, simulated_transport
from ..providers.local import DEMO_RATES
from ..reconcile import deposit_buckets, latest_plan, pending_agent_questions, record_agent_answer
from .security import require_operator, require_owner, require_reader

log = logging.getLogger("ledgerline.api")
router = APIRouter()
read = [Depends(require_reader)]


def ctx_of(request: Request) -> AppContext:
    """The authenticated member's organization context (set by the role dependency)."""
    return request.state.principal.ctx


def _page(response: Response, total: int) -> None:
    response.headers["X-Total-Count"] = str(total)


def _loads(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    for k in keys:
        if row.get(k) is not None and isinstance(row[k], str):
            row[k] = json.loads(row[k])
    return row


# --------------------------------------------------------------------------- status
@router.get("/status", dependencies=read)
def status(request: Request) -> dict[str, Any]:
    ctx = ctx_of(request)
    s = ctx.settings
    with ctx.conn() as conn:
        paused = ctx.paused(conn)
        pause_info = db.get_setting(conn, "money_out_pause_info", None)
        policy = ctx.policy(conn)
        epoch = db.get_setting(conn, "demo_epoch")
    return {
        "now": iso(ctx.clock.now()),
        "demo_epoch": epoch,
        "bank": {
            "mode": ctx.provider.name,
            # A real company with no bank keeps records only; the simulated bank's name is for practice companies.
            "label": "No bank connected (you record payments made in your own bank)" if payouts.records_only(ctx) else ctx.provider.label,
            "airwallex_credentials_present": s.airwallex_configured or bool(s.sender_socket),
            "airwallex_keys_held_by": "sending service" if s.sender_socket else "app",
            "airwallex_executed_in_this_build": False,
            "sandbox_available": s.airwallex_configured or bool(s.sender_socket),
            "global_accounts_configured": sorted(s.airwallex_global_account_ids),
        },
        "claude": {
            "mode": "claude_api" if s.claude_configured else "deterministic_fixture",
            "model": s.claude_model if s.claude_configured else None,
            "label": f"Claude API ({s.claude_model})" if s.claude_configured else "Deterministic fixture - Claude not invoked (no ANTHROPIC_API_KEY)",
        },
        "payer_agents": {
            "transport": "mcp/stdio" if simulated_transport(ctx) == "stdio" else "mcp/in-memory",
            "label": "Customer agents hosted on this server, real MCP protocol",
        },
        "security": {
            "bind_host": s.host,
            "cookie_secure": s.cookie_secure,
            "allowed_origins": list(s.allowed_origins),
            "webhook_secret_source": "organization Airwallex secret" if s.airwallex_webhook_secret else "organization local secret",
            "webhook_path": f"/api/webhooks/airwallex/{ctx.org['id']}" if ctx.org else None,
        },
        "org": ctx.org,
        "role": request.state.principal.role,
        "paused": paused,
        "pause_info": pause_info,
        "policy": policy,
        "demo_fx_rates": [{"sell": a, "buy": b, "rate": str(r)} for (a, b), r in DEMO_RATES.items()],
    }


# --------------------------------------------------------------------------- overview
def _work_queue(conn) -> list[dict[str, Any]]:
    queue = []
    for d in db.rows(conn, "SELECT * FROM deposits WHERE status IN ('awaiting_evidence','escalated','refund_awaiting_approval','refund_in_flight') ORDER BY received_at"):
        queue.append({"kind": "deposit", "id": d["id"], "status": d["status"], "currency": d["currency"],
                      "amount_minor": d["amount_minor"], "payer_name": d["payer_name"], "reason": d["escalation_reason"]})
    for a in db.rows(conn, "SELECT * FROM approvals WHERE status = 'pending'"):
        scope = json.loads(a["scope"])
        queue.append({"kind": "approval", "id": a["id"], "status": "pending", "currency": scope["currency"],
                      "amount_minor": scope["amount_minor"], "payer_name": scope["destination"], "reason": a["reason"]})
    for p in db.rows(conn, "SELECT * FROM bill_payments WHERE status = 'proposed'"):
        queue.append({"kind": "approval", "id": p["id"], "status": "pending", "currency": p["currency"],
                      "amount_minor": p["amount_minor"], "payer_name": p["destination"], "reason": "bill payment waiting for a second person"})
    for o in db.rows(conn, "SELECT * FROM operations WHERE needs_reconciliation = 1"):
        queue.append({"kind": "operation", "id": o["id"], "status": o["status"], "currency": o["currency"],
                      "amount_minor": o["amount_minor"], "payer_name": o["destination"], "reason": o["last_error"]})
    return queue


@router.get("/ceo", dependencies=read)
def ceo_view(request: Request) -> dict[str, Any]:
    ctx = ctx_of(request)
    with ctx.conn() as conn:
        queue = _work_queue(conn)
    return ceo.summary(ctx, queue)


@router.get("/overview", dependencies=read)
def overview(request: Request) -> dict[str, Any]:
    ctx = ctx_of(request)
    with ctx.conn() as conn:
        pos = treasury.wallet_position(conn, ctx)
        counts = {r["status"]: r["n"] for r in db.rows(conn, "SELECT status, COUNT(*) AS n FROM deposits GROUP BY status")}
        queue = _work_queue(conn)
        cons = ledger.conservation(conn)
        paused = ctx.paused(conn)
    return {
        "wallets": [{k: v for k, v in p.items() if k != "obligations"} for p in pos.values()],
        "deposit_counts": counts,
        "work_queue": queue,
        "conservation": {c: v["balanced"] for c, v in cons["currencies"].items()},
        "all_balanced": cons["all_balanced"],
        "scorecard": demo.scorecard(ctx),
        "paused": paused,
    }


# --------------------------------------------------------------------------- deposits
def _deposit_summary(conn, d: dict[str, Any]) -> dict[str, Any]:
    plan = latest_plan(conn, d["id"])
    cust = db.row(conn, "SELECT name FROM customers WHERE id = ?", (d["customer_id"],)) if d["customer_id"] else None
    return {**d, "customer_name": cust["name"] if cust else None, "buckets": deposit_buckets(conn, d["id"]),
            "plan": plan, "plan_count": conn.execute("SELECT COUNT(*) FROM plans WHERE deposit_id = ?", (d["id"],)).fetchone()[0]}


@router.get("/deposits", dependencies=read)
def list_deposits(request: Request, response: Response, status: str | None = None, currency: str | None = None,
                  q: str | None = Query(None, max_length=80), limit: int = Query(200, ge=1, le=500),
                  offset: int = Query(0, ge=0)) -> list[dict[str, Any]]:
    ctx = ctx_of(request)
    sql, params = "SELECT * FROM deposits WHERE 1=1", []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if currency:
        sql += " AND currency = ?"
        params.append(currency)
    if q:
        sql += " AND (id LIKE ? OR payer_name LIKE ? OR reference LIKE ? OR provider_ref LIKE ?)"
        params += [f"%{q}%"] * 4
    with ctx.conn() as conn:
        _page(response, conn.execute(sql.replace("SELECT *", "SELECT COUNT(*)", 1), tuple(params)).fetchone()[0])
        rows = db.rows(conn, sql + " ORDER BY received_at DESC, id DESC LIMIT ? OFFSET ?", (*params, limit, offset))
        return [_deposit_summary(conn, d) for d in rows]


@router.get("/deposits/{deposit_id}", dependencies=read)
def get_deposit(request: Request, deposit_id: str) -> dict[str, Any]:
    ctx = ctx_of(request)
    with ctx.conn() as conn:
        d = db.row(conn, "SELECT * FROM deposits WHERE id = ?", (deposit_id,))
        if d is None:
            raise HTTPException(404, "unknown deposit")
        plans = [_loads(p, "actions") for p in db.rows(conn, "SELECT * FROM plans WHERE deposit_id = ? ORDER BY version", (deposit_id,))]
        evidence = [_loads(e, "checks", "envelope") for e in db.rows(conn, "SELECT * FROM evidence WHERE deposit_id = ? ORDER BY version", (deposit_id,))]
        return {
            **_deposit_summary(conn, d),
            "plans": plans,
            "evidence": evidence,
            "allocations": db.rows(conn, "SELECT * FROM allocations WHERE deposit_id = ?", (deposit_id,)),
            "writeoffs": db.rows(conn, "SELECT * FROM writeoffs WHERE deposit_id = ?", (deposit_id,)),
            "credits": db.rows(conn, "SELECT * FROM credits WHERE deposit_id = ?", (deposit_id,)),
            "payment_links": db.rows(conn, "SELECT * FROM payment_links WHERE deposit_id = ?", (deposit_id,)),
            "approvals": [_loads(a, "scope") for a in db.rows(conn, "SELECT * FROM approvals WHERE deposit_id = ? ORDER BY created_at", (deposit_id,))],
            "operations": [_loads(o, "detail") for o in db.rows(conn, "SELECT * FROM operations WHERE deposit_id = ? ORDER BY created_at", (deposit_id,))],
            "audit": [_loads(a, "detail") for a in db.rows(conn, "SELECT * FROM audit_events WHERE entity_id = ? OR detail LIKE ? ORDER BY id", (deposit_id, f'%"{deposit_id}"%'))],
            "has_remittance_doc": d["provider_ref"] in claude_reader.REMITTANCE_DOCS,
        }


@router.get("/deposits/{deposit_id}/wrong-currency", dependencies=read)
def wrong_currency_options(request: Request, deposit_id: str) -> dict[str, Any]:
    return wrong_currency.options(ctx_of(request), deposit_id)


@router.post("/deposits/{deposit_id}/wrong-currency/convert")
def wrong_currency_convert(request: Request, deposit_id: str, body: dict[str, Any], operator: str = Depends(require_operator)) -> dict[str, Any]:
    return wrong_currency.convert(ctx_of(request), deposit_id, body.get("invoice_id"), operator)


@router.post("/deposits/{deposit_id}/ask-agent")
def ask_agent(request: Request, deposit_id: str, operator: str = Depends(require_operator)) -> dict[str, Any]:
    ctx = ctx_of(request)
    with ctx.conn() as conn:
        qs = [q for q in pending_agent_questions(conn) if q["deposit_id"] == deposit_id]
    if not qs:
        raise HTTPException(409, "deposit is not awaiting a payer agent answer")
    try:
        _q, answer, transport, problem = ask_agents(ctx, qs[:1], simulated=explain_payments)[0]
    except SimulatedAgentFailed as exc:
        log.error("ask-agent %s: %s", deposit_id, exc)
        raise HTTPException(503, "Ledgerline's simulated payer agent could not answer because of a problem on this server, not the payer's. "
                                 "Nothing was recorded and the payment stays waiting.") from exc
    if answer is None:
        raise HTTPException(502, f"could not ask the customer's own agent: {problem}. The payment stays waiting.")
    with ctx.conn() as conn, db.transaction(conn):
        r = record_agent_answer(conn, ctx, deposit_id, qs[0]["customer_id"], answer, transport)
    payouts.auto_execute_ready(ctx, operator)
    return r


class RemittanceBody(BaseModel):
    text: str | None = Field(None, max_length=5000)
    # Base64 PDF remittance advice (at most 3 MB decoded), sent to Claude as a document.
    pdf_base64: str | None = Field(None, max_length=4_300_000)


@router.post("/deposits/{deposit_id}/read-remittance")
def read_remittance(request: Request, deposit_id: str, body: RemittanceBody | None = None,
                    operator: str = Depends(require_operator)) -> dict[str, Any]:
    import base64
    import binascii

    pdf = None
    if body and body.pdf_base64:
        if body.text:
            raise HTTPException(422, "send either text or a PDF, not both")
        try:
            pdf = base64.b64decode(body.pdf_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(422, "pdf_base64 is not valid base64") from exc
    try:
        return claude_reader.read_remittance(ctx_of(request), deposit_id, operator, body.text if body else None,
                                             control=request.app.state.control, pdf=pdf)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/deposits/{deposit_id}/plans/{version}/replay", dependencies=read)
def replay_decision(request: Request, deposit_id: str, version: int) -> dict[str, Any]:
    """Run the same rules again on the inputs stored with this plan and compare. Changes nothing."""
    from ..replay import ReplayError, replay_plan

    try:
        return replay_plan(ctx_of(request), deposit_id, version)
    except ReplayError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/deposits/{deposit_id}/explanation", dependencies=read)
def get_explanation(request: Request, deposit_id: str) -> dict[str, Any]:
    """The cached "why this plan" for the current plan version, if one was written. Advice only."""
    from .. import explain

    return {"explanation": explain.cached(ctx_of(request), deposit_id)}


@router.post("/deposits/{deposit_id}/explanation")
def write_explanation(request: Request, deposit_id: str, operator: str = Depends(require_operator)) -> dict[str, Any]:
    from .. import explain

    try:
        return {"explanation": explain.explain(ctx_of(request), deposit_id, control=request.app.state.control)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/deposits/{deposit_id}/resolve")
def resolve(request: Request, deposit_id: str, body: dict[str, Any], operator: str = Depends(require_operator)) -> dict[str, Any]:
    return workspace.resolve_deposit(ctx_of(request), deposit_id, body, operator)


@router.post("/payments")
def record_payment(request: Request, body: dict[str, Any], background: BackgroundTasks, operator: str = Depends(require_operator)) -> dict[str, Any]:
    result = workspace.record_manual_payment(ctx_of(request), body, operator)
    background.add_task(agent_loop.on_arrival, ctx_of(request))
    return result


# Typed request bodies: a field of the wrong JSON type is refused with 422 before anything reaches the database
# or the key decoder. Fields are optional here so a missing value still gets the domain's own message (workspace.py),
# and only fields the client actually sent are passed on (exclude_unset keeps PATCH semantics).
class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore")

    def fields(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class CustomerBody(_Body):
    name: StrictStr | None = None
    country: StrictStr | None = None
    payer_names: list[StrictStr] | None = None
    refund_beneficiary: StrictStr | None = None
    agent_public_key: StrictStr | None = None


Amount = StrictStr | StrictInt | StrictFloat


class InvoiceBody(_Body):
    customer_id: StrictStr | None = None
    currency: StrictStr | None = None
    amount: Amount | None = None
    description: StrictStr | None = None
    due_date: StrictStr | None = None


class InvoicePatchBody(_Body):
    description: StrictStr | None = None
    due_date: StrictStr | None = None
    # Never editable; accepted only so the domain can say so (workspace.update_invoice).
    amount: Any = None
    currency: Any = None
    customer_id: Any = None


@router.post("/customers")
def create_customer(request: Request, body: CustomerBody, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return workspace.create_customer(ctx_of(request), body.fields(), operator)


@router.post("/invoices")
def create_invoice(request: Request, body: InvoiceBody, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return workspace.create_invoice(ctx_of(request), body.fields(), operator)


@router.patch("/customers/{customer_id}")
def update_customer(request: Request, customer_id: str, body: CustomerBody, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return workspace.update_customer(ctx_of(request), customer_id, body.fields(), operator)


@router.patch("/invoices/{invoice_id}")
def update_invoice(request: Request, invoice_id: str, body: InvoicePatchBody, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return workspace.update_invoice(ctx_of(request), invoice_id, body.fields(), operator)


@router.post("/invoices/{invoice_id}/adjustments")
def adjust_invoice(request: Request, invoice_id: str, body: dict[str, Any], operator: str = Depends(require_operator)) -> dict[str, Any]:
    return workspace.adjust_invoice(ctx_of(request), invoice_id, body, operator)


class CsvBody(BaseModel):
    csv: str = Field(max_length=200_000)


@router.post("/payments/import")
def import_payments(request: Request, body: CsvBody, background: BackgroundTasks, operator: str = Depends(require_operator)) -> dict[str, Any]:
    result = workspace.import_payments_csv(ctx_of(request), body.csv, operator)
    background.add_task(agent_loop.on_arrival, ctx_of(request))
    return result


class PayerAgentBody(BaseModel):
    url: StrictStr = Field(max_length=300)
    public_key: StrictStr = Field(max_length=100)


@router.get("/agents/outside-proof")
def outside_agent_proof(request: Request, owner: str = Depends(require_owner)) -> Response:
    """Owner only: every exchange with a customer's own agent over the network, as recorded in the audit log, ready to
    commit as evidence (docs/evidence/outside-agent-run.json). Read only."""
    ctx = ctx_of(request)
    with ctx.conn() as conn:
        rows = db.rows(conn, "SELECT id, at, entity_id, detail FROM audit_events WHERE action = 'agent.outside_answer' ORDER BY id")
    body = {
        "what": "Answers from a payer agent running outside this server, each checked three ways before any plan changed",
        "organization": (ctx.org or {}).get("name"),
        "generated_at": iso(ctx.clock.now()),
        "runs": [{"audit_event": r["id"], "at": r["at"], "deposit_id": r["entity_id"], **json.loads(r["detail"])} for r in rows],
    }
    return Response(json.dumps(body, indent=2), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="outside-agent-run.json"'})


@router.put("/customers/{customer_id}/payer-agent")
def set_payer_agent(request: Request, customer_id: str, body: PayerAgentBody, owner: str = Depends(require_owner)) -> dict[str, Any]:
    """Owner only: ask this customer's own agent at this URL; its answers must be signed by this public key."""
    return workspace.set_payer_agent(ctx_of(request), customer_id, body.model_dump(), owner)


@router.delete("/customers/{customer_id}/payer-agent")
def clear_payer_agent(request: Request, customer_id: str, owner: str = Depends(require_owner)) -> dict[str, Any]:
    return workspace.clear_payer_agent(ctx_of(request), customer_id, owner)


@router.post("/customers/import")
def import_customers(request: Request, body: CsvBody, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return workspace.import_customers_csv(ctx_of(request), body.csv, operator)


@router.post("/invoices/import")
def import_invoices(request: Request, body: CsvBody, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return workspace.import_invoices_csv(ctx_of(request), body.csv, operator)


@router.post("/treasury/obligations/import")
def import_bills(request: Request, body: CsvBody, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return workspace.import_bills_csv(ctx_of(request), body.csv, operator)


@router.post("/treasury/obligations")
def create_obligation(request: Request, body: dict[str, Any], operator: str = Depends(require_operator)) -> dict[str, Any]:
    return workspace.create_obligation(ctx_of(request), body, operator)


@router.post("/treasury/opening-balance")
def opening_balance(request: Request, body: dict[str, Any], owner: str = Depends(require_owner)) -> dict[str, Any]:
    return workspace.set_opening_balance(ctx_of(request), body, owner)


class ReturnBody(BaseModel):
    note: str = Field("", max_length=200)


@router.post("/deposits/{deposit_id}/return-to-sender")
def return_to_sender(request: Request, deposit_id: str, operator: str = Depends(require_operator), body: ReturnBody | None = None) -> dict[str, Any]:
    return _loads(payouts.operator_return_to_sender(ctx_of(request), deposit_id, operator, note=body.note if body else None), "scope")


@router.get("/invoices", dependencies=read)
def list_invoices(request: Request, response: Response, q: str | None = Query(None, max_length=80),
                  status: str | None = Query(None, pattern="^(outstanding|open|scheduled|paid|void)$"),
                  customer_id: str | None = None, limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0)) -> list[dict[str, Any]]:
    ctx = ctx_of(request)
    from ..reconcile import invoice_views

    with ctx.conn() as conn:
        views = invoice_views(conn)
        rows = db.rows(conn, "SELECT i.*, c.name AS customer_name FROM invoices i JOIN customers c ON c.id = i.customer_id ORDER BY i.id DESC")
        if q:
            ql = q.lower()
            rows = [r for r in rows if ql in r["id"].lower() or ql in r["customer_name"].lower() or ql in r["description"].lower()]
        if customer_id:
            rows = [r for r in rows if r["customer_id"] == customer_id]
        if status:
            def keep(r):
                v = views[r["id"]]
                if status == "outstanding":
                    return v.status == "open" and v.remaining_minor > 0
                if status == "paid":
                    return v.status in ("open", "paid") and v.remaining_minor == 0
                return v.status == status
            rows = [r for r in rows if keep(r)]
        _page(response, len(rows))
        out = []
        for inv in rows[offset:offset + limit]:
            v = views[inv["id"]]
            out.append({**inv, "remaining_minor": v.remaining_minor, "effective_amount_minor": v.amount_minor,
                        "effective_status": v.status,
                        "adjustments": db.rows(conn, "SELECT * FROM invoice_adjustments WHERE invoice_id = ? ORDER BY created_at", (inv["id"],)),
                        "allocated_minor": conn.execute("SELECT COALESCE(SUM(amount_minor),0) FROM allocations WHERE invoice_id=?", (inv["id"],)).fetchone()[0],
                        "written_off_minor": conn.execute("SELECT COALESCE(SUM(amount_minor),0) FROM writeoffs WHERE invoice_id=?", (inv["id"],)).fetchone()[0],
                        "payment_links": db.rows(conn, "SELECT * FROM payment_links WHERE invoice_id = ?", (inv["id"],))})
        return out


@router.get("/invoices/{invoice_id}", dependencies=read)
def get_invoice(request: Request, invoice_id: str) -> dict[str, Any]:
    ctx = ctx_of(request)
    from ..reconcile import invoice_views

    with ctx.conn() as conn:
        inv = db.row(conn, "SELECT i.*, c.name AS customer_name FROM invoices i JOIN customers c ON c.id = i.customer_id WHERE i.id = ?", (invoice_id,))
        if inv is None:
            raise HTTPException(404, "unknown invoice")
        v = invoice_views(conn)[invoice_id]
        return {**inv, "remaining_minor": v.remaining_minor, "effective_amount_minor": v.amount_minor, "effective_status": v.status,
                "allocations": db.rows(conn, "SELECT a.*, d.payer_name, d.received_at FROM allocations a JOIN deposits d ON d.id = a.deposit_id WHERE a.invoice_id = ? ORDER BY a.created_at", (invoice_id,)),
                "writeoffs": db.rows(conn, "SELECT * FROM writeoffs WHERE invoice_id = ?", (invoice_id,)),
                "adjustments": db.rows(conn, "SELECT * FROM invoice_adjustments WHERE invoice_id = ? ORDER BY created_at", (invoice_id,)),
                "payment_links": db.rows(conn, "SELECT * FROM payment_links WHERE invoice_id = ?", (invoice_id,)),
                "audit": [_loads(a, "detail") for a in db.rows(conn, "SELECT * FROM audit_events WHERE entity_id = ? ORDER BY id", (invoice_id,))]}


@router.get("/customers", dependencies=read)
def list_customers(request: Request, response: Response, q: str | None = Query(None, max_length=80)) -> list[dict[str, Any]]:
    ctx = ctx_of(request)
    with ctx.conn() as conn:
        out = []
        rows = db.rows(conn, "SELECT * FROM customers ORDER BY name")
        if q:
            ql = q.lower()
            rows = [c for c in rows if ql in c["name"].lower() or ql in c["id"].lower() or ql in c["payer_names"].lower()]
        _page(response, len(rows))
        for c in rows:
            c["payer_names"] = json.loads(c["payer_names"])
            c["credits"] = db.rows(conn, "SELECT * FROM credits WHERE customer_id = ?", (c["id"],))
            out.append(c)
        return out


# --------------------------------------------------------------------------- evidence
@router.get("/evidence", dependencies=read)
def evidence_timeline(request: Request) -> list[dict[str, Any]]:
    ctx = ctx_of(request)
    with ctx.conn() as conn:
        out = []
        for d in db.rows(conn, "SELECT * FROM deposits WHERE id IN (SELECT deposit_id FROM evidence) OR id IN (SELECT deposit_id FROM plans GROUP BY deposit_id HAVING COUNT(*) > 1) ORDER BY received_at"):
            out.append({
                "deposit": d,
                "plans": [_loads(p, "actions") for p in db.rows(conn, "SELECT * FROM plans WHERE deposit_id = ? ORDER BY version", (d["id"],))],
                "evidence": [_loads(e, "checks", "envelope") for e in db.rows(conn, "SELECT * FROM evidence WHERE deposit_id = ? ORDER BY version", (d["id"],))],
            })
        return out


# --------------------------------------------------------------------------- approvals & operations
@router.get("/approvals", dependencies=read)
def list_approvals(request: Request) -> list[dict[str, Any]]:
    ctx = ctx_of(request)
    with ctx.conn() as conn:
        out = []
        for a in db.rows(conn, "SELECT * FROM approvals ORDER BY created_at DESC"):
            a = _loads(a, "scope")
            ev = db.row(conn, "SELECT id, verdict, reason, checks, source FROM evidence WHERE id = ?", (a["scope"].get("evidence_id"),)) if a["scope"].get("evidence_id") else None
            a["evidence"] = _loads(ev, "checks") if ev else None
            a["operation"] = db.row(conn, "SELECT * FROM operations WHERE approval_id = ?", (a["id"],))
            a["sender_must_differ"] = payouts.sender_must_differ(a)
            out.append(a)
        return out


class Decision(BaseModel):
    scope_hash: str = Field(min_length=64, max_length=64)


@router.post("/approvals/{approval_id}/approve")
def approve(request: Request, approval_id: str, body: Decision, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return _loads(payouts.decide(ctx_of(request), approval_id, approve=True, actor=operator, seen_scope_hash=body.scope_hash), "scope")


@router.post("/approvals/{approval_id}/reject")
def reject(request: Request, approval_id: str, body: Decision, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return _loads(payouts.decide(ctx_of(request), approval_id, approve=False, actor=operator, seen_scope_hash=body.scope_hash), "scope")


class RecordedRefundBody(BaseModel):
    paid_on: str = Field(max_length=10)
    reference: str = Field(max_length=60)


@router.post("/approvals/{approval_id}/record-external")
def record_external(request: Request, approval_id: str, body: RecordedRefundBody, operator: str = Depends(require_operator)) -> dict[str, Any]:
    """No bank connected: record an approved refund that was made in the company's own bank."""
    return payouts.record_external_refund(ctx_of(request), approval_id, operator, body.paid_on, body.reference)


@router.post("/approvals/{approval_id}/execute")
def execute(request: Request, approval_id: str, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return payouts.execute_refund(ctx_of(request), approval_id, operator)


@router.post("/approvals/{approval_id}/send-as-practice-teammate")
def send_as_practice_teammate(request: Request, approval_id: str, operator: str = Depends(require_operator)) -> dict[str, Any]:
    """Practice companies only (403 elsewhere): a labelled stand-in sends a refund a member approved."""
    return payouts.send_as_practice_teammate(ctx_of(request), approval_id, operator)


@router.get("/operations", dependencies=read)
def list_operations(request: Request) -> list[dict[str, Any]]:
    ctx = ctx_of(request)
    with ctx.conn() as conn:
        out = []
        for o in db.rows(conn, "SELECT * FROM operations ORDER BY created_at DESC"):
            o = _loads(o, "detail")
            o["events"] = db.rows(conn, "SELECT * FROM operation_events WHERE operation_id = ? ORDER BY id", (o["id"],))
            out.append(o)
        return out


class SimStatus(BaseModel):
    next_status: Literal["SENT", "PAID", "FAILED"]


@router.post("/operations/{op_id}/sync")
def sync(request: Request, op_id: str, operator: str = Depends(require_operator)) -> dict[str, Any]:
    ctx = ctx_of(request)
    with ctx.conn() as conn:
        op = db.row(conn, "SELECT kind FROM operations WHERE id = ?", (op_id,))
    if op is None:
        raise HTTPException(404, "unknown operation")
    if op["kind"] == "fx_conversion":
        return treasury.sync_conversion(ctx, op_id)
    return payouts.sync_operation(ctx, op_id)


@router.post("/operations/{op_id}/simulate-bank")
def simulate_bank(request: Request, op_id: str, body: SimStatus, operator: str = Depends(require_operator)) -> dict[str, Any]:
    ctx = ctx_of(request)
    if ctx.provider.name == 'airwallex_sandbox':
        if request.state.principal.role != 'owner' or not (ctx.org.get('own_airwallex') or request.app.state.settings.sandbox_allowed(ctx.org['id'])):
            raise HTTPException(403, 'sandbox transfer simulation is restricted to the owner of a connected account')
    return payouts.simulate_bank_status(ctx, op_id, body.next_status)


@router.post("/operations/{op_id}/cancel")
def cancel(request: Request, op_id: str, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return payouts.cancel_pending(ctx_of(request), op_id, operator)


# --------------------------------------------------------------------------- treasury
@router.get("/treasury", dependencies=read)
def treasury_view(request: Request) -> dict[str, Any]:
    ctx = ctx_of(request)
    with ctx.conn() as conn:
        pos = treasury.wallet_position(conn, ctx)
        obligations = db.rows(conn, "SELECT * FROM obligations ORDER BY due_at")
        plans = {o["id"]: treasury.plan_for_obligation(conn, ctx, o["id"]) for o in obligations}
        quotes = [treasury.quote_preview(conn, ctx, q["id"]) for q in db.rows(conn, "SELECT id FROM fx_quotes ORDER BY created_at DESC LIMIT 10")]
        conversions = db.rows(conn, "SELECT * FROM operations WHERE kind = 'fx_conversion' ORDER BY created_at DESC")
    return {"wallets": list(pos.values()), "obligations": obligations, "plans": plans, "quotes": quotes,
            "conversions": conversions, "rates": [{"sell": a, "buy": b, "rate": str(r)} for (a, b), r in DEMO_RATES.items()],
            "rate_source": ctx.provider.label}


_RATE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


@router.get("/treasury/rates", dependencies=read)
def treasury_rates(request: Request) -> dict[str, Any]:
    """Indicative rates for display. Sandbox organizations get Airwallex GET /fx/rates/current (cached 60 s);
    local workspaces get the fixed synthetic rates, labelled as such. Conversions always book a quote."""
    import time

    ctx = ctx_of(request)
    if ctx.provider.name != "airwallex_sandbox":
        return {"source": "synthetic", "label": "Fixed synthetic rates (local simulated bank)", "as_of": None,
                "rates": [{"sell": a, "buy": b, "rate": str(r)} for (a, b), r in DEMO_RATES.items()]}
    key = ctx.org["id"] if ctx.org else "default"
    hit = _RATE_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < 60:
        return hit[1]
    rates = [ctx.provider.current_rate(a, b) for (a, b) in DEMO_RATES]
    out = {"source": "airwallex_sandbox", "label": "Airwallex sandbox GET /fx/rates/current (indicative client rate)",
           "as_of": iso(ctx.clock.now()), "rates": rates}
    _RATE_CACHE[key] = (time.monotonic(), out)
    return out


@router.get("/treasury/decisions", dependencies=read)
def treasury_decisions(request: Request) -> dict[str, Any]:
    """The ranked plan, refreshed from the current position. Only decisions that changed get a new version."""
    return treasury.refresh_decisions(ctx_of(request), "position review")


@router.post("/treasury/practice-squeeze")
def practice_squeeze(request: Request, operator: str = Depends(require_operator)) -> dict[str, Any]:
    ctx = ctx_of(request)
    _sample_only(ctx)
    return treasury.add_practice_squeeze(ctx, operator)


@router.post("/treasury/obligations/{obligation_id}/defer")
def defer_bill(request: Request, obligation_id: str, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return treasury.apply_deferral(ctx_of(request), obligation_id, operator)


class PayBillBody(BaseModel):
    destination: str = Field(max_length=120)


class PaymentDecision(BaseModel):
    scope_hash: str = Field(max_length=128)


class PaymentSim(BaseModel):
    next_status: Literal["SENT", "PAID", "FAILED"]


@router.get("/treasury/bill-payments", dependencies=read)
def list_bill_payments(request: Request) -> list[dict[str, Any]]:
    return bill_payments.list_payments(ctx_of(request))


@router.post("/treasury/obligations/{obligation_id}/pay")
def propose_bill_payment(request: Request, obligation_id: str, body: PayBillBody, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return bill_payments.propose(ctx_of(request), obligation_id, body.destination, operator)


@router.post("/treasury/bill-payments/{payment_id}/approve")
def approve_bill_payment(request: Request, payment_id: str, body: PaymentDecision, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return bill_payments.decide(ctx_of(request), payment_id, approve=True, actor=operator, seen_scope_hash=body.scope_hash)


@router.post("/treasury/bill-payments/{payment_id}/reject")
def reject_bill_payment(request: Request, payment_id: str, body: PaymentDecision, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return bill_payments.decide(ctx_of(request), payment_id, approve=False, actor=operator, seen_scope_hash=body.scope_hash)


@router.post("/treasury/bill-payments/{payment_id}/execute")
def execute_bill_payment(request: Request, payment_id: str, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return bill_payments.execute(ctx_of(request), payment_id, operator)


@router.post("/treasury/bill-payments/{payment_id}/sync")
def sync_bill_payment(request: Request, payment_id: str, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return bill_payments.sync(ctx_of(request), payment_id, operator)


@router.post("/treasury/bill-payments/{payment_id}/simulate-bank")
def simulate_bill_payment(request: Request, payment_id: str, body: PaymentSim, operator: str = Depends(require_operator)) -> dict[str, Any]:
    ctx = ctx_of(request)
    if ctx.provider.name == "airwallex_sandbox" and request.state.principal.role != "owner":
        raise HTTPException(403, "only an owner can simulate a transfer status on a connected account")
    return bill_payments.simulate(ctx, payment_id, body.next_status, operator)


@router.post("/treasury/obligations/{obligation_id}/mark-paid")
def bill_paid(request: Request, obligation_id: str, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return treasury.mark_bill_paid(ctx_of(request), obligation_id, operator)


@router.post("/treasury/obligations/{obligation_id}/quote")
def quote(request: Request, obligation_id: str, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return treasury.create_quote(ctx_of(request), obligation_id, operator)


@router.post("/treasury/quotes/{quote_id}/execute")
def convert(request: Request, quote_id: str, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return treasury.execute_conversion(ctx_of(request), quote_id, operator)


# --------------------------------------------------------------------------- ledger & audit
@router.get("/ledger", dependencies=read)
def ledger_view(request: Request) -> dict[str, Any]:
    ctx = ctx_of(request)
    with ctx.conn() as conn:
        return {"conservation": ledger.conservation(conn), "per_deposit": ledger.per_deposit_check(conn),
                "journal": ledger.journal(conn, 300)}


@router.get("/audit", dependencies=read)
def audit_view(request: Request, response: Response, limit: int = Query(300, ge=1, le=2000), offset: int = Query(0, ge=0),
               q: str | None = Query(None, max_length=80)) -> list[dict[str, Any]]:
    ctx = ctx_of(request)
    sql, params = "SELECT * FROM audit_events", []
    if q:
        sql += " WHERE action LIKE ? OR entity_id LIKE ? OR actor LIKE ? OR COALESCE(operation_id,'') LIKE ?"
        params = [f"%{q}%"] * 4
    with ctx.conn() as conn:
        _page(response, conn.execute(sql.replace("SELECT *", "SELECT COUNT(*)", 1), params).fetchone()[0])
        return [_loads(a, "detail") for a in db.rows(conn, sql + " ORDER BY id DESC LIMIT ? OFFSET ?", (*params, limit, offset))]


@router.get("/audit/verify", dependencies=read)
def audit_verify(request: Request) -> dict[str, Any]:
    with ctx_of(request).conn() as conn:
        return audit.verify_chain(conn)


@router.get("/practice/tamper", dependencies=read)
def practice_tamper_status(request: Request) -> dict[str, Any]:
    from .. import tamper_demo

    return tamper_demo.status(ctx_of(request))


@router.post("/practice/tamper")
def practice_tamper(request: Request, operator: str = Depends(require_operator)) -> dict[str, Any]:
    """Practice companies only: change one audit event directly and show where the chain catches it."""
    from .. import tamper_demo

    try:
        return tamper_demo.tamper(ctx_of(request))
    except tamper_demo.TamperError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/practice/tamper/restore")
def practice_tamper_restore(request: Request, operator: str = Depends(require_operator)) -> dict[str, Any]:
    from .. import tamper_demo

    return tamper_demo.restore(ctx_of(request), operator)


class EarlyPayBody(BaseModel):
    discount_bps: StrictInt


@router.get("/treasury/links-last-checked", dependencies=read)
def links_last_checked(request: Request) -> dict[str, Any]:
    with ctx_of(request).conn() as conn:
        return {"at": db.get_setting(conn, "links_last_checked", None)}


@router.get("/treasury/early-pay/options", dependencies=read)
def early_pay_options(request: Request) -> dict[str, Any]:
    return early_pay.options(ctx_of(request))


@router.get("/treasury/early-pay", dependencies=read)
def early_pay_offers(request: Request) -> list[dict[str, Any]]:
    return early_pay.list_offers(ctx_of(request))


@router.post("/invoices/{invoice_id}/early-pay")
def early_pay_offer(request: Request, invoice_id: str, body: EarlyPayBody, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return early_pay.create_offer(ctx_of(request), invoice_id, body.discount_bps, operator)


@router.post("/treasury/early-pay/{offer_id}/check")
def early_pay_check(request: Request, offer_id: str, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return early_pay.check(ctx_of(request), offer_id, operator)


@router.post("/treasury/early-pay/{offer_id}/practice-paid")
def early_pay_practice(request: Request, offer_id: str, operator: str = Depends(require_operator)) -> dict[str, Any]:
    return early_pay.practice_paid(ctx_of(request), offer_id, operator)


@router.get("/treasury/plan-runs", dependencies=read)
def plan_runs(request: Request) -> list[dict[str, Any]]:
    return treasury.list_plan_runs(ctx_of(request))


@router.get("/treasury/plan-runs/{run_id}/replay", dependencies=read)
def plan_run_replay(request: Request, run_id: str) -> dict[str, Any]:
    return treasury.replay_plan_run(ctx_of(request), run_id)


@router.get("/audit/export", dependencies=read)
def audit_export(request: Request) -> Response:
    ctx = ctx_of(request)
    with ctx.conn() as conn:
        payload = {
            "exported_at": iso(ctx.clock.now()),
            "organization": ctx.org,
            "exported_by": request.state.principal.actor,
            "mode": {"bank": ctx.provider.label, "claude": "claude_api" if ctx.settings.claude_configured else "deterministic_fixture"},
            "synthetic_data_only": bool(ctx.org and ctx.org.get("kind") == "sample"),
            "deposits": db.rows(conn, "SELECT * FROM deposits ORDER BY id"),
            "plans": [_loads(p, "actions") for p in db.rows(conn, "SELECT * FROM plans ORDER BY deposit_id, version")],
            "evidence": [_loads(e, "checks", "envelope") for e in db.rows(conn, "SELECT * FROM evidence ORDER BY deposit_id, version")],
            "approvals": [_loads(a, "scope") for a in db.rows(conn, "SELECT * FROM approvals ORDER BY created_at")],
            "operations": [_loads(o, "detail") for o in db.rows(conn, "SELECT * FROM operations ORDER BY created_at")],
            "operation_events": db.rows(conn, "SELECT * FROM operation_events ORDER BY id"),
            "bill_payments": db.rows(conn, "SELECT * FROM bill_payments ORDER BY created_at"),
            "early_pay_offers": db.rows(conn, "SELECT * FROM early_pay_offers ORDER BY created_at"),
            "audit_chain": audit.verify_chain(conn),
            "plan_runs": [_loads(r, "inputs", "output") for r in db.rows(conn, "SELECT * FROM plan_runs ORDER BY at")],
            "conservation": ledger.conservation(conn),
            "audit_events": [_loads(a, "detail") for a in db.rows(conn, "SELECT * FROM audit_events ORDER BY id")],
            "scorecard": demo.scorecard(ctx),
        }
    body = json.dumps(payload, indent=2, default=str)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="ledgerline-evidence-export.json"', "Cache-Control": "no-store"})


@router.get("/export/csv", dependencies=read)
def export_csv(request: Request) -> Response:
    """The company's records as CSV files in one zip (customers, invoices, payments, plans, approvals, transfers, bills,
    the audit log). Nothing secret is included."""
    from .. import export_csv as export

    body, filename = export.build(ctx_of(request), request.state.principal.actor)
    return Response(body, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


# --------------------------------------------------------------------------- settings
class PauseBody(BaseModel):
    paused: bool
    reason: str = Field("", max_length=200)


@router.post("/settings/pause")
def set_pause(request: Request, body: PauseBody, operator: str = Depends(require_operator)) -> dict[str, Any]:
    """Any operator can stop money-out in an emergency; only an owner can resume it."""
    ctx = ctx_of(request)
    if not body.paused and request.state.principal.role != "owner":
        raise HTTPException(403, "only an owner can resume money-out")
    from .. import audit

    with ctx.conn() as conn, db.transaction(conn):
        now = iso(ctx.clock.now())
        db.set_setting(conn, "money_out_paused", body.paused)
        db.set_setting(conn, "money_out_pause_info", {"by": operator, "at": now, "reason": body.reason})
        audit.record(conn, now, operator, "money_out.paused" if body.paused else "money_out.resumed", "settings", "pause",
                     {"reason": body.reason})
    return {"paused": body.paused}


@router.put("/settings/policy")
def put_policy(request: Request, body: dict[str, Any], operator: str = Depends(require_owner)) -> dict[str, Any]:
    ctx = ctx_of(request)
    from .. import audit

    with ctx.conn() as conn, db.transaction(conn):
        before = ctx.policy(conn)
        policy = validate_policy({**before, **body})  # a field the form does not show keeps its value
        changed = {k: {"from": before[k], "to": policy[k]} for k in policy if before.get(k) != policy[k]}
        db.set_setting(conn, "policy", policy)
        audit.record(conn, iso(ctx.clock.now()), operator, "policy.updated", "settings", "policy", {"changed": changed})
    return policy


# --------------------------------------------------------------------------- demo
def _sample_only(ctx: AppContext) -> None:
    if not ctx.org or ctx.org.get("kind") != "sample":
        raise HTTPException(409, "the walkthrough runs only in sample organizations; create one from the organization menu")


@router.post("/demo/practice-unclear-payment")
def practice_unclear_payment(request: Request, operator: str = Depends(require_operator)) -> dict[str, Any]:
    """Practice companies only: a new payment with no reference arrives, and the agent handles it with no further click."""
    from ..reconcile import ingest_deposit

    ctx = ctx_of(request)
    _sample_only(ctx)
    with ctx.conn() as conn, db.transaction(conn):
        deposit_id, created = ingest_deposit(conn, ctx, {"provider_ref": "PRACTICE-AUTO-1", "currency": "USD", "amount_minor": 120_000, "payer_name": "DUNMORE ANALYTICS LLC",
                                                         "reference": "", "received_at": iso(ctx.clock.now())}, source="practice_payment")
        if created:
            audit.record(conn, iso(ctx.clock.now()), operator, "practice.unclear_payment_added", "deposit", deposit_id, {})
    if created:
        agent_loop.ask_pending(ctx, only=deposit_id)
    return {"deposit_id": deposit_id, "created": created}


@router.post("/demo/practice-wrong-currency")
def practice_wrong_currency(request: Request, operator: str = Depends(require_operator)) -> dict[str, Any]:
    """Practice companies only: a USD payment against a EUR invoice, added on request so the six reference payments stay as they are."""
    from ..reconcile import ingest_deposit

    ctx = ctx_of(request)
    _sample_only(ctx)
    with ctx.conn() as conn, db.transaction(conn):
        deposit_id, created = ingest_deposit(conn, ctx, {"provider_ref": "PRACTICE-FX-1", "currency": "USD", "amount_minor": 300_000, "payer_name": "BRIGHTWAVE GMBH",
                                                         "reference": "INV-2253", "received_at": iso(ctx.clock.now())}, source="practice_payment")
        if created:
            audit.record(conn, iso(ctx.clock.now()), operator, "practice.wrong_currency_added", "deposit", deposit_id, {})
    return {"deposit_id": deposit_id, "created": created}


@router.get("/demo", dependencies=read)
def demo_state(request: Request) -> dict[str, Any]:
    ctx = ctx_of(request)
    if not ctx.org or ctx.org.get("kind") != "sample":
        return {"available": False, "steps": [], "next": None, "blocked": None, "provider": ctx.provider.label}
    return {"available": True, **demo.state(ctx)}


class StepBody(BaseModel):
    step: str = Field(max_length=32)


@router.post("/demo/step")
def demo_step(request: Request, body: StepBody, operator: str = Depends(require_operator)) -> dict[str, Any]:
    ctx = ctx_of(request)
    _sample_only(ctx)
    if body.step == "seed" and request.state.principal.role != "owner":
        raise HTTPException(403, "only an owner can reset the sample organization")
    return demo.run_step(ctx, body.step, operator)


@router.get("/scorecard", dependencies=read)
def scorecard(request: Request) -> dict[str, Any]:
    return demo.scorecard(ctx_of(request))


# --------------------------------------------------------------------------- webhooks
@router.post("/webhooks/airwallex/{org_id}")
async def airwallex_webhook(request: Request, org_id: str, background: BackgroundTasks) -> dict[str, Any]:
    """Each organization has its own webhook URL and secret. HMAC is the only credential."""
    try:
        ctx = request.app.state.orgs.get(org_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, "unknown webhook endpoint") from exc
    raw = await request.body()
    if len(raw) > 64_000:
        raise HTTPException(413, "payload too large")
    secret = ctx.settings.airwallex_webhook_secret or ctx.settings.webhook_secret
    source = "airwallex_sandbox_webhook" if ctx.settings.airwallex_webhook_secret else "local_simulated_webhook"
    from starlette.concurrency import run_in_threadpool

    result = await run_in_threadpool(
        webhooks.handle, ctx, raw_body=raw, timestamp_ms=request.headers.get("x-timestamp"),
        signature=request.headers.get("x-signature"), secret=secret, source=source,
    )
    # New cash may change a bill decision. Done after the response, so a rate lookup cannot delay the receipt.
    background.add_task(treasury.refresh_decisions, ctx, "deposit received")
    background.add_task(agent_loop.on_arrival, ctx)
    return result
