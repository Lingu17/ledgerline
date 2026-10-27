"""Sign in with Google and Sign in with Apple (OpenID Connect, authorization-code flow).

The browser only ever sees the provider's consent screen and a one-time code.
The server exchanges the code with the provider's token endpoint and accepts the
ID token only after checking its RS256 signature against the provider's
published keys, its issuer, audience, expiry and the nonce bound to this
sign-in attempt. Nothing from the ID token is trusted before that.

A provider is offered only when its credentials are configured on the server:
  Google: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
  Apple:  APPLE_CLIENT_ID (Services ID), APPLE_TEAM_ID, APPLE_KEY_ID, APPLE_PRIVATE_KEY_PATH (.p8)
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from .config import Settings

CLOCK_SKEW = 120  # seconds of leeway on iat/exp


class OIDCError(ValueError):
    """A sign-in attempt that must be refused. `code` is safe to show; details go to the log."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def pkce_challenge(verifier: str) -> str:
    return b64url(hashlib.sha256(verifier.encode()).digest())


@dataclass
class Provider:
    name: str
    label: str
    client_id: str
    authorize_url: str
    token_url: str
    jwks_url: str
    issuers: frozenset[str]
    scope: str
    response_mode: str  # "query" (GET callback) or "form_post" (POST callback)
    use_pkce: bool
    client_secret: Callable[[], str]
    extra_params: dict[str, str] = field(default_factory=dict)


def apple_client_secret(team_id: str, key_id: str, client_id: str, private_key_pem: bytes, now: int | None = None) -> str:
    """Apple's client_secret is a short-lived ES256 JWT signed with the team's .p8 key."""
    now = int(now if now is not None else time.time())
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    claims = {"iss": team_id, "iat": now, "exp": now + 300, "aud": "https://appleid.apple.com", "sub": client_id}
    signing_input = f"{b64url(json.dumps(header, separators=(',', ':')).encode())}.{b64url(json.dumps(claims, separators=(',', ':')).encode())}"
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise OIDCError("misconfigured", "APPLE_PRIVATE_KEY_PATH must be an EC (P-256) .p8 key")
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    return f"{signing_input}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def configured_providers(settings: Settings) -> dict[str, Provider]:
    out: dict[str, Provider] = {}
    if settings.google_client_id and settings.google_client_secret:
        secret = settings.google_client_secret
        out["google"] = Provider(
            name="google", label="Google", client_id=settings.google_client_id,
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            jwks_url="https://www.googleapis.com/oauth2/v3/certs",
            issuers=frozenset({"https://accounts.google.com", "accounts.google.com"}),
            scope="openid email profile", response_mode="query", use_pkce=True,
            client_secret=lambda: secret, extra_params={"prompt": "select_account"},
        )
    if settings.apple_client_id and settings.apple_team_id and settings.apple_key_id and settings.apple_private_key:
        team, kid, cid, pem = settings.apple_team_id, settings.apple_key_id, settings.apple_client_id, settings.apple_private_key
        out["apple"] = Provider(
            name="apple", label="Apple", client_id=cid,
            authorize_url="https://appleid.apple.com/auth/authorize",
            token_url="https://appleid.apple.com/auth/token",
            jwks_url="https://appleid.apple.com/auth/keys",
            issuers=frozenset({"https://appleid.apple.com"}),
            # Apple only returns name/email with form_post, and only on the first authorization.
            scope="name email", response_mode="form_post", use_pkce=False,
            client_secret=lambda: apple_client_secret(team, kid, cid, pem),
        )
    return out


def authorization_url(p: Provider, *, redirect_uri: str, state: str, nonce: str, code_verifier: str | None) -> str:
    params = {"client_id": p.client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": p.scope,
              "state": state, "nonce": nonce, **p.extra_params}
    if p.response_mode != "query":
        params["response_mode"] = p.response_mode
    if p.use_pkce and code_verifier:
        params["code_challenge"] = pkce_challenge(code_verifier)
        params["code_challenge_method"] = "S256"
    return f"{p.authorize_url}?{urlencode(params)}"


class JWKSCache:
    """Provider signing keys, cached for an hour and refetched once when an unknown key id appears."""

    def __init__(self, ttl: int = 3600) -> None:
        self.ttl = ttl
        self._keys: dict[str, tuple[float, dict[str, Any]]] = {}

    def key(self, p: Provider, kid: str, http: httpx.Client) -> dict[str, Any]:
        fetched, keys = self._keys.get(p.name, (0.0, {}))
        if kid not in keys or time.time() - fetched > self.ttl:
            r = http.get(p.jwks_url)
            if r.status_code != 200:
                raise OIDCError("provider_unavailable", f"{p.name} JWKS returned {r.status_code}")
            keys = {k["kid"]: k for k in r.json().get("keys", []) if "kid" in k}
            self._keys[p.name] = (time.time(), keys)
        if kid not in keys:
            raise OIDCError("invalid_token", f"unknown signing key {kid!r}")
        return keys[kid]


def exchange_code(p: Provider, *, code: str, redirect_uri: str, code_verifier: str | None, http: httpx.Client) -> str:
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": p.client_id, "client_secret": p.client_secret()}
    if p.use_pkce and code_verifier:
        data["code_verifier"] = code_verifier
    try:
        r = http.post(p.token_url, data=data, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise OIDCError("provider_unavailable", f"{p.name} token endpoint: {exc}") from exc
    if r.status_code != 200:
        raise OIDCError("exchange_failed", f"{p.name} token endpoint returned {r.status_code}: {r.text[:200]}")
    id_token = r.json().get("id_token")
    if not isinstance(id_token, str):
        raise OIDCError("exchange_failed", f"{p.name} returned no id_token")
    return id_token


def verify_id_token(p: Provider, token: str, *, nonce: str, jwks: JWKSCache, http: httpx.Client, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    try:
        h64, c64, s64 = token.split(".")
        header = json.loads(b64url_decode(h64))
        claims = json.loads(b64url_decode(c64))
        signature = b64url_decode(s64)
    except (ValueError, json.JSONDecodeError) as exc:
        raise OIDCError("invalid_token", "malformed ID token") from exc
    if header.get("alg") != "RS256":
        raise OIDCError("invalid_token", f"unexpected alg {header.get('alg')!r}")
    jwk = jwks.key(p, str(header.get("kid", "")), http)
    if jwk.get("kty") != "RSA":
        raise OIDCError("invalid_token", "signing key is not RSA")
    public = rsa.RSAPublicNumbers(int.from_bytes(b64url_decode(jwk["e"]), "big"),
                                  int.from_bytes(b64url_decode(jwk["n"]), "big")).public_key()
    try:
        public.verify(signature, f"{h64}.{c64}".encode(), padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:  # cryptography raises InvalidSignature
        raise OIDCError("invalid_token", "ID token signature does not verify") from exc

    if claims.get("iss") not in p.issuers:
        raise OIDCError("invalid_token", f"issuer {claims.get('iss')!r}")
    aud = claims.get("aud")
    if aud != p.client_id and not (isinstance(aud, list) and p.client_id in aud):
        raise OIDCError("invalid_token", "audience is not this application")
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != p.client_id:
        raise OIDCError("invalid_token", "authorized party is not this application")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] + CLOCK_SKEW < now:
        raise OIDCError("invalid_token", "ID token expired")
    if isinstance(claims.get("iat"), (int, float)) and claims["iat"] - CLOCK_SKEW > now:
        raise OIDCError("invalid_token", "ID token issued in the future")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OIDCError("invalid_token", "nonce does not match this sign-in attempt")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise OIDCError("invalid_token", "ID token has no subject")
    return claims


def email_verified(claims: dict[str, Any]) -> bool:
    # Google sends a boolean; Apple sends a boolean or the string "true".
    v = claims.get("email_verified")
    return v is True or v == "true"
