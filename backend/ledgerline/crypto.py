"""Ed25519 signatures over canonical JSON claims, plus approval scope hashing."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat


def canonical_json(obj: Any) -> bytes:
    """Deterministic encoding: sorted keys, no whitespace, UTF-8. Floats are refused."""

    def check(o: Any) -> None:
        if isinstance(o, float):
            raise ValueError("floats are not allowed in signed or hashed payloads")
        if isinstance(o, dict):
            for k, v in o.items():
                if not isinstance(k, str):
                    raise ValueError("object keys must be strings")
                check(v)
        elif isinstance(o, list):
            for v in o:
                check(v)

    check(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"), validate=True)


def generate_keypair() -> tuple[str, str]:
    """Returns (private_raw_b64, public_raw_b64)."""
    sk = Ed25519PrivateKey.generate()
    priv = sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return b64e(priv), b64e(pub)


def public_from_private(private_b64: str) -> str:
    sk = Ed25519PrivateKey.from_private_bytes(b64d(private_b64))
    return b64e(sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def key_id_for(public_b64: str) -> str:
    return "ed25519:" + sha256_hex(b64d(public_b64))[:16]


def sign_claim(claim: dict[str, Any], private_b64: str) -> dict[str, Any]:
    sk = Ed25519PrivateKey.from_private_bytes(b64d(private_b64))
    pub = public_from_private(private_b64)
    sig = sk.sign(canonical_json(claim))
    return {"claim": claim, "signature": b64e(sig), "key_id": key_id_for(pub), "alg": "Ed25519"}


def verify_signature(claim: dict[str, Any], signature_b64: str, public_b64: str) -> bool:
    try:
        pk = Ed25519PublicKey.from_public_bytes(b64d(public_b64))
        pk.verify(b64d(signature_b64), canonical_json(claim))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def scope_hash(scope: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(scope))
