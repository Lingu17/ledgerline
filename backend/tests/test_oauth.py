"""Sign in with Google / Apple against fake providers that sign real RS256 ID tokens.

Nothing here reaches Google or Apple: an httpx MockTransport plays their token and
JWKS endpoints. What is exercised is our side: state, browser binding, nonce,
signature/issuer/audience/expiry checks, account creation and linking rules.
"""
from __future__ import annotations

import base64
import json
import secrets
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi.testclient import TestClient

from ledgerline.api.app import create_app
from ledgerline.config import load_settings
from ledgerline.oidc import b64url, b64url_decode

from .conftest import PASSWORD, signup

GOOGLE_ID = "ledgerline-test.apps.googleusercontent.com"
APPLE_ID = "test.ledgerline.signin"


class FakeIdP:
    def __init__(self, iss: str, aud: str) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = secrets.token_hex(6)  # unique per test: the JWKS cache is process-wide
        self.iss, self.aud = iss, aud
        self.nonce = ""
        self.sub = "1000001"
        self.email = "dana@gmail.test"
        self.overrides: dict = {}
        self.sign_with = self.key
        self.token_requests: list[dict] = []

    def jwks(self) -> dict:
        pub = self.key.public_key().public_numbers()
        return {"keys": [{"kty": "RSA", "kid": self.kid, "alg": "RS256", "use": "sig",
                          "n": b64url(pub.n.to_bytes((pub.n.bit_length() + 7) // 8, "big")), "e": b64url(pub.e.to_bytes(3, "big"))}]}

    def id_token(self) -> str:
        now = int(time.time())
        claims = {"iss": self.iss, "aud": self.aud, "sub": self.sub, "email": self.email, "email_verified": True,
                  "nonce": self.nonce, "iat": now, "exp": now + 600, "name": "Dana Okafor", **self.overrides}
        header = {"alg": "RS256", "kid": self.kid, "typ": "JWT"}
        signing_input = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(claims).encode())}"
        sig = self.sign_with.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{signing_input}.{b64url(sig)}"


@pytest.fixture
def idps():
    return {"google": FakeIdP("https://accounts.google.com", GOOGLE_ID),
            "apple": FakeIdP("https://appleid.apple.com", APPLE_ID)}


@pytest.fixture
def apple_key(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path / "AuthKey_TEST.p8"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return key, path


def make_app(tmp_path, idps, apple_key, **extra):
    settings = load_settings({
        "LEDGERLINE_DATA_DIR": str(tmp_path / "data"), "LEDGERLINE_PAYER_MCP_TRANSPORT": "memory",
        "LEDGERLINE_SAMPLE_WORKSPACE": "0", "ANTHROPIC_API_KEY": "", "AIRWALLEX_CLIENT_ID": "", "AIRWALLEX_API_KEY": "",
        "GOOGLE_CLIENT_ID": GOOGLE_ID, "GOOGLE_CLIENT_SECRET": "test-google-secret",
        "APPLE_CLIENT_ID": APPLE_ID, "APPLE_TEAM_ID": "TEAM123456", "APPLE_KEY_ID": "KEY1234567",
        "APPLE_PRIVATE_KEY_PATH": str(apple_key[1]), "LEDGERLINE_PUBLIC_URL": "http://localhost:8000", **extra,
    })
    app = create_app(settings)
    routes = {"oauth2.googleapis.com": ("google", "token"), "www.googleapis.com": ("google", "jwks"),
              "appleid.apple.com": ("apple", None)}

    def handler(request: httpx.Request) -> httpx.Response:
        name, kind = routes[request.url.host]
        idp = idps[name]
        if kind == "jwks" or request.url.path == "/auth/keys":
            return httpx.Response(200, json=idp.jwks())
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        idp.token_requests.append(form)
        if form.get("code") == "bad-code":
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(200, json={"access_token": "x", "token_type": "Bearer", "id_token": idp.id_token()})

    app.state.oidc_transport = httpx.MockTransport(handler)
    return app


@pytest.fixture
def app(tmp_path, idps, apple_key):
    return make_app(tmp_path, idps, apple_key)


def begin(client, provider, **params):
    r = client.get(f"/api/auth/oauth/{provider}/start", params=params, follow_redirects=False)
    assert r.status_code == 302, r.text
    return {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}, r


def google_signin(client, idps, code="code-1", **params):
    q, _ = begin(client, "google", **params)
    idps["google"].nonce = q["nonce"]
    return client.get("/api/auth/oauth/google/callback", params={"code": code, "state": q["state"]}, follow_redirects=False)


def error_of(r) -> str | None:
    loc = r.headers.get("location", "")
    return parse_qs(loc.split("?", 1)[1]).get("oauth_error", [None])[0] if "?" in loc else None


def test_providers_report_configuration(app, tmp_path):
    assert TestClient(app).get("/api/auth/providers").json() == {"google": {"configured": True}, "apple": {"configured": True}}
    bare = create_app(load_settings({"LEDGERLINE_DATA_DIR": str(tmp_path / "bare"), "GOOGLE_CLIENT_ID": "", "APPLE_CLIENT_ID": ""}))
    c = TestClient(bare)
    assert c.get("/api/auth/providers").json() == {"google": {"configured": False}, "apple": {"configured": False}}
    r = c.get("/api/auth/oauth/google/start", follow_redirects=False)
    assert r.status_code == 303 and error_of(r) == "not_configured"


def test_google_start_redirect_carries_state_nonce_pkce_and_binding_cookie(app):
    c = TestClient(app)
    q, r = begin(c, "google")
    assert r.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert q["client_id"] == GOOGLE_ID and q["response_type"] == "code" and q["scope"] == "openid email profile"
    assert q["redirect_uri"] == "http://localhost:8000/api/auth/oauth/google/callback"
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert len(q["state"]) >= 40 and len(q["nonce"]) >= 30
    cookie = r.headers["set-cookie"]
    assert "ll_oauth=" in cookie and "HttpOnly" in cookie and "Path=/api/auth/oauth" in cookie


def test_new_google_user_is_created_signed_in_and_lands_without_organization(app, idps):
    c = TestClient(app)
    r = google_signin(c, idps)
    assert r.status_code == 303 and r.headers["location"] == "/#/inbox", r.headers
    assert "ll_session=" in r.headers["set-cookie"]
    me = c.get("/api/auth/me").json()
    assert me["user"]["email"] == "dana@gmail.test" and me["user"]["name"] == "Dana Okafor" and me["organization"] is None
    # Token request was a server-side code exchange carrying the secret and the PKCE verifier.
    form = idps["google"].token_requests[-1]
    assert form["grant_type"] == "authorization_code" and form["client_secret"] == "test-google-secret" and form["code_verifier"]
    # The new account has no password: password sign-in fails even with a guess.
    assert c.post("/api/auth/login", json={"email": "dana@gmail.test", "password": PASSWORD}).status_code == 401
    # Next Google sign-in reaches the same user.
    c2 = TestClient(app)
    google_signin(c2, idps, code="code-2")
    assert c2.get("/api/auth/me").json()["user"]["id"] == me["user"]["id"]


def test_state_is_single_use_and_bound_to_the_starting_browser(app, idps):
    c = TestClient(app)
    q, _ = begin(c, "google")
    idps["google"].nonce = q["nonce"]
    # Another browser (no binding cookie) cannot complete this attempt, and the attempt is burned.
    attacker = TestClient(app)
    r = attacker.get("/api/auth/oauth/google/callback", params={"code": "x", "state": q["state"]}, follow_redirects=False)
    assert error_of(r) == "browser_mismatch"
    r = c.get("/api/auth/oauth/google/callback", params={"code": "x", "state": q["state"]}, follow_redirects=False)
    assert error_of(r) == "state_reused"
    assert "ll_session" not in c.cookies
    # Unknown state, and a state from the other provider, are refused.
    assert error_of(c.get("/api/auth/oauth/google/callback", params={"code": "x", "state": "nope"}, follow_redirects=False)) == "unknown_state"
    q2, _ = begin(c, "apple")
    r = c.get("/api/auth/oauth/google/callback", params={"code": "x", "state": q2["state"]}, follow_redirects=False)
    assert error_of(r) == "unknown_state"


def test_expired_attempt_is_refused(app, idps):
    c = TestClient(app)
    q, _ = begin(c, "google")
    from datetime import timedelta
    app.state.control.clock.advance(timedelta(minutes=11))
    r = c.get("/api/auth/oauth/google/callback", params={"code": "x", "state": q["state"]}, follow_redirects=False)
    assert error_of(r) == "state_expired"


@pytest.mark.parametrize("tamper,expected", [
    ({"nonce": "someone-elses-nonce"}, "invalid_token"),
    ({"aud": "another-app.apps.googleusercontent.com"}, "invalid_token"),
    ({"iss": "https://evil.example"}, "invalid_token"),
    ({"exp": int(time.time()) - 3600}, "invalid_token"),
    ({"email_verified": False}, "email_unverified"),
])
def test_id_token_claims_are_enforced(app, idps, tamper, expected):
    idps["google"].overrides = tamper
    c = TestClient(app)
    r = google_signin(c, idps)
    assert error_of(r) == expected and "ll_session" not in c.cookies


def test_signature_from_a_different_key_is_refused(app, idps):
    idps["google"].sign_with = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    c = TestClient(app)
    assert error_of(google_signin(c, idps)) == "invalid_token"


def test_failed_code_exchange_and_user_cancel(app, idps):
    c = TestClient(app)
    assert error_of(google_signin(c, idps, code="bad-code")) == "exchange_failed"
    q, _ = begin(c, "google")
    r = c.get("/api/auth/oauth/google/callback", params={"error": "access_denied", "state": q["state"]}, follow_redirects=False)
    assert error_of(r) == "cancelled"


def test_existing_password_account_is_never_auto_linked_by_email(app, idps):
    owner = TestClient(app)
    signup(owner, email="dana@gmail.test")
    c = TestClient(app)
    r = google_signin(c, idps)
    assert error_of(r) == "account_exists" and "ll_session" not in c.cookies


def test_signed_in_user_links_google_from_settings_then_signs_in_with_it(app, idps):
    owner = TestClient(app)
    me = signup(owner, email="owner@northbeam.test")
    idps["google"].email = "northbeam.owner@gmail.test"
    q, _ = begin(owner, "google", intent="link")
    idps["google"].nonce = q["nonce"]
    r = owner.get("/api/auth/oauth/google/callback", params={"code": "c", "state": q["state"]}, follow_redirects=False)
    assert r.headers["location"] == "/#/settings?oauth_linked=google"
    ids = owner.get("/api/auth/identities").json()
    assert ids["has_password"] and [i["provider"] for i in ids["identities"]] == ["google"]
    fresh = TestClient(app)
    google_signin(fresh, idps, code="c2")
    got = fresh.get("/api/auth/me").json()
    assert got["user"]["id"] == me["user"]["id"] and got["organization"]["id"] == owner.org_id
    # The same Google account cannot be linked to a second user.
    other = TestClient(app)
    signup(other, email="other@northbeam.test", org="Other Co")
    q, _ = begin(other, "google", intent="link")
    idps["google"].nonce = q["nonce"]
    r = other.get("/api/auth/oauth/google/callback", params={"code": "c3", "state": q["state"]}, follow_redirects=False)
    assert error_of(r) == "identity_in_use"


def test_link_requires_a_session_and_unlink_keeps_one_way_in(app, idps):
    anon = TestClient(app)
    r = anon.get("/api/auth/oauth/google/start", params={"intent": "link"}, follow_redirects=False)
    assert error_of(r) == "signin_required"
    c = TestClient(app)
    google_signin(c, idps)
    c.headers["X-CSRF-Token"] = c.get("/api/auth/me").json()["csrf_token"]
    r = c.delete("/api/auth/identities/google")
    assert r.status_code == 409 and "only way" in r.json()["detail"]
    assert c.delete("/api/auth/identities/google", headers={"X-CSRF-Token": "wrong"}).status_code == 403


def test_open_redirects_are_not_followed(app, idps):
    c = TestClient(app)
    r = google_signin(c, idps, return_to="https://evil.example/#/inbox")
    assert r.headers["location"] == "/#/inbox"


def test_signup_disabled_blocks_new_oauth_accounts(tmp_path, idps, apple_key):
    app = make_app(tmp_path, idps, apple_key, LEDGERLINE_ALLOW_SIGNUP="0")
    assert error_of(google_signin(TestClient(app), idps)) == "signup_disabled"


def test_apple_form_post_callback_with_signed_client_secret(app, idps, apple_key):
    c = TestClient(app)
    q, r = begin(c, "apple")
    assert r.headers["location"].startswith("https://appleid.apple.com/auth/authorize?")
    assert q["response_mode"] == "form_post" and q["scope"] == "name email" and "code_challenge" not in q
    apple = idps["apple"]
    apple.nonce, apple.sub, apple.email = q["nonce"], "001234.abcd.0001", "x7p2k@privaterelay.appleid.com"
    apple.overrides = {"email_verified": "true", "name": None}
    r = c.post("/api/auth/oauth/apple/callback", follow_redirects=False,
               data={"code": "apple-code", "state": q["state"],
                     "user": json.dumps({"name": {"firstName": "Sam", "lastName": "Reyes"}, "email": "x7p2k@privaterelay.appleid.com"})},
               headers={"Origin": "https://appleid.apple.com"})
    assert r.status_code == 303 and r.headers["location"] == "/#/inbox", r.headers
    me = c.get("/api/auth/me").json()
    assert me["user"]["email"] == "x7p2k@privaterelay.appleid.com" and me["user"]["name"] == "Sam Reyes"

    # The client_secret Apple received is an ES256 JWT signed by our .p8 key with Apple's required claims.
    secret = apple.token_requests[-1]["client_secret"]
    h, cl, s = secret.split(".")
    header, claims, sig = json.loads(b64url_decode(h)), json.loads(b64url_decode(cl)), b64url_decode(s)
    assert header == {"alg": "ES256", "kid": "KEY1234567", "typ": "JWT"}
    assert claims["iss"] == "TEAM123456" and claims["sub"] == APPLE_ID and claims["aud"] == "https://appleid.apple.com"
    assert 0 < claims["exp"] - claims["iat"] <= 15777000
    der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
    apple_key[0].public_key().verify(der, f"{h}.{cl}".encode(), ec.ECDSA(hashes.SHA256()))


def test_invited_google_user_joins_without_a_password(app, idps):
    owner = TestClient(app)
    signup(owner)
    path = owner.post("/api/team/invitations", json={"email": "dana@gmail.test", "role": "viewer"}).json()["invite_path"]
    invite_token = path.split("token=")[1]
    c = TestClient(app)
    r = google_signin(c, idps, return_to=f"/#/invite?token={invite_token}")
    assert r.headers["location"] == f"/#/invite?token={invite_token}"
    c.headers["X-CSRF-Token"] = c.get("/api/auth/me").json()["csrf_token"]
    assert c.post(f"/api/invitations/{invite_token}/accept-signed-in").json() == {"joined": owner.org_id}
    me = c.get("/api/auth/me").json()
    assert me["organization"]["id"] == owner.org_id and me["role"] == "viewer"
    # Single use, and only for the invited address.
    assert c.post(f"/api/invitations/{invite_token}/accept-signed-in").status_code == 404
    path2 = owner.post("/api/team/invitations", json={"email": "someone.else@gmail.test", "role": "owner"}).json()["invite_path"]
    r = c.post(f"/api/invitations/{path2.split('token=')[1]}/accept-signed-in")
    assert r.status_code == 403
