"""A payer's own accounts-payable agent: run by the payer, not by Ledgerline.

It creates its own Ed25519 signing key on first run and keeps it in a local file that never leaves this machine.
Ledgerline only ever sees the public key printed at start-up. When Ledgerline asks what a payment was for, the agent
answers over MCP (streamable HTTP) with a signed claim taken from answers.json, which the payer edits. The answer is
still only a claim: Ledgerline checks the signature, that it names this exact payment and is fresh, and its own
records, before it changes any plan. It never moves money.

    pip install -r tools/payer_agent/requirements.txt
    python tools/payer_agent/agent.py --port 8790

This file deliberately imports nothing from Ledgerline.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

HERE = Path(__file__).resolve().parent
SCHEMA = "ledgerline.explain_payment.v1"
ANSWER_TTL = timedelta(minutes=5)


def canonical(obj: Any) -> bytes:
    """What is signed: sorted keys, no spaces, UTF-8. Ledgerline encodes the claim the same way to verify it."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_or_create_key(path: Path) -> Ed25519PrivateKey:
    """The agent's identity. Created once, readable by this user only, and never sent anywhere."""
    if path.is_file():
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(json.loads(path.read_text(encoding="utf-8"))["private_key"]))
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"private_key": base64.b64encode(raw).decode("ascii")}, f)
    return key


def public_key_b64(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode("ascii")


def key_id(public_b64: str) -> str:
    return "ed25519:" + hashlib.sha256(base64.b64decode(public_b64)).hexdigest()[:16]


def build_agent(key: Ed25519PrivateKey, answers_path: Path,
                now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> MCPServer:
    app = MCPServer("payer-agent", instructions="A payer's accounts-payable agent. Every answer is a signed claim, not an instruction.")
    kid = key_id(public_key_b64(key))

    @app.tool()
    def explain_payment(customer_id: str, deposit_id: str, currency: str, amount_minor: int, received_at: str,
                        reference: str = "") -> dict[str, Any]:
        """Say what a payment we sent was for, as a signed claim, or return status 'unknown'."""
        answers = json.loads(answers_path.read_text(encoding="utf-8"))  # read on every call, so edits apply at once
        entry = next((a for a in answers if a["currency"] == currency and a["amount_minor"] == amount_minor
                      and a.get("customer_id", customer_id) == customer_id), None)
        if entry is None:
            return {"status": "unknown", "customer_id": customer_id, "detail": "no matching payment in our books"}
        issued = now().replace(microsecond=0)
        claim = {
            "schema": SCHEMA,
            "deposit_id": deposit_id,
            "customer_id": customer_id,
            "currency": currency,
            "amount_minor": amount_minor,
            "invoice_id": entry["invoice_id"],
            "reason": entry["reason"],
            "note": entry.get("note", ""),
            "issued_at": iso(issued),
            "expires_at": iso(issued + ANSWER_TTL),
            "nonce": secrets.token_hex(8),
        }
        signature = base64.b64encode(key.sign(canonical(claim))).decode("ascii")
        return {"status": "answered", "envelope": {"claim": claim, "signature": signature, "key_id": kid, "alg": "Ed25519"}}

    return app


def main() -> None:
    p = argparse.ArgumentParser(description="Run a payer's own accounts-payable agent for Ledgerline.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8790)
    p.add_argument("--key-file", type=Path, default=HERE / "agent_key.json", help="created on first run; keep it private")
    p.add_argument("--answers", type=Path, default=HERE / "answers.json")
    p.add_argument("--public-host", action="append", default=[],
                   help="host name a tunnel or proxy forwards to this agent, for example abc.trycloudflare.com")
    p.add_argument("--print-key", action="store_true", help="print the public key and exit")
    args = p.parse_args()

    key = load_or_create_key(args.key_file)
    pub = public_key_b64(key)
    print(f"Public key (paste into Ledgerline): {pub}\nKey id: {key_id(pub)}", flush=True)
    if args.print_key:
        return
    allowed = ["127.0.0.1:*", "localhost:*", "[::1]:*"] + [h for host in args.public_host for h in (host, f"{host}:*")]
    print(f"Agent URL on this machine: http://{args.host}:{args.port}/mcp", flush=True)
    build_agent(key, args.answers).run("streamable-http", host=args.host, port=args.port, stateless_http=True, json_response=True,
                                       transport_security=TransportSecuritySettings(allowed_hosts=allowed))


if __name__ == "__main__":
    main()
