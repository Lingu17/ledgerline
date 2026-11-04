"""FastAPI application factory."""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from ..clock import Clock
from ..config import BACKEND_DIR, Settings, load_settings
from ..context import AppContext
from ..control import AuthError, ControlPlane
from ..demo import DemoError
from ..money import MoneyError
from ..payouts import Paused, PayoutError, PracticeOnly, SelfApproval, StaleApproval
from ..providers.base import ProviderError
from ..providers.local import LocalBank
from ..reconcile import ReconcileError
from ..sender import SenderRefused, SenderUnavailable
from ..tenancy import OrgRegistry
from ..treasury import TreasuryError
from ..webhooks import WebhookRejected
from ..workspace import InputError
from .auth_routes import auth_error_handler
from .auth_routes import router as auth_router
from .oauth_routes import router as oauth_router
from .security import client_ip, same_secret
from .routes import router

FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"
log = logging.getLogger("ledgerline")


def build_context(settings: Settings, clock: Clock | None = None) -> AppContext:
    """A single organization's context rooted at settings.data_dir (used by domain tests and tools)."""
    clock = clock or Clock()
    local_bank = None
    sandbox = None
    if settings.provider == "airwallex_sandbox":
        from ..providers.airwallex import AirwallexSandbox

        if not settings.airwallex_configured:
            raise RuntimeError("LEDGERLINE_PROVIDER=airwallex_sandbox requires AIRWALLEX_CLIENT_ID and AIRWALLEX_API_KEY")
        sandbox = AirwallexSandbox(settings.airwallex_client_id, settings.airwallex_api_key)
        provider = sandbox
    else:
        local_bank = LocalBank(settings.pg_target("b", "single") if settings.postgres else settings.data_dir / "local_bank.sqlite3", clock)
        provider = local_bank
    return AppContext(settings=settings, clock=clock, provider=provider, local_bank=local_bank, sandbox=sandbox)


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or load_settings()
    clock = clock or Clock()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if settings.require_persistent_mount and not settings.postgres:
        # Deployment guard: databases, organization data and signing keys must never land on ephemeral disk.
        mount = Path(settings.require_persistent_mount).resolve()
        if not os.path.ismount(mount) or mount not in [settings.data_dir.resolve(), *settings.data_dir.resolve().parents]:
            raise RuntimeError(f"LEDGERLINE_DATA_DIR must be on the persistent mount {mount}; refusing to start on ephemeral storage")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    legacy = settings.data_dir / "ledgerline.sqlite3"
    if legacy.exists():
        log.warning("ignoring pre-SaaS single-tenant database %s; organizations live under %s", legacy, settings.data_dir / "orgs")

    control = ControlPlane(settings.pg_target("control") if settings.postgres else settings.data_dir / "control.sqlite3", clock)
    control.creation_limits = dict(zip(("per_ip_hour", "per_ip_day", "per_day"), settings.signup_limits))
    from .. import REPO_DIR, __version__, build_commit

    app = FastAPI(title="Ledgerline", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    commit = build_commit()  # read once: an update restarts the service
    app.state.settings = settings
    app.state.control = control
    app.state.orgs = OrgRegistry(settings, control, clock)

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            # Leave a correlatable line for requests that never produce a response (the traceback follows).
            if request.url.path.startswith("/api"):
                principal = getattr(request.state, "principal", None)
                log.error("%s %s failed after %.0fms: %s org=%s user=%s", request.method,
                          getattr(request.scope.get("route"), "path", "<unmatched-api-route>"),
                          (time.perf_counter() - started) * 1000, type(exc).__name__,
                          principal.session.org_id if principal else "-", principal.session.email if principal else "-")
            raise
        if request.url.path.startswith("/api"):
            principal = getattr(request.state, "principal", None)
            # Invitation URLs contain bearer credentials. Log the route template,
            # never a raw URL whose path could reveal a one-time invitation token.
            route = request.scope.get("route")
            safe_path = getattr(route, "path", "<unmatched-api-route>")
            log.info("%s %s %s %.0fms org=%s user=%s", request.method, safe_path, response.status_code,
                     (time.perf_counter() - started) * 1000,
                     principal.session.org_id if principal else "-", principal.session.email if principal else "-")
            response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    def _err(status: int):
        def handler(_request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse({"detail": str(exc), "error": type(exc).__name__}, status_code=status)
        return handler

    app.add_exception_handler(Paused, _err(423))
    app.add_exception_handler(StaleApproval, _err(409))
    app.add_exception_handler(SelfApproval, _err(403))
    app.add_exception_handler(PracticeOnly, _err(403))
    for exc_type in (PayoutError, ReconcileError, TreasuryError, DemoError):
        app.add_exception_handler(exc_type, _err(409))
    app.add_exception_handler(MoneyError, _err(422))
    app.add_exception_handler(InputError, _err(422))
    app.add_exception_handler(ProviderError, _err(502))
    app.add_exception_handler(SenderUnavailable, _err(503))
    app.add_exception_handler(SenderRefused, _err(403))
    app.add_exception_handler(AuthError, auth_error_handler)

    @app.exception_handler(sqlite3.OperationalError)
    def _busy(_request: Request, exc: sqlite3.OperationalError) -> JSONResponse:
        # Many sign-ups at once can queue on the shared control database: say "busy, try again", not a bare 500.
        if "locked" in str(exc) or "busy" in str(exc):
            log.warning("database busy: %s", exc)
            return JSONResponse({"detail": "the server is busy; please try again in a moment", "error": "Busy"},
                                status_code=503, headers={"Retry-After": "2"})
        raise exc

    @app.exception_handler(WebhookRejected)
    def _webhook(_request: Request, exc: WebhookRejected) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    app.include_router(auth_router, prefix="/api")
    app.include_router(oauth_router, prefix="/api")

    def _edge_proof(request: Request) -> str:
        if settings.edge_secret is None:
            return "not configured"
        supplied = request.headers.get("x-ledgerline-edge")
        if not supplied:
            return "missing"
        if same_secret(supplied, settings.edge_secret):
            return "valid"
        if supplied.startswith("$"):
            return "invalid: unsubstituted placeholder"  # the edge sent its variable name, not its value
        return "invalid" if len(supplied) == len(settings.edge_secret) else "invalid: length differs"

    @app.get("/api/public/info", include_in_schema=False)
    def public_info() -> JSONResponse:
        """What any visitor may see: the version, and where to report a security problem (if the operator set one)."""
        return JSONResponse({"version": app.version, "commit": commit, "security_contact": settings.security_contact},
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/public/changelog", include_in_schema=False)
    def changelog() -> PlainTextResponse:
        path = REPO_DIR / "CHANGELOG.md"
        text = path.read_text(encoding="utf-8") if path.is_file() else "# Changelog\n\nNot available on this server.\n"
        return PlainTextResponse(text, media_type="text/markdown; charset=utf-8", headers={"Cache-Control": "no-store"})

    @app.get("/.well-known/security.txt", include_in_schema=False)
    def security_txt(request: Request) -> PlainTextResponse:
        # RFC 9116. Without a contact chosen by the operator there is nothing honest to publish.
        if not settings.security_contact:
            return PlainTextResponse("no security contact has been published for this server\n", status_code=404)
        expires = (datetime.now(timezone.utc) + timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if settings.public_url and not settings.public_url.startswith("http://localhost"):
            base = settings.public_url  # the configured origin, so a forged Host header cannot change what this file says
        else:
            local = request.url.hostname in ("localhost", "127.0.0.1", "::1")
            base = f"{'http' if local else 'https'}://{request.url.netloc}"  # behind the proxy the app itself sees http
        return PlainTextResponse(f"Contact: {settings.security_contact}\nExpires: {expires}\nPreferred-Languages: en\n"
                                 f"Canonical: {base}/.well-known/security.txt\nPolicy: {base}/#/security\n")

    @app.get("/api/health", include_in_schema=False)
    def health(request: Request) -> JSONResponse:
        """Liveness and readiness for the host's health check: control database readable and data directory writable."""
        try:
            with control.conn() as c:
                schema = c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            if settings.postgres:
                storage = "postgresql"
            else:
                probe = settings.data_dir / ".health"
                probe.write_text(str(time.time()), encoding="utf-8")
                storage = "persistent mount" if settings.require_persistent_mount else "local directory"
            body = {"status": "ok", "version": app.version, "commit": commit, "control_schema": schema, "storage": storage,
                    "bank": settings.provider, "claude": "configured" if settings.claude_configured else "not configured",
                    # The caller's own address as resolved through trusted proxies (verifies proxy configuration).
                    "client": client_ip(request),
                    # Hop count of the caller's own forwarding chain (no addresses), for calibrating LEDGERLINE_TRUSTED_PROXY_HOPS.
                    "forwarded_entries": len([x for x in request.headers.get("x-forwarded-for", "").split(",") if x.strip()]),
                    "trusted_hops": settings.trusted_proxy_hops,
                    # Whether this request carried the edge's proof (never the value), for checking the edge secret matches.
                    "edge_proof": _edge_proof(request)}
            return JSONResponse(body, headers={"Cache-Control": "no-store"})
        except Exception as exc:  # noqa: BLE001 - report unhealthy instead of crashing the probe
            log.error("health check failed: %s", exc)
            return JSONResponse({"status": "unavailable"}, status_code=503, headers={"Cache-Control": "no-store"})
    app.include_router(router, prefix="/api")

    if FRONTEND_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            candidate = (FRONTEND_DIST / path).resolve()
            if path and candidate.is_file() and Path(FRONTEND_DIST.resolve()) in candidate.parents:
                return FileResponse(candidate)
            if "." in path.rsplit("/", 1)[-1]:  # asks for a file (robots.txt, .hg, x.php) that is not there: say so
                return PlainTextResponse("not found\n", status_code=404)
            return FileResponse(FRONTEND_DIST / "index.html")  # an app address: the page routes it

    return app
