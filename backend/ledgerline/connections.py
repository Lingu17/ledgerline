"""Each organization's own Airwallex sandbox credentials, encrypted at rest.

The AES-256-GCM key is derived from LEDGERLINE_SECRET_KEY, or from a random owner-only key file in the data
directory when that is not set. The organization id is bound in as associated data, so a ciphertext cannot be
moved to another organization. Credentials are only ever returned to the provider client, never to a browser.
The client is fixed to Airwallex's sandbox host: no setting here can reach a live account.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import Settings


class ConnectionError_(ValueError):
    """A connection that cannot be saved or read (HTTP 422)."""


def _root_secret(settings: Settings) -> str:
    if settings.sender_socket:
        raise ConnectionError_("this process does not hold the connection key; the sending service does")
    if settings.secret_key:
        return settings.secret_key
    path = settings.connections_key_path or Path(settings.data_dir) / "connections.key"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:  # another worker created it first
            return path.read_text(encoding="ascii").strip()
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(secrets.token_urlsafe(48))
    return path.read_text(encoding="ascii").strip()


def _aead(settings: Settings) -> AESGCM:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"ledgerline", info=b"org-connections v1").derive(_root_secret(settings).encode())
    return AESGCM(key)


def seal(settings: Settings, org_id: str, client_id: str, api_key: str) -> str:
    nonce = os.urandom(12)
    plain = json.dumps({"client_id": client_id, "api_key": api_key}).encode()
    return "v1:" + base64.b64encode(nonce + _aead(settings).encrypt(nonce, plain, org_id.encode())).decode()


def unseal(settings: Settings, org_id: str, blob: str) -> tuple[str, str]:
    if not blob.startswith("v1:"):
        raise ConnectionError_("unknown credential encoding")
    raw = base64.b64decode(blob[3:])
    try:
        out = json.loads(_aead(settings).decrypt(raw[:12], raw[12:], org_id.encode()))
    except Exception as exc:  # cryptography raises InvalidTag
        raise ConnectionError_("saved Airwallex credentials cannot be decrypted; connect the account again") from exc
    return out["client_id"], out["api_key"]


def discover_accounts(readiness: dict[str, Any]) -> dict[str, str]:
    """USD/EUR/GBP receiving accounts found on the account: first one per currency, single-currency accounts only."""
    found: dict[str, str] = {}
    for a in readiness.get("global_accounts", []):
        currencies = a.get("supported_currencies") or ([a["currency"]] if a.get("currency") else [])
        if len(currencies) == 1 and currencies[0] in ("USD", "EUR", "GBP"):
            found.setdefault(currencies[0], a["id"])
    return found
