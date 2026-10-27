"""Sign in with Google / Apple: start, callback, connected identities.

Flow: /start stores a single-use attempt (state, nonce, PKCE verifier) server-side and
sets a short-lived HttpOnly binding cookie, then redirects to the provider. The
callback must present the same state *and* that cookie (so a code obtained in one
browser cannot be replayed into another), then the code is exchanged server-side
and the ID token is verified (oidc.py) before any account is touched.

Errors redirect back to the sign-in page with a short code (?oauth_error=...); the
detail is logged, never shown.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from ..control import AuthError
from ..oidc import JWKSCache, OIDCError, authorization_url, configured_providers, email_verified, exchange_code, verify_id_token
from .security import SESSION_COOKIE, require_session, set_session_cookie

router = APIRouter()
log = logging.getLogger("ledgerline.oauth")

BINDING_COOKIE = "ll_oauth"
BINDING_PATH = "/api/auth/oauth"
_RETURN_TO = re.compile(r"^/#/(inbox|settings|invite\?token=[A-Za-z0-9_-]{16,128})$")
_jwks = JWKSCache()


def _providers(request: Request):
    return configured_providers(request.app.state.settings)


def _http(request: Request) -> httpx.Client:
    # Tests inject a MockTransport here; production uses the real network.
    transport = getattr(request.app.state, "oidc_transport", None)
    return httpx.Client(transport=transport, timeout=10.0)


def _redirect_uri(request: Request, provider: str) -> str:
    return f"{request.app.state.settings.public_url}/api/auth/oauth/{provider}/callback"


def _safe_return(value: str | None, default: str) -> str:
    return value if value and _RETURN_TO.match(value) else default


def _fail(request: Request, code: str, return_to: str = "/#/signin") -> RedirectResponse:
    target = "/#/settings" if return_to == "/#/settings" else "/#/signin"
    sep = "&" if "?" in target else "?"
    resp = RedirectResponse(f"{target}{sep}oauth_error={quote(code)}", status_code=303)
    _clear_binding(request, resp)
    return resp


def _clear_binding(request: Request, resp: Response) -> None:
    resp.delete_cookie(BINDING_COOKIE, path=BINDING_PATH, secure=request.app.state.settings.cookie_secure,
                       samesite="none" if request.app.state.settings.cookie_secure else "lax")


@router.get("/auth/providers")
def providers(request: Request) -> dict[str, Any]:
    configured = _providers(request)
    return {name: {"configured": name in configured} for name in ("google", "apple")}


@router.get("/auth/oauth/{provider}/start")
def start(request: Request, provider: str, intent: str = "signin", return_to: str | None = None):
    p = _providers(request).get(provider)
    if p is None:
        return _fail(request, "not_configured")
    link_user = None
    if intent == "link":
        # Connecting a provider to the signed-in account. Same-site top-level GET, so the
        # SameSite=Strict session cookie is present here (it will not be on the callback).
        info = request.app.state.control.authenticate(request.cookies.get(SESSION_COOKIE))
        if info is None:
            return _fail(request, "signin_required")
        link_user = info.user_id
        return_to = "/#/settings"
    elif intent != "signin":
        raise HTTPException(422, "intent must be signin or link")
    binding = secrets.token_urlsafe(32)
    state, nonce, verifier = request.app.state.control.oauth_begin(
        provider=provider, binding=binding, intent=intent, link_user_id=link_user,
        return_to=_safe_return(return_to, "/#/inbox"), use_pkce=p.use_pkce)
    resp = RedirectResponse(authorization_url(p, redirect_uri=_redirect_uri(request, provider), state=state, nonce=nonce,
                                              code_verifier=verifier), status_code=302)
    secure = request.app.state.settings.cookie_secure
    # Apple returns with a cross-site form POST, which only carries SameSite=None cookies (HTTPS only).
    resp.set_cookie(BINDING_COOKIE, binding, httponly=True, secure=secure, samesite="none" if secure else "lax",
                    path=BINDING_PATH, max_age=600)
    return resp


@router.api_route("/auth/oauth/{provider}/callback", methods=["GET", "POST"])
async def callback(request: Request, provider: str):
    params: dict[str, Any] = dict(request.query_params)
    if request.method == "POST":
        params.update({k: v for k, v in (await request.form()).items() if isinstance(v, str)})
    p = _providers(request).get(provider)
    if p is None:
        return _fail(request, "not_configured")
    control = request.app.state.control
    if params.get("error"):
        # The user cancelled or the provider refused; still burn the attempt.
        try:
            control.oauth_consume(provider=provider, state=params.get("state", ""), binding=request.cookies.get(BINDING_COOKIE))
        except AuthError:
            pass
        return _fail(request, "cancelled")
    try:
        rec = control.oauth_consume(provider=provider, state=params.get("state", ""), binding=request.cookies.get(BINDING_COOKIE))
    except AuthError as exc:
        log.warning("oauth %s callback refused: %s", provider, exc)
        return _fail(request, str(exc))
    try:
        with _http(request) as http:
            id_token = exchange_code(p, code=str(params.get("code", "")), redirect_uri=_redirect_uri(request, provider),
                                     code_verifier=rec["code_verifier"], http=http)
            claims = verify_id_token(p, id_token, nonce=rec["nonce"], jwks=_jwks, http=http)
    except OIDCError as exc:
        log.warning("oauth %s token refused: %s", provider, exc)
        return _fail(request, exc.code, rec["return_to"])

    name = claims.get("name")
    if provider == "apple" and params.get("user"):
        # Apple sends the name once, outside the signed token, on first authorization only. Display-only.
        try:
            n = json.loads(params["user"]).get("name") or {}
            name = " ".join(x for x in (n.get("firstName"), n.get("lastName")) if isinstance(x, str)).strip() or None
        except (ValueError, AttributeError):
            name = None

    if rec["intent"] == "link":
        try:
            control.oauth_link(user_id=rec["link_user_id"], provider=provider, subject=claims["sub"], email=claims.get("email"))
        except AuthError as exc:
            return _fail(request, str(exc), "/#/settings")
        resp = RedirectResponse(f"/#/settings?oauth_linked={provider}", status_code=303)
        _clear_binding(request, resp)
        return resp

    try:
        token, _created = control.oauth_signin(
            provider=provider, subject=claims["sub"], email=claims.get("email"), verified=email_verified(claims),
            name=name if isinstance(name, str) else None, allow_signup=request.app.state.settings.allow_signup,
            ip=request.client.host if request.client else "unknown", user_agent=request.headers.get("user-agent", "")[:200])
    except AuthError as exc:
        return _fail(request, str(exc))
    resp = RedirectResponse(rec["return_to"], status_code=303)
    set_session_cookie(request, resp, token)
    _clear_binding(request, resp)
    return resp


@router.get("/auth/identities")
def identities(request: Request) -> dict[str, Any]:
    info, _ = require_session(request, mutating=False)
    return {**request.app.state.control.identities(info.user_id),
            "available": {name: name in _providers(request) for name in ("google", "apple")}}


@router.delete("/auth/identities/{provider}")
def unlink(request: Request, provider: str) -> dict[str, Any]:
    info, _ = require_session(request, mutating=True)
    request.app.state.control.oauth_unlink(info.user_id, provider)
    return {"unlinked": provider}


@router.post("/invitations/{token}/accept-signed-in")
def accept_signed_in(request: Request, token: str) -> dict[str, Any]:
    info, session_token = require_session(request, mutating=True)
    org_id = request.app.state.control.accept_invitation_signed_in(token, user_id=info.user_id, email=info.email,
                                                                    session_token=session_token)
    return {"joined": org_id}
