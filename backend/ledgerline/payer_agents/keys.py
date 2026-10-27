"""Private signing keys for the simulated payer agents.

These belong to the *customers'* agents, not to Ledgerline. They are generated
locally on first use and stored under the data dir (gitignored). Ledgerline's
database only ever stores the public half (the customer key registry).
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import crypto

AGENT_CUSTOMERS = ("CUST-ACME", "CUST-BRIGHTWAVE", "CUST-CALDER", "CUST-DUNMORE", "CUST-EASTGATE", "CUST-FJORD")


def keys_path(data_dir: Path) -> Path:
    return data_dir / "payer_agents" / "private_keys.json"


def ensure_keys(data_dir: Path) -> dict[str, str]:
    path = keys_path(data_dir)
    keys: dict[str, str] = {}
    if path.is_file():
        keys = json.loads(path.read_text(encoding="utf-8"))
        if all(c in keys for c in AGENT_CUSTOMERS):
            return keys
    for cid in AGENT_CUSTOMERS:
        keys.setdefault(cid, crypto.generate_keypair()[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keys, indent=2), encoding="utf-8")
    return keys


def public_registry(data_dir: Path) -> dict[str, dict[str, str]]:
    """What each customer registers with Ledgerline at onboarding: key id + public key only."""
    out = {}
    for cid, priv in ensure_keys(data_dir).items():
        pub = crypto.public_from_private(priv)
        out[cid] = {"key_id": crypto.key_id_for(pub), "public_key": pub}
    return out
