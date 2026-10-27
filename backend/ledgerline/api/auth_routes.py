"""Account, organization and team endpoints (control plane)."""
from __future__ import annotations

from typing import Any, Literal

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
                                             org_name=body.organization_name, kind=kind, user_agent=_ua(request))
    request.app.state.orgs.provision(org_id, sample=kind == "sample")
    set_session_cookie(request, response, token)
    return _me(request, token)


class LoginBody(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


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
    org_id = _control(request).create_org(info.user_id, body.name, kind)
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
    import json as _json

    org = _control(request).org(p.session.org_id)
    s = request.app.state.settings
    return {
        "id": org["id"], "name": org["name"], "kind": org["kind"], "bank_mode": org["bank_mode"],
        "airwallex_global_accounts": _json.loads(org["airwallex_global_accounts"] or "{}"),
        "airwallex_webhook_secret_set": bool(org["airwallex_webhook_secret"]),
        "webhook_path": f"/api/webhooks/airwallex/{org['id']}",
        "server": {"airwallex_credentials_present": s.airwallex_configured, "claude_key_present": s.claude_configured,
                   "claude_model": s.claude_model},
        "control_audit": _control(request).control_audit(org["id"], 50) if p.role == "owner" else [],
    }


@router.put("/organization")
def update_org(request: Request, body: dict[str, Any], p: Principal = Depends(require_role("owner"))) -> dict[str, Any]:
    _control(request).update_org_settings(p.session.org_id, p.session.email, body,
                                          sandbox_available=request.app.state.settings.airwallex_configured)
    request.app.state.orgs.invalidate(p.session.org_id)
    return org_settings(request, p)


@router.post("/integrations/check")
def integration_check(request: Request, p: Principal = Depends(require_role("owner"))) -> dict[str, Any]:
    """Actively probe each configured integration and report exactly what happened. Nothing is assumed."""
    s = request.app.state.settings
    out: dict[str, Any] = {}
    if s.airwallex_configured:
        from ..providers.airwallex import AirwallexSandbox

        try:
            r = AirwallexSandbox(s.airwallex_client_id, s.airwallex_api_key, timeout=10).readiness()
            accounts = ", ".join(f"{a['currency']} {a['id']}" for a in r["global_accounts"]) or "none yet (create one in the sandbox)"
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


def auth_error_handler(_request: Request, exc: AuthError):
    from fastapi.responses import JSONResponse

    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    return JSONResponse({"detail": str(exc)}, status_code=exc.status, headers=headers)
