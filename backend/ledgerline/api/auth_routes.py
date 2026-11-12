"""Account, organization and team endpoints (control plane)."""
from __future__ import annotations

import json as _json
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..control import AuthError
from .security import Principal, clear_session_cookie, client_ip, require_role, require_session, set_session_cookie

router = APIRouter()


def _control(request: Request):
    return request.app.state.control


def _ip(request: Request) -> str:
    return client_ip(request)


def _ua(request: Request) -> str:
    return request.headers.get("user-agent", "")[:200]


def _me(request: Request, token: str) -> dict[str, Any]:
    info = _control(request).authenticate(token)
    if info is None:
        raise HTTPException(401, "sign in required")
    orgs = _control(request).user_orgs(info.user_id)
    active = next((o for o in orgs if o["id"] == info.org_id), None)
    return {
        "user": {"id": info.user_id, "email": info.email, "name": info.name},
        "csrf_token": info.csrf_token,
        "session_expires_at": info.expires_at,
        "organization": active,
        "role": info.role,
        "organizations": orgs,
        "signup_enabled": request.app.state.settings.allow_signup,
        "judge_demo": _control(request).judge_demo_person(info.user_id, info.org_id),
    }


def _check_origin(request: Request) -> None:
    """Unauthenticated POSTs (signup, login, invitation) still refuse foreign browser origins."""
    origin = request.headers.get("origin")
    if origin is not None and origin not in request.app.state.settings.allowed_origins:
        raise HTTPException(403, f"origin {origin} not allowed")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "cross-site request refused")


class SignupBody(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(max_length=80)
    password: str = Field(max_length=256)
    organization_name: str = Field(max_length=80)
    start_with: Literal["empty", "sample"] = "empty"


@router.post("/auth/signup")
def signup(request: Request, response: Response, body: SignupBody) -> dict[str, Any]:
    _check_origin(request)
    if not request.app.state.settings.allow_signup:
        raise HTTPException(403, "self-service sign-up is disabled on this server; ask an owner for an invitation")
    kind = "sample" if body.start_with == "sample" else "workspace"
    token, org_id = _control(request).signup(email=body.email, name=body.name, password=body.password,
                                             org_name=body.organization_name, kind=kind, user_agent=_ua(request), ip=_ip(request))
    request.app.state.orgs.provision(org_id, sample=kind == "sample")
    set_session_cookie(request, response, token)
    return _me(request, token)


class LoginBody(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


@router.post("/auth/judge-demo")
def judge_demo(request: Request, response: Response) -> dict[str, Any]:
    """One click: a practice company of its own, with the reference payments, and two demo people (Judge A, the Owner,
    and Teammate B, an Operator). Simulated bank only; deleted after 48 hours."""
    _check_origin(request)
    s = request.app.state.settings
    if not s.judge_demo:
        raise HTTPException(403, "the one-click judge demo is switched off on this server")
    token, org_id = _control(request).create_judge_demo(ip=_ip(request), user_agent=_ua(request), limits=s.judge_demo_limits)
    request.app.state.orgs.provision(org_id, sample=True)
    set_session_cookie(request, response, token)
    return _me(request, token)


@router.post("/auth/judge-demo/switch")
def judge_demo_switch(request: Request, response: Response) -> dict[str, Any]:
    """Become the other demo person (A or B) of the same demo company, to be the second person in the two-person rule."""
    _, token = require_session(request, mutating=True)
    new = _control(request).switch_judge_demo_person(token, _ua(request))
    set_session_cookie(request, response, new)
    return _me(request, new)


@router.post("/auth/login")
def login(request: Request, response: Response, body: LoginBody) -> dict[str, Any]:
    _check_origin(request)
    token = _control(request).login(email=body.email, password=body.password, ip=_ip(request), user_agent=_ua(request))
    set_session_cookie(request, response, token)
    return _me(request, token)


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict[str, Any]:
    _, token = require_session(request, mutating=True)
    _control(request).logout(token)
    clear_session_cookie(request, response)
    return {"signed_out": True}


@router.get("/auth/session")
def session_probe(request: Request) -> dict[str, Any]:
    """Like /auth/me, but a visitor who is not signed in gets 200 {"signed_in": false}, not a 401 in their console."""
    try:
        _, token = require_session(request, mutating=False)
    except (AuthError, HTTPException):
        return {"signed_in": False}
    return {"signed_in": True, **_me(request, token)}


@router.get("/auth/me")
def me(request: Request) -> dict[str, Any]:
    _, token = require_session(request, mutating=False)
    return _me(request, token)


class SwitchBody(BaseModel):
    organization_id: str = Field(max_length=40)


@router.post("/auth/switch-organization")
def switch_org(request: Request, body: SwitchBody) -> dict[str, Any]:
    _, token = require_session(request, mutating=True)
    _control(request).switch_org(token, body.organization_id)
    return _me(request, token)


class PasswordBody(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class NameBody(BaseModel):
    name: str = Field(max_length=80)


@router.put("/auth/me")
def rename(request: Request, body: NameBody) -> dict[str, Any]:
    info, token = require_session(request, mutating=True)
    _control(request).rename_user(info.user_id, body.name)
    return _me(request, token)


class ResetBody(BaseModel):
    password: str = Field(max_length=256)


@router.get("/auth/reset/{token}")
def reset_info(request: Request, token: str) -> dict[str, Any]:
    return _control(request).reset_info(token)


@router.post("/auth/reset/{token}")
def reset_password(request: Request, response: Response, token: str, body: ResetBody) -> dict[str, Any]:
    """Set a new password with an Owner's reset link. Every other session of that account is signed out."""
    _check_origin(request)
    session_token = _control(request).complete_reset(token, body.password, user_agent=_ua(request))
    set_session_cookie(request, response, session_token)
    return _me(request, session_token)


class ConfirmBody(BaseModel):
    confirm: str = Field(max_length=254)


@router.post("/auth/leave-organization")
def leave_org(request: Request, p: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    _control(request).leave_org(p.session.org_id, p.session.user_id)
    return {"left": True}


@router.post("/auth/delete-account")
def delete_account(request: Request, response: Response, body: ConfirmBody) -> dict[str, Any]:
    info, _ = require_session(request, mutating=True)
    _control(request).delete_account(info.user_id, body.confirm)
    clear_session_cookie(request, response)
    return {"deleted": True}


@router.post("/organization/delete")
def delete_org(request: Request, body: ConfirmBody, p: Principal = Depends(require_role("owner"))) -> dict[str, Any]:
    """Delete this organization and all its data, once nothing is being sent. Practice or real alike; no undo."""
    from .. import db
    from ..clock import iso
    from ..tenancy import delete_org_storage

    # Pause money-out in the same transaction as the check: a send that starts after this sees the pause and stops,
    # and one that started before has already written the transfer this check counts.
    with p.ctx.conn() as conn, db.transaction(conn):
        was = (db.get_setting(conn, "money_out_paused", False), db.get_setting(conn, "money_out_pause_info", None))
        db.set_setting(conn, "money_out_paused", True)
        db.set_setting(conn, "money_out_pause_info", {"by": p.session.email, "at": iso(p.ctx.clock.now()), "reason": "organization being deleted"})
        busy = conn.execute("SELECT COUNT(*) FROM operations WHERE status IN ('processing','sent')").fetchone()[0] + \
            conn.execute("SELECT COUNT(*) FROM bill_payments WHERE status IN ('processing','sent')").fetchone()[0]
    if busy:
        with p.ctx.conn() as conn, db.transaction(conn):  # nothing is deleted, so the pause goes back to what it was
            db.set_setting(conn, "money_out_paused", was[0])
            db.set_setting(conn, "money_out_pause_info", was[1])
        raise HTTPException(409, "money is still being sent from this organization; wait until every transfer is paid or failed")
    org_id = p.session.org_id
    gone = _control(request).delete_org(org_id, p.session.email, body.confirm)
    request.app.state.orgs.invalidate(org_id)
    delete_org_storage(request.app.state.settings, org_id)
    return {"deleted": gone}


@router.post("/team/members/{user_id}/reset-link")
def reset_link(request: Request, user_id: str, p: Principal = Depends(require_role("owner"))) -> dict[str, Any]:
    """There is no email from this server, so an Owner hands the member a one-hour link. It is shown once."""
    token, expires = _control(request).issue_reset(p.session.org_id, p.session.user_id, user_id)
    return {"path": f"#/reset?token={token}", "expires_at": expires}


@router.post("/auth/change-password")
def change_password(request: Request, body: PasswordBody) -> dict[str, Any]:
    info, token = require_session(request, mutating=True)
    _control(request).change_password(info.user_id, body.current_password, body.new_password, keep_token=token)
    return {"changed": True, "other_sessions_signed_out": True}


class OrgBody(BaseModel):
    name: str = Field(max_length=80)
    start_with: Literal["empty", "sample"] = "empty"


@router.post("/organizations")
def create_org(request: Request, body: OrgBody) -> dict[str, Any]:
    """Any signed-in user can create another organization and becomes its owner."""
    info, token = require_session(request, mutating=True)
    kind = "sample" if body.start_with == "sample" else "workspace"
    org_id = _control(request).create_org(info.user_id, body.name, kind, ip=_ip(request))
    request.app.state.orgs.provision(org_id, sample=kind == "sample")
    _control(request).switch_org(token, org_id)
    return _me(request, token)


# --------------------------------------------------------------------------- invitations (public lookup + accept)
@router.get("/invitations/{token}")
def invitation(request: Request, token: str) -> dict[str, Any]:
    return _control(request).invitation_info(token)


class AcceptBody(BaseModel):
    name: str = Field("", max_length=80)
    password: str = Field(max_length=256)


@router.post("/invitations/{token}/accept")
def accept(request: Request, response: Response, token: str, body: AcceptBody) -> dict[str, Any]:
    _check_origin(request)
    session_token = _control(request).accept_invitation(token, name=body.name, password=body.password, user_agent=_ua(request), ip=_ip(request))
    set_session_cookie(request, response, session_token)
    return _me(request, session_token)


# --------------------------------------------------------------------------- team (scoped to the active organization)
@router.get("/team")
def team(request: Request, p: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    ctrl = _control(request)
    return {
        "members": ctrl.members(p.session.org_id),
        "invitations": ctrl.invitations(p.session.org_id) if p.role == "owner" else [],
        "you": p.session.user_id,
        "role": p.role,
    }


class InviteBody(BaseModel):
    email: str = Field(max_length=254)
    role: Literal["owner", "operator", "viewer"]


@router.post("/team/invitations")
def invite(request: Request, body: InviteBody, p: Principal = Depends(require_role("owner"))) -> dict[str, Any]:
    token = _control(request).invite(p.session.org_id, p.session.user_id, body.email, body.role)
    # Email delivery is not part of this build: the owner copies the one-time link.
    return {"invite_path": f"/#/invite?token={token}", "expires_in_days": 3, "email": body.email.strip().lower(), "role": body.role}


@router.delete("/team/invitations/{invite_id}")
def revoke_invite(request: Request, invite_id: str, p: Principal = Depends(require_role("owner"))) -> dict[str, Any]:
    _control(request).revoke_invitation(p.session.org_id, p.session.user_id, invite_id)
    return {"revoked": True}


class RoleBody(BaseModel):
    role: Literal["owner", "operator", "viewer"]


@router.put("/team/members/{user_id}")
def set_role(request: Request, user_id: str, body: RoleBody, p: Principal = Depends(require_role("owner"))) -> dict[str, Any]:
    _control(request).set_role(p.session.org_id, p.session.user_id, user_id, body.role)
    return {"user_id": user_id, "role": body.role}


@router.delete("/team/members/{user_id}")
def remove_member(request: Request, user_id: str, p: Principal = Depends(require_role("owner"))) -> dict[str, Any]:
    _control(request).remove_member(p.session.org_id, p.session.user_id, user_id)
    return {"removed": True}


# --------------------------------------------------------------------------- organization settings & integrations
@router.get("/organization")
def org_settings(request: Request, p: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    org = _control(request).org(p.session.org_id)
    s = request.app.state.settings
    return {
        "id": org["id"], "name": org["name"], "kind": org["kind"], "bank_mode": org["bank_mode"],
        "airwallex_global_accounts": _json.loads(org["airwallex_global_accounts"] or "{}"),
        "airwallex_webhook_secret_set": bool(org["airwallex_webhook_secret"]),
        "airwallex_connected": bool(org["airwallex_credentials_enc"]),
        "webhook_path": f"/api/webhooks/airwallex/{org['id']}",
        "server": {"airwallex_credentials_present": s.airwallex_configured or bool(s.sender_socket),
                   "airwallex_keys_held_by": "sending service" if s.sender_socket else "app", "claude_key_present": s.claude_configured,
                   "claude_model": s.claude_model, "sandbox_allowed": s.sandbox_allowed(org["id"]),
                   "claude_daily_limit": s.claude_daily_limit},
        "control_audit": _control(request).control_audit(org["id"], 50) if p.role == "owner" else [],
    }


@router.put("/organization")
def update_org(request: Request, body: dict[str, Any], p: Principal = Depends(require_role("owner"))) -> dict[str, Any]:
    _control(request).update_org_settings(p.session.org_id, p.session.email, body,
                                          sandbox_available=request.app.state.settings.sandbox_allowed(p.session.org_id))
    request.app.state.orgs.invalidate(p.session.org_id)
    return org_settings(request, p)


class ConnectAirwallexBody(BaseModel):
    client_id: str = Field(strict=True, min_length=6, max_length=200)
    api_key: str = Field(strict=True, min_length=6, max_length=500)
    webhook_secret: str = Field(strict=True, min_length=8, max_length=200)


def _no_money_activity(p: Principal) -> None:
    """The ledger of an organization belongs to one bank: switching mid-way would mix two sets of balances."""
    with p.ctx.conn() as conn:
        if conn.execute("SELECT 1 FROM deposits LIMIT 1").fetchone() or conn.execute("SELECT 1 FROM operations LIMIT 1").fetchone() \
                or conn.execute("SELECT 1 FROM wallet_opening LIMIT 1").fetchone():
            raise HTTPException(409, "this organization already has payments or balances on its current bank; create a new organization to connect another account")


@router.post("/integrations/airwallex/connect")
def connect_airwallex(request: Request, body: ConnectAirwallexBody, p: Principal = Depends(require_role("owner"))) -> dict[str, Any]:
    """Check the organization's own sandbox keys against Airwallex first; save them only if they work."""
    if _control(request).is_judge_demo(p.session.org_id):
        raise HTTPException(403, "a judge demo company runs on the simulated bank only; it cannot connect Airwallex keys")
    from ..connections import discover_accounts, seal
    from ..providers.airwallex import AirwallexSandbox
    from ..providers.base import ProviderAmbiguous, ProviderError

    s = request.app.state.settings
    org = _control(request).org(p.session.org_id)
    if org["kind"] == "sample":
        raise HTTPException(409, "a practice company stays on the simulated bank; connect from your own organization")
    if not org["airwallex_credentials_enc"]:
        _no_money_activity(p)
    try:
        readiness = AirwallexSandbox(body.client_id.strip(), body.api_key.strip(), timeout=15).readiness()
    except (ProviderError, ProviderAmbiguous, httpx.HTTPError) as exc:
        # Only the error type: a provider message must not echo anything we sent.
        raise HTTPException(422, f"Airwallex did not accept these sandbox keys ({type(exc).__name__}); nothing was saved") from exc
    accounts = discover_accounts(readiness)
    rotating = bool(org["airwallex_credentials_enc"])
    if rotating and accounts != _json.loads(org["airwallex_global_accounts"] or "{}"):
        # New keys for the same account are fine; a different account would mix two sets of balances in one ledger.
        raise HTTPException(409, "these keys belong to a different account; create a new organization to connect it")
    if s.sender_socket:  # only the sending service holds the key that seals stored credentials
        from ..sender import SenderClient

        sealed = SenderClient(s.sender_socket).call("seal", org["id"], client_id=body.client_id.strip(), api_key=body.api_key.strip())
    else:
        sealed = seal(s, org["id"], body.client_id.strip(), body.api_key.strip())
    _control(request).set_airwallex_connection(org["id"], p.session.email, sealed, accounts, body.webhook_secret.strip())
    request.app.state.orgs.invalidate(org["id"])
    if not rotating:
        from .. import workspace

        workspace.record_connected_opening(request.app.state.orgs.get(org["id"]), readiness["balances"], p.session.email)
    return {"connected": True, "receiving_accounts": accounts, "balances": readiness["balances"],
            "webhook_path": f"/api/webhooks/airwallex/{org['id']}",
            "missing_currencies": sorted({"USD", "EUR", "GBP"} - set(accounts))}


@router.post("/integrations/airwallex/disconnect")
def disconnect_airwallex(request: Request, p: Principal = Depends(require_role("owner"))) -> dict[str, Any]:
    org = _control(request).org(p.session.org_id)
    if not org["airwallex_credentials_enc"]:
        raise HTTPException(409, "this organization has no connected Airwallex account")
    with p.ctx.conn() as conn:
        if conn.execute("SELECT 1 FROM deposits LIMIT 1").fetchone() or conn.execute("SELECT 1 FROM operations LIMIT 1").fetchone():
            raise HTTPException(409, "this organization has payments on this account, so the connection must stay for its records")
    _control(request).set_airwallex_connection(org["id"], p.session.email, None, {}, None)
    request.app.state.orgs.invalidate(org["id"])
    return {"connected": False}


@router.get("/setup")
def setup_checklist(request: Request, p: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    """First-run steps for a real company, each computed from its own data."""
    org = _control(request).org(p.session.org_id)
    approvers = sum(m["role"] in ("owner", "operator") for m in _control(request).members(org["id"]))  # a viewer cannot approve
    with p.ctx.conn() as conn:
        n = lambda t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731 - fixed table names only
        customers, invoices, bills, deposits = n("customers"), n("invoices"), n("obligations"), n("deposits")
        openings = n("wallet_opening")
    steps = [
        {"id": "bank", "label": "Connect your Airwallex account", "done": org["bank_mode"] != "local", "page": "settings"},
        {"id": "opening", "label": "Set opening balances, and reserves in Settings → Policy", "done": openings > 0, "page": "treasury"},
        {"id": "customers", "label": "Add the customers who pay you", "done": customers > 0, "page": "customers"},
        {"id": "invoices", "label": "Add open invoices", "done": invoices > 0, "page": "customers"},
        {"id": "bills", "label": "Add upcoming bills and payroll", "done": bills > 0, "page": "treasury"},
        {"id": "approver", "label": "Invite a second approver", "done": approvers > 1, "page": "team"},
        {"id": "payment", "label": "Receive your first payment", "done": deposits > 0, "page": "payments"},
    ]
    return {"show": org["kind"] != "sample" and not all(x["done"] for x in steps), "steps": steps}


@router.post("/integrations/check")
def integration_check(request: Request, p: Principal = Depends(require_role("owner"))) -> dict[str, Any]:
    """Actively probe each configured integration and report exactly what happened. Nothing is assumed."""
    s = request.app.state.settings
    out: dict[str, Any] = {}
    if p.ctx.org.get("own_airwallex") and p.ctx.sandbox is not None:
        try:
            r = p.ctx.sandbox.readiness()
            money = ", ".join(f"{b['currency']} {b['available_amount']}" for b in r["balances"]) or "no balances"
            out["airwallex"] = {"status": "ok", "detail": f"your account answered just now; {len(r['global_accounts'])} receiving accounts; available balances: {money}"[:600], **r}
        except Exception as exc:  # noqa: BLE001 - reported to the owner
            out["airwallex"] = {"status": "error", "detail": f"account check failed: {type(exc).__name__}"[:300]}
    elif s.sender_socket and p.ctx.sandbox is not None:
        try:
            r = p.ctx.sandbox.readiness()
            money = ", ".join(f"{b['currency']} {b['available_amount']}" for b in r["balances"]) or "no balances"
            out["airwallex"] = {"status": "ok", "detail": f"the sending service reached the sandbox account just now; available balances: {money}"[:600], **r}
        except Exception as exc:  # noqa: BLE001 - reported to the owner
            out["airwallex"] = {"status": "error", "detail": f"sandbox check through the sending service failed: {type(exc).__name__}"[:300]}
    elif s.sender_socket and not s.sandbox_allowed(p.session.org_id):
        out["airwallex"] = {"status": "restricted", "detail": "the server's Airwallex sandbox account is reserved for operator-approved "
                                                              "organizations; this organization uses the simulated bank"}
    elif s.airwallex_configured and not s.sandbox_allowed(p.session.org_id):
        out["airwallex"] = {"status": "restricted", "detail": "the server's Airwallex sandbox account is reserved for operator-approved "
                                                              "organizations; this organization uses the simulated bank"}
    elif s.airwallex_configured:
        from ..providers.airwallex import AirwallexSandbox

        try:
            r = AirwallexSandbox(s.airwallex_client_id, s.airwallex_api_key, timeout=10).readiness()
            accounts = ", ".join(
                f"{'/'.join(a.get('supported_currencies') or ([a['currency']] if a.get('currency') else [])) or 'currency not reported'} {a['id']}"
                for a in r["global_accounts"]
            ) or "none yet (create one in the sandbox)"
            money = ", ".join(f"{b['currency']} {b['available_amount']}" for b in r["balances"]) or "no balances"
            out["airwallex"] = {"status": "ok", "detail": f"sandbox authentication succeeded just now; global accounts: {accounts}; "
                                                          f"available balances: {money}"[:600], **r}
        except Exception as exc:  # noqa: BLE001 - reported verbatim to the owner
            out["airwallex"] = {"status": "error", "detail": f"sandbox check failed: {type(exc).__name__}: {exc}"[:300]}
    else:
        out["airwallex"] = {"status": "not_configured", "detail": "AIRWALLEX_CLIENT_ID / AIRWALLEX_API_KEY not set on the server"}
    if s.claude_configured:
        try:
            import anthropic

            anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=10.0, max_retries=0).models.retrieve(s.claude_model)
            out["claude"] = {"status": "ok", "detail": f"model {s.claude_model} reachable just now"}
        except Exception as exc:  # noqa: BLE001
            out["claude"] = {"status": "error", "detail": f"Claude API check failed: {type(exc).__name__}"[:300]}
    else:
        out["claude"] = {"status": "not_configured", "detail": "ANTHROPIC_API_KEY not set; the offline rules reader is used"}
    out["payer_agents"] = {"status": "local_simulation", "detail": "explain_payment runs over MCP against simulated customer agents"}
    return out


class SandboxDepositBody(BaseModel):
    request_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
    currency: Literal['USD', 'EUR', 'GBP']
    amount: str = Field(strict=True, min_length=1, max_length=20)
    payer_name: str = Field(strict=True, min_length=1, max_length=100)
    reference: str = Field(strict=True, min_length=1, max_length=100)


def _sandbox_context(request: Request, p: Principal):
    if p.ctx.sandbox is None or not (p.ctx.org.get("own_airwallex") or request.app.state.settings.sandbox_allowed(p.session.org_id)):
        raise HTTPException(403, 'sandbox actions need a connected Airwallex account')
    return p.ctx


@router.get('/integrations/sandbox/deposits')
def sandbox_deposits(request: Request, p: Principal = Depends(require_role('owner'))):
    from ..sandbox_receipts import records
    return records(_sandbox_context(request, p))


@router.post('/integrations/sandbox/deposits')
def sandbox_deposit(request: Request, body: SandboxDepositBody, p: Principal = Depends(require_role('owner'))):
    from ..sandbox_receipts import SandboxReceiptError, create
    ctx = _sandbox_context(request, p)
    if not body.payer_name.strip() or not body.reference.strip():
        raise HTTPException(422, 'payer name and reference must not be blank')
    try:
        return create(ctx, body.request_id.lower(), body.currency, body.amount, body.payer_name.strip(), body.reference.strip(), p.actor)
    except SandboxReceiptError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/integrations/sandbox/deposits/sync')
def sandbox_deposits_sync(request: Request, p: Principal = Depends(require_role('owner'))):
    from ..sandbox_receipts import SandboxReceiptError, sync
    try:
        return sync(_sandbox_context(request, p), p.actor)
    except SandboxReceiptError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/integrations/sandbox/deposits/discover')
def sandbox_deposits_discover(request: Request, p: Principal = Depends(require_role('owner'))):
    """Polling fallback for missed webhooks: only this organization's receiving accounts, only since it was created."""
    from ..sandbox_receipts import SandboxReceiptError, discover
    ctx = _sandbox_context(request, p)
    try:
        return discover(ctx, p.actor, since=_control(request).org(p.session.org_id)['created_at'])
    except SandboxReceiptError as exc:
        raise HTTPException(409, str(exc)) from exc


class BeneficiaryBody(BaseModel):
    corridor: Literal['EUR_DE_LOCAL', 'GBP_GB_LOCAL', 'USD_US_LOCAL']
    company_name: str = Field(max_length=80)
    bank_name: str = Field(max_length=80)
    street_address: str = Field(max_length=80)
    city: str = Field(max_length=80)
    postcode: str = Field(max_length=10)
    iban: str | None = Field(None, max_length=40)
    account_number: str | None = Field(None, max_length=20)
    sort_code: str | None = Field(None, max_length=10)
    aba: str | None = Field(None, max_length=12)
    customer_id: str | None = Field(None, max_length=80)


@router.get('/integrations/sandbox/beneficiaries')
def sandbox_beneficiaries(request: Request, p: Principal = Depends(require_role('owner'))):
    from ..beneficiaries import CORRIDORS, summary
    ctx = _sandbox_context(request, p)
    return {'corridors': {k: v['label'] for k, v in CORRIDORS.items()},
            'items': [summary(i) for i in ctx.sandbox.list_beneficiaries()]}


@router.get('/integrations/sandbox/beneficiaries/schema')
def sandbox_beneficiary_schema(request: Request, corridor: str, p: Principal = Depends(require_role('owner'))):
    from ..beneficiaries import BeneficiaryError, schema
    ctx = _sandbox_context(request, p)
    try:
        return schema(ctx.sandbox, corridor)
    except BeneficiaryError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/integrations/sandbox/beneficiaries')
def sandbox_beneficiary_create(request: Request, body: BeneficiaryBody, p: Principal = Depends(require_role('owner'))):
    from ..beneficiaries import BeneficiaryError, create
    ctx = _sandbox_context(request, p)
    form = body.model_dump(exclude={'corridor', 'customer_id'})
    try:
        return create(ctx, body.corridor, form, p.actor, customer_id=body.customer_id)
    except BeneficiaryError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/integrations/sandbox/payment-links/{link_id}/publish')
def sandbox_payment_link(request: Request, link_id: str, p: Principal = Depends(require_role('owner'))):
    from ..payment_links import publish
    ctx = _sandbox_context(request, p)
    try:
        return publish(ctx, link_id, p.actor)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/integrations/sandbox/payment-links/{link_id}/check')
def sandbox_payment_link_check(request: Request, link_id: str, p: Principal = Depends(require_role('operator'))):
    from ..payment_links import check
    ctx = _sandbox_context(request, p)
    try:
        return check(ctx, link_id, p.actor)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


def auth_error_handler(_request: Request, exc: AuthError):
    from fastapi.responses import JSONResponse

    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    return JSONResponse({"detail": str(exc)}, status_code=exc.status, headers=headers)
