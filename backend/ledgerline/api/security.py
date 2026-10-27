"""Authentication, CSRF and role checks for every tenant route.

- Session: random token in an HttpOnly, SameSite=Strict cookie (Secure when
  LEDGERLINE_COOKIE_SECURE=1). Only its SHA-256 is stored server-side.
- CSRF: state-changing requests must echo the session's CSRF token in
  X-CSRF-Token (the SPA reads it from /api/auth/me), come from an allowed
  Origin when one is sent, and must not be cross-site per Sec-Fetch-Site.
- Authorization: the session's active organization and the member's role are
  re-read from the control plane on every request; the request is then bound
  to that organization's isolated context only.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Callable

from fastapi import HTTPException, Request, Response

from ..context import AppContext
from ..control import ROLE_RANK, SessionInfo

SESSION_COOKIE = "ll_session"


@dataclass
class Principal:
    session: SessionInfo
    token: str
    ctx: AppContext

    @property
    def actor(self) -> str:
        return self.session.email

    @property
    def role(self) -> str:
        return self.session.role or ""


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    secure = request.app.state.settings.cookie_secure
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", secure=secure, path="/api",
                        max_age=12 * 3600)


def clear_session_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/api", samesite="strict", secure=request.app.state.settings.cookie_secure)


def session_of(request: Request) -> tuple[SessionInfo, str]:
    token = request.cookies.get(SESSION_COOKIE)
    info = request.app.state.control.authenticate(token)
    if info is None or token is None:
        raise HTTPException(401, "sign in required")
    return info, token


def check_csrf(request: Request, info: SessionInfo) -> None:
    settings = request.app.state.settings
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.allowed_origins:
        raise HTTPException(403, f"origin {origin} not allowed")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "cross-site request refused")
    supplied = request.headers.get("x-csrf-token", "")
    if not supplied or not hmac.compare_digest(supplied, info.csrf_token):
        raise HTTPException(403, "missing or invalid CSRF token; reload the page")


def _principal(request: Request, min_role: str, mutating: bool) -> Principal:
    info, token = session_of(request)
    if mutating:
        check_csrf(request, info)
    if not info.org_id or not info.role:
        raise HTTPException(403, "no organization selected or membership revoked")
    if ROLE_RANK[info.role] < ROLE_RANK[min_role]:
        raise HTTPException(403, f"this action needs the {min_role} role; you are {info.role}")
    try:
        ctx = request.app.state.orgs.get(info.org_id)
    except KeyError as exc:
        raise HTTPException(403, "organization not found") from exc
    p = Principal(info, token, ctx)
    request.state.principal = p
    return p


def require_role(min_role: str, *, mutating: bool | None = None) -> Callable[[Request], Principal]:
    def dep(request: Request) -> Principal:
        is_mutation = request.method not in ("GET", "HEAD", "OPTIONS") if mutating is None else mutating
        return _principal(request, min_role, is_mutation)

    return dep


def require_reader(request: Request) -> Principal:
    return _principal(request, "viewer", request.method not in ("GET", "HEAD", "OPTIONS"))


def require_operator(request: Request) -> str:
    """Operator or owner; returns the actor recorded in the audit trail."""
    return _principal(request, "operator", True).actor


def require_owner(request: Request) -> str:
    return _principal(request, "owner", True).actor


def require_session(request: Request, *, mutating: bool) -> tuple[SessionInfo, str]:
    """Signed in, organization optional (account-level endpoints)."""
    info, token = session_of(request)
    if mutating:
        check_csrf(request, info)
    return info, token
