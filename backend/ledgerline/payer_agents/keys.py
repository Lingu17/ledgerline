"""Private signing keys for the simulated payer agents.

These belong to the *customers'* agents, not to Ledgerline. Ledgerline's ledger only ever stores
the public half (the customer key registry). Two stores:

- File (local SQLite mode): `<org data dir>/payer_agents/private_keys.json`, gitignored.
- PostgreSQL (hosted mode): table `agent_keys` in the organization's own schema, each private key
  encrypted with AES-256-GCM under a key derived (HKDF-SHA256) from the server secret
  LEDGERLINE_SECRET_KEY, with the schema and customer id as associated data, so a ciphertext cannot
  be moved to another organization or customer. The secret never enters the database.

Keys are created only when an organization's sample scenario is seeded (`ensure_keys`). The agent
itself only *loads* keys (`load_keys`): a missing or undecryptable key is an error, never a silent
new identity, because a new identity would no longer match the public key the customer registered.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .. import crypto

AGENT_CUSTOMERS = ("CUST-ACME", "CUST-BRIGHTWAVE", "CUST-CALDER", "CUST-DUNMORE", "CUST-EASTGATE", "CUST-FJORD")


class KeyStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class PgKeys:
    target: object  # db.PgTarget of the organization's ledger schema
    secret: str


@dataclass(frozen=True)
class EnvKeys:
    """Keys handed to the stdio MCP subprocess by its parent (hosted mode: the child has no database access)."""
    keys: dict


KeyLocation = Union[Path, PgKeys, EnvKeys]


def key_location(settings) -> KeyLocation:
    if getattr(settings, "postgres", False):
        return PgKeys(settings.db_path, settings.secret_key)
    return settings.data_dir


def keys_path(data_dir: Path) -> Path:
    return data_dir / "payer_agents" / "private_keys.json"


def _aead(secret: str) -> AESGCM:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"ledgerline", info=b"payer-agent-keys v1").derive(secret.encode())
    return AESGCM(key)


def _aad(target, customer_id: str) -> bytes:
    return f"{target.schema}:{customer_id}".encode()


def encrypt(secret: str, target, customer_id: str, private_key: str) -> str:
    nonce = os.urandom(12)
    ct = _aead(secret).encrypt(nonce, private_key.encode(), _aad(target, customer_id))
    return "v1:" + base64.b64encode(nonce + ct).decode()


def decrypt(secret: str, target, customer_id: str, blob: str) -> str:
    if not blob.startswith("v1:"):
        raise KeyStoreError(f"unknown key encoding for {customer_id}")
    raw = base64.b64decode(blob[3:])
    try:
        return _aead(secret).decrypt(raw[:12], raw[12:], _aad(target, customer_id)).decode()
    except Exception as exc:  # cryptography raises InvalidTag
        raise KeyStoreError(f"cannot decrypt the signing key for {customer_id}: wrong LEDGERLINE_SECRET_KEY or tampered row") from exc


def _pg_conn(loc: PgKeys) -> sqlite3.Connection:
    from .. import db

    c = db.connect(loc.target)
    c.execute("CREATE TABLE IF NOT EXISTS agent_keys (customer_id TEXT PRIMARY KEY, private_key_enc TEXT NOT NULL, created_at TEXT NOT NULL)")
    from ..pg import harden

    harden(c)
    return c


def load_keys(loc: KeyLocation) -> dict[str, str]:
    """Existing keys only. Never creates."""
    if isinstance(loc, EnvKeys):
        return dict(loc.keys)
    if isinstance(loc, PgKeys):
        c = _pg_conn(loc)
        try:
            rows = c.execute("SELECT customer_id, private_key_enc FROM agent_keys").fetchall()
        finally:
            c.close()
        return {r["customer_id"]: decrypt(loc.secret, loc.target, r["customer_id"], r["private_key_enc"]) for r in rows}
    path = keys_path(loc)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def ensure_keys(loc: KeyLocation) -> dict[str, str]:
    """Seeding only: create keys for agent customers that have none. Existing keys are never replaced."""
    keys = load_keys(loc)
    missing = [cid for cid in AGENT_CUSTOMERS if cid not in keys]
    if not missing:
        return keys
    if isinstance(loc, EnvKeys):
        raise KeyStoreError("the payer agent process cannot create keys")
    for cid in missing:
        keys[cid] = crypto.generate_keypair()[0]
    if isinstance(loc, PgKeys):
        from ..clock import Clock, iso

        c = _pg_conn(loc)
        try:
            for cid in missing:
                # ON CONFLICT DO NOTHING: two concurrent seeders can never overwrite an identity.
                c.execute("INSERT OR IGNORE INTO agent_keys(customer_id, private_key_enc, created_at) VALUES (?,?,?)",
                          (cid, encrypt(loc.secret, loc.target, cid, keys[cid]), iso(Clock().now())))
        finally:
            c.close()
        return load_keys(loc)
    path = keys_path(loc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keys, indent=2), encoding="utf-8")
    return keys


def public_registry(loc: KeyLocation) -> dict[str, dict[str, str]]:
    """What each customer registers with Ledgerline at onboarding: key id + public key only."""
    out = {}
    for cid, priv in ensure_keys(loc).items():
        pub = crypto.public_from_private(priv)
        out[cid] = {"key_id": crypto.key_id_for(pub), "public_key": pub}
    return out
