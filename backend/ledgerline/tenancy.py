"""Organization isolation: one database, simulated bank and payer-agent key set per organization.

Every authenticated request is bound to exactly one organization's AppContext,
resolved from the session's verified membership. Domain code only ever receives
that context, so a query cannot reach another organization's rows: they live in
a different database file.
"""
from __future__ import annotations

import dataclasses
import json
import re
import threading
from pathlib import Path
from typing import Any

from .clock import Clock
from .config import Settings
from .context import AppContext
from .control import ControlPlane
from .providers.local import LocalBank

_ORG_ID = re.compile(r"^org_[0-9a-f]{12}$")


def org_dir(base: Path, org_id: str) -> Path:
    if not _ORG_ID.match(org_id):  # defence in depth: ids never become path traversal
        raise ValueError("invalid organization id")
    return base / "orgs" / org_id


def build_org_context(settings: Settings, org: dict[str, Any], clock: Clock) -> AppContext:
    data_dir = org_dir(settings.data_dir, org["id"])
    s = dataclasses.replace(
        settings,
        data_dir=data_dir,
        db_path=data_dir / "ledgerline.sqlite3",
        webhook_secret=org["webhook_secret_local"],
        airwallex_webhook_secret=org.get("airwallex_webhook_secret"),
        airwallex_global_account_ids=json.loads(org.get("airwallex_global_accounts") or "{}"),
        provider=org.get("bank_mode", "local"),
    )
    local_bank = sandbox = None
    if s.provider == "airwallex_sandbox":
        from .providers.airwallex import AirwallexSandbox

        if not settings.sandbox_allowed(org["id"]):
            # Shared sandbox credentials are reserved for operator-approved organizations (LEDGERLINE_SANDBOX_ORGS).
            from .control import AuthError

            raise AuthError(403, "this organization is not authorized to use the server's Airwallex sandbox credentials")
        sandbox = AirwallexSandbox(s.airwallex_client_id, s.airwallex_api_key)
        provider: Any = sandbox
    else:
        local_bank = LocalBank(data_dir / "local_bank.sqlite3", clock)
        provider = local_bank
    ctx = AppContext(settings=s, clock=clock, provider=provider, local_bank=local_bank, sandbox=sandbox)
    ctx.org = {k: org[k] for k in ("id", "name", "kind", "bank_mode")}
    return ctx


class OrgRegistry:
    def __init__(self, settings: Settings, control: ControlPlane, clock: Clock) -> None:
        self.settings = settings
        self.control = control
        self.clock = clock
        self._cache: dict[str, AppContext] = {}
        self._lock = threading.Lock()

    def get(self, org_id: str) -> AppContext:
        with self._lock:
            ctx = self._cache.get(org_id)
            if ctx is not None and ctx.sandbox is not None and not self.settings.sandbox_allowed(org_id):
                # Allow-list checked at every use, so withdrawing access applies even to a cached context.
                self._cache.pop(org_id, None)
                ctx = None
            if ctx is None:
                org = self.control.org(org_id)
                if org is None:
                    raise KeyError(org_id)
                ctx = build_org_context(self.settings, org, self.clock)
                self._cache[org_id] = ctx
            return ctx

    def invalidate(self, org_id: str) -> None:
        with self._lock:
            self._cache.pop(org_id, None)

    def provision(self, org_id: str, *, sample: bool) -> AppContext:
        """Create the tenant database. Sample orgs get the reference scenario; workspaces start empty."""
        from . import db
        from .demo import run_step

        ctx = self.get(org_id)
        with ctx.conn() as conn:
            if db.get_setting(conn, "provisioned"):
                return ctx
        if sample:
            run_step(ctx, "seed", "system")
            if self.settings.sample_workspace and ctx.local_bank is not None:
                run_step(ctx, "deposits", "system")
                run_step(ctx, "links", "system")
        with ctx.conn() as conn, db.transaction(conn):
            db.set_setting(conn, "provisioned", True)
            db.set_setting(conn, "workspace_kind", "sample" if sample else "workspace")
        return ctx
