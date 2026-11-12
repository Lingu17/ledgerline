"""Validate a recorded outside-agent run (docs/evidence/outside-agent-run.json) without trusting Ledgerline's own code.

    python scripts/validate_outside_run.py [path]

Checks, each printed as PASS or FAIL (exit 1 on any FAIL):
  1. the Ed25519 signature on the stored claim verifies with the registered public key (checked here, independently);
  2. the key fingerprint (ed25519:<first 16 hex of sha256(public key)>) matches the envelope, the registration and the proof;
  3. the key differs from every key the server holds for its built-in agents, as seen in the same company's answers,
     and from the key used in the 3 Nov run on the owner's PC;
  4. ids and times agree: payment, customer, evidence id, agent host; the key was registered before the claim was
     issued, the answer was stored inside the claim's validity window, and the proof was written after it;
  5. Ledgerline recorded all three checks as passed (signature, binding, records), the verdict, and the plan change.
Only the `cryptography` package is needed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DEFAULT = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "outside-agent-run.json"
OWNER_PC_KEY_3_NOV = "ed25519:5b38d62d2a682719"
LABEL = "separate machine, separate key, operated by the Ledgerline author"


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def fingerprint(public_b64: str) -> str:
    return "ed25519:" + hashlib.sha256(base64.b64decode(public_b64, validate=True)).hexdigest()[:16]


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def validate(data: dict) -> list[tuple[bool, str]]:
    out: list[tuple[bool, str]] = []

    def check(ok: bool, what: str) -> None:
        out.append((bool(ok), what))

    reg, ev, proof = data["registered"], data["evidence"], data["proof"]
    env, claim = ev["envelope"], ev["envelope"]["claim"]
    run = next(r for r in proof["runs"] if r["evidence_id"] == ev["id"])

    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(reg["public_key"], validate=True)).verify(
            base64.b64decode(env["signature"], validate=True), canonical(claim))
        sig_ok = True
    except (InvalidSignature, ValueError):
        sig_ok = False
    check(sig_ok and env.get("alg") == "Ed25519", "signature on the stored claim verifies with the registered public key")

    fp = fingerprint(reg["public_key"])
    check(fp == env["key_id"] == reg["key_id"] == run["key_id"], f"fingerprint {fp} matches envelope, registration and proof")

    builtin = {v["key_id"] for v in data["builtin_agents"].values()}
    check(len(builtin) >= 2 and all(v.get("transport", "").startswith("mcp/") and "http" not in v.get("transport", "")
                                     for v in data["builtin_agents"].values()),
          f"built-in agents' keys recorded from the same company ({', '.join(sorted(builtin))})")
    check(fp not in builtin and fp != OWNER_PC_KEY_3_NOV, "the key differs from every server-held key and from the 3 Nov PC key")

    host = urlparse(reg["agent_url"]).hostname
    check(claim["deposit_id"] == ev["deposit_id"] == run["deposit_id"], f"payment id agrees ({claim['deposit_id']})")
    check(claim["customer_id"] == reg["customer_id"], f"customer id agrees ({claim['customer_id']})")
    check(ev["transport"] == f"mcp/http {host}" == f"mcp/http {run['endpoint_host']}", f"agent host agrees ({host})")
    check(ts(reg["set_at"]) <= ts(claim["issued_at"]) <= ts(ev["created_at"]) <= ts(claim["expires_at"]),
          "registered before the claim was issued; stored inside the claim's validity window")
    check(ts(ev["created_at"]) <= ts(run["at"]) <= ts(proof["generated_at"]), "proof written after the answer was stored")

    names = {c["name"]: c["passed"] for c in ev["checks"]}
    check(names == {"signature": True, "binding": True, "records": True} and run["checks"] == names,
          "all three checks recorded as passed, in the evidence and in the proof")
    check(ev["verdict"] == run["verdict"] == "verified" and run["signature_valid"] is True, "verdict verified")
    check(run["plan_before"]["category"] != run["plan_after"]["category"] and run["plan_after"]["version"] > run["plan_before"]["version"],
          f"plan changed: {run['plan_before']['category']} -> {run['plan_after']['category']}")
    check(data.get("label") == LABEL, f'labelled exactly "{LABEL}"')
    return out


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("placeholder"):
        print("FAIL  no run recorded yet (placeholder)")
        return 1
    results = validate(data)
    for ok, what in results:
        print(f"{'PASS' if ok else 'FAIL'}  {what}")
    bad = sum(1 for ok, _ in results if not ok)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
