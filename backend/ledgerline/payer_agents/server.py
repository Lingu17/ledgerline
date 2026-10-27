"""MCP server exposing the payer agents' `explain_payment` tool.

Run standalone over stdio:  python -m ledgerline.payer_agents.server --data-dir var
Ledgerline launches it as a subprocess and talks to it with the MCP client SDK.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from mcp.server.mcpserver import MCPServer

from .. import crypto
from ..clock import iso
from . import books
from .keys import EnvKeys, load_keys

ANSWER_TTL = timedelta(minutes=10)


def build_server(data_dir, now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> MCPServer:
    app = MCPServer(
        "ledgerline-payer-agents",
        instructions="Simulated customer accounts-payable agents (local demo). Answers are signed claims.",
    )

    @app.tool()
    def explain_payment(
        customer_id: str,
        deposit_id: str,
        currency: str,
        amount_minor: int,
        received_at: str,
        reference: str = "",
    ) -> dict[str, Any]:
        """Ask a customer's AP agent what a received payment was for. Returns a signed claim or status 'unknown'."""
        keys = load_keys(data_dir)  # never creates: a missing key means no agent, not a new identity
        if customer_id not in keys:
            return {"status": "no_agent", "customer_id": customer_id}
        entry = books.lookup(customer_id, currency, amount_minor)
        if entry is None:
            return {"status": "unknown", "customer_id": customer_id, "detail": "no matching payment in our AP books"}
        now = now_fn()
        claim = {
            "schema": "ledgerline.explain_payment.v1",
            "deposit_id": deposit_id,
            "customer_id": customer_id,
            "currency": currency,
            "amount_minor": amount_minor,
            "invoice_id": entry["invoice_id"],
            "reason": entry["reason"],
            "note": entry["note"],
            "issued_at": iso(now),
            "expires_at": iso(now + ANSWER_TTL),
            "nonce": secrets.token_hex(8),
        }
        return {"status": "answered", "envelope": crypto.sign_claim(claim, keys[customer_id])}

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir")
    args = parser.parse_args()
    env_keys = os.environ.get("LEDGERLINE_AGENT_KEYS")
    # Hosted mode: the parent passes the decrypted keys of this organization's agents through the child's
    # environment (never argv, which is visible in process lists); the child has no database access.
    location = EnvKeys(json.loads(env_keys)) if env_keys else Path(args.data_dir)
    build_server(location).run("stdio")


if __name__ == "__main__":
    main()
