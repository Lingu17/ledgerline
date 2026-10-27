"""Control plane: users, organizations, memberships, sessions, invitations and login throttling.

Lives in its own SQLite database. Tenant financial data never lives here; each
organization has a separate tenant database (see tenancy.py).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterator

from . import db
from .clock import Clock, iso, parse_iso
from .migrations import CONTROL, migrate

ROLES = ("owner", "operator", "viewer")
ROLE_RANK = {"viewer": 0, "operator": 1, "owner": 2}

SESSION_ABSOLUTE = timedelta(hours=12)
SESSION_IDLE = timedelta(hours=2)
INVITE_TTL = timedelta(days=3)
THROTTLE_WINDOW = timedelta(minutes=15)
THROTTLE_MAX_FAILURES = 5
MIN_PASSWORD = 12
OAUTH_STATE_TTL = timedelta(minutes=10)
# Accounts created through Google/Apple have no password; this marker never verifies (see verify_password).
NO_PASSWORD = "none$oauth-only"

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")


class AuthError(ValueError):
    """Authentication or authorization failure."""

    def __init__(self, status: int, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


# --------------------------------------------------------------------------- passwords
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return "scrypt${n}${r}${p}${salt}${dk}".format(
        salt=base64.b64encode(salt).decode(), dk=base64.b64encode(digest).decode(), **_SCRYPT)


def verify_password(password: str, encoded: str) -> bool:
    try:
        alg, n, r, p, salt, dk = encoded.split("$")
        if alg != "scrypt":
            return False
        expected = base64.b64decode(dk)
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(got, expected)
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def validate_password(password: Any) -> str:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD or len(password) > 256:
        raise AuthError(422, f"password must be {MIN_PASSWORD}-256 characters")
    if password.lower() == password or password.upper() == password or not re.search(r"\d", password):
        raise AuthError(422, "password needs upper- and lower-case letters and a digit")
    return password


def validate_email(email: Any) -> str:
    if not isinstance(email, str) or not _EMAIL_RE.match(email.strip()):
        raise AuthError(422, "enter a valid email address")
    return email.strip().lower()


def _text(value: Any, field: str, lo: int, hi: int) -> str:
    if not isinstance(value, str) or not lo <= len(value.strip()) <= hi:
        raise AuthError(422, f"{field} must be {lo}-{hi} characters")
    return value.strip()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --------------------------------------------------------------------------- store
@dataclass
class SessionInfo:
    user_id: str
    email: str
    name: str
    org_id: str | None
    role: str | None
    csrf_token: str
    expires_at: str


class ControlPlane:
    def __init__(self, path: Path, clock: Clock | None = None) -> None:
        self.path = path
        self.clock = clock or Clock()
        with self.conn() as c:
            migrate(c, CONTROL)

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = db.connect(self.path)
        try:
            yield c
        finally:
            c.close()

    def now(self) -> str:
        return iso(self.clock.now())

    def _audit(self, c: sqlite3.Connection, actor: str, action: str, org_id: str | None, detail: dict[str, Any]) -> None:
        c.execute("INSERT INTO control_audit(at, actor, org_id, action, detail) VALUES (?,?,?,?,?)",
                  (self.now(), actor, org_id, action, json.dumps(detail, sort_keys=True)))

    # ---------------------------------------------------------------- Claude budget
    def reserve_claude_call(self, org_id: str, org_limit: int, server_limit: int) -> int:
        """Reserve one Claude call before it is dispatched. Every reservation counts against today's budget
        whatever its outcome (a failed or interrupted call may still have been billed), and the check and the
        insert share one serialized transaction, so concurrent requests cannot overspend."""
        day = self.clock.now().strftime("%Y-%m-%d")
        with self.conn() as c, db.transaction(c):
            org_used = c.execute("SELECT COUNT(*) FROM claude_calls WHERE day = ? AND org_id = ?", (day, org_id)).fetchone()[0]
            if org_used >= org_limit:
                raise ValueError(f"this organization has used its {org_limit} Claude reads for today; try again tomorrow")
            server_used = c.execute("SELECT COUNT(*) FROM claude_calls WHERE day = ?", (day,)).fetchone()[0]
            if server_used >= server_limit:
                raise ValueError("this server has reached its daily Claude budget; try again tomorrow")
            c.execute("INSERT INTO claude_calls(org_id, day, status, reserved_at) VALUES (?,?,?,?)",
                      (org_id, day, "reserved", self.now()))
            return int(c.execute("SELECT MAX(id) FROM claude_calls WHERE org_id = ? AND day = ?", (org_id, day)).fetchone()[0])

    def settle_claude_call(self, call_id: int, ok: bool, detail: str = "") -> None:
        with self.conn() as c, db.transaction(c):
            c.execute("UPDATE claude_calls SET status = ?, settled_at = ?, detail = ? WHERE id = ? AND status = 'reserved'",
                      ("succeeded" if ok else "failed", self.now(), detail[:300], call_id))

    # ---------------------------------------------------------------- orgs
    def _insert_org(self, c: sqlite3.Connection, name: str, kind: str, user_id: str) -> str:
        org_id = "org_" + uuid.uuid4().hex[:12]
        c.execute("INSERT INTO organizations(id, name, kind, webhook_secret_local, created_by, created_at) VALUES (?,?,?,?,?,?)",
                  (org_id, name, kind, secrets.token_urlsafe(32), user_id, self.now()))
        c.execute("INSERT INTO memberships VALUES (?,?,?,?)", (user_id, org_id, "owner", self.now()))
        return org_id

    def org(self, org_id: str) -> dict[str, Any] | None:
        with self.conn() as c:
            return db.row(c, "SELECT * FROM organizations WHERE id = ?", (org_id,))

    def all_org_ids(self) -> list[str]:
        with self.conn() as c:
            return [r["id"] for r in db.rows(c, "SELECT id FROM organizations")]

    def create_org(self, user_id: str, name: Any, kind: str) -> str:
        name = _text(name, "organization name", 2, 80)
        if kind not in ("workspace", "sample"):
            raise AuthError(422, "kind must be 'workspace' or 'sample'")
        with self.conn() as c, db.transaction(c):
            org_id = self._insert_org(c, name, kind, user_id)
            self._audit(c, user_id, "org.created", org_id, {"name": name, "kind": kind})
            return org_id

    def update_org_settings(self, org_id: str, actor: str, body: dict[str, Any], *, sandbox_available: bool) -> dict[str, Any]:
        with self.conn() as c, db.transaction(c):
            org = db.row(c, "SELECT * FROM organizations WHERE id = ?", (org_id,))
            if org is None:
                raise AuthError(404, "unknown organization")
            changes: dict[str, Any] = {}
            if "name" in body:
                changes["name"] = _text(body["name"], "organization name", 2, 80)
            if "bank_mode" in body:
                if body["bank_mode"] not in ("local", "airwallex_sandbox"):
                    raise AuthError(422, "bank_mode must be local or airwallex_sandbox")
                if body["bank_mode"] == "airwallex_sandbox" and not sandbox_available:
                    raise AuthError(422, "Airwallex sandbox credentials are not configured on this server")
                changes["bank_mode"] = body["bank_mode"]
            if "airwallex_global_accounts" in body:
                ga = body["airwallex_global_accounts"]
                if not isinstance(ga, dict) or not all(k in ("USD", "EUR", "GBP") and isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_-]{0,64}", v) for k, v in ga.items()):
                    raise AuthError(422, "global accounts must map USD/EUR/GBP to account ids")
                changes["airwallex_global_accounts"] = json.dumps({k: v for k, v in ga.items() if v})
            if "airwallex_webhook_secret" in body:
                secret = body["airwallex_webhook_secret"]
                if secret is not None and (not isinstance(secret, str) or not 8 <= len(secret) <= 200):
                    raise AuthError(422, "webhook secret must be 8-200 characters, or null to clear")
                changes["airwallex_webhook_secret"] = secret
            for k, v in changes.items():
                c.execute(f"UPDATE organizations SET {k} = ? WHERE id = ?", (v, org_id))  # keys are whitelisted above
            self._audit(c, actor, "org.settings_updated", org_id,
                        {k: ("<set>" if k == "airwallex_webhook_secret" and v else v) for k, v in changes.items()})
            return db.row(c, "SELECT * FROM organizations WHERE id = ?", (org_id,))

    # ---------------------------------------------------------------- users & sessions
    def signup(self, *, email: Any, name: Any, password: Any, org_name: Any, kind: str, user_agent: str = "") -> tuple[str, str]:
        email = validate_email(email)
        name = _text(name, "name", 1, 80)
        validate_password(password)
        org_name = _text(org_name, "organization name", 2, 80)
        if kind not in ("workspace", "sample"):
            raise AuthError(422, "kind must be 'workspace' or 'sample'")
        with self.conn() as c, db.transaction(c):
            if db.row(c, "SELECT id FROM users WHERE email = ?", (email,)):
                raise AuthError(409, "an account with this email already exists; sign in instead")
            user_id = "usr_" + uuid.uuid4().hex[:12]
            c.execute("INSERT INTO users(id, email, name, password_hash, created_at, password_changed_at) VALUES (?,?,?,?,?,?)",
                      (user_id, email, name, hash_password(password), self.now(), self.now()))
            org_id = self._insert_org(c, org_name, kind, user_id)
            self._audit(c, email, "user.signup", org_id, {"org_name": org_name, "kind": kind})
            token = self._new_session(c, user_id, org_id, user_agent)
            return token, org_id

    def _new_session(self, c: sqlite3.Connection, user_id: str, org_id: str | None, user_agent: str) -> str:
        token = secrets.token_urlsafe(32)
        now = self.clock.now()
        c.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,NULL,?)",
                  (token_hash(token), user_id, org_id, secrets.token_urlsafe(24), iso(now), iso(now),
                   iso(now + SESSION_ABSOLUTE), user_agent[:200]))
        return token

    def _throttle_keys(self, email: str, ip: str) -> list[str]:
        return [f"email:{email}", f"ip:{ip}"]

    def login(self, *, email: Any, password: Any, ip: str, user_agent: str = "") -> str:
        email_n = email.strip().lower() if isinstance(email, str) else ""
        keys = self._throttle_keys(email_n, ip)
        since = iso(self.clock.now() - THROTTLE_WINDOW)
        with self.conn() as c, db.transaction(c):
            for k in keys:
                fails = db.rows(c, "SELECT at FROM login_failures WHERE key = ? AND at > ? ORDER BY at", (k, since))
                if len(fails) >= THROTTLE_MAX_FAILURES:
                    retry = int((parse_iso(fails[0]["at"]) + THROTTLE_WINDOW - self.clock.now()).total_seconds()) + 1
                    raise AuthError(429, "too many failed sign-in attempts; try again later", retry_after=max(retry, 1))
            user = db.row(c, "SELECT * FROM users WHERE email = ?", (email_n,))
            ok = verify_password(password if isinstance(password, str) else "", user["password_hash"] if user else _DUMMY_HASH)
            if not user or not ok or user["disabled"]:
                for k in keys:
                    c.execute("INSERT INTO login_failures(key, at) VALUES (?,?)", (k, self.now()))
                self._audit(c, email_n or "?", "login.failed", None, {"ip": ip})
                # Committed failure count must survive the raise: commit happens via the context manager below.
                failed = True
            else:
                failed = False
                c.execute("DELETE FROM login_failures WHERE key = ?", (f"email:{email_n}",))
                membership = db.row(c, "SELECT org_id FROM memberships WHERE user_id = ? ORDER BY created_at LIMIT 1", (user["id"],))
                token = self._new_session(c, user["id"], membership["org_id"] if membership else None, user_agent)
                self._audit(c, email_n, "login.succeeded", membership["org_id"] if membership else None, {"ip": ip})
        if failed:
            raise AuthError(401, "email or password is incorrect")
        return token

    def authenticate(self, token: str | None) -> SessionInfo | None:
        if not token:
            return None
        with self.conn() as c:
            s = db.row(c, """SELECT s.*, u.email, u.name, u.disabled, u.password_changed_at FROM sessions s
                             JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?""", (token_hash(token),))
            if s is None or s["revoked_at"] or s["disabled"]:
                return None
            now = self.clock.now()
            if parse_iso(s["expires_at"]) <= now or parse_iso(s["last_seen_at"]) + SESSION_IDLE <= now:
                return None
            role = None
            if s["org_id"]:
                m = db.row(c, "SELECT role FROM memberships WHERE user_id = ? AND org_id = ?", (s["user_id"], s["org_id"]))
                role = m["role"] if m else None
            if (now - parse_iso(s["last_seen_at"])).total_seconds() > 60:
                c.execute("UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?", (iso(now), s["token_hash"]))
            return SessionInfo(s["user_id"], s["email"], s["name"], s["org_id"] if role else None, role, s["csrf_token"], s["expires_at"])

    def logout(self, token: str) -> None:
        with self.conn() as c, db.transaction(c):
            c.execute("UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL", (self.now(), token_hash(token)))

    def switch_org(self, token: str, org_id: str) -> None:
        with self.conn() as c, db.transaction(c):
            s = db.row(c, "SELECT user_id FROM sessions WHERE token_hash = ?", (token_hash(token),))
            if not s or not db.row(c, "SELECT 1 FROM memberships WHERE user_id = ? AND org_id = ?", (s["user_id"], org_id)):
                raise AuthError(403, "you are not a member of that organization")
            c.execute("UPDATE sessions SET org_id = ? WHERE token_hash = ?", (org_id, token_hash(token)))

    def change_password(self, user_id: str, current: Any, new: Any, keep_token: str) -> None:
        validate_password(new)
        with self.conn() as c, db.transaction(c):
            u = db.row(c, "SELECT * FROM users WHERE id = ?", (user_id,))
            if not u or not verify_password(current if isinstance(current, str) else "", u["password_hash"]):
                raise AuthError(403, "current password is incorrect")
            c.execute("UPDATE users SET password_hash = ?, password_changed_at = ? WHERE id = ?", (hash_password(new), self.now(), user_id))
            c.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND token_hash != ? AND revoked_at IS NULL",
                      (self.now(), user_id, token_hash(keep_token)))
            self._audit(c, u["email"], "user.password_changed", None, {"other_sessions_revoked": True})

    def user_orgs(self, user_id: str) -> list[dict[str, Any]]:
        with self.conn() as c:
            return db.rows(c, """SELECT o.id, o.name, o.kind, m.role FROM memberships m JOIN organizations o ON o.id = m.org_id
                                 WHERE m.user_id = ? ORDER BY o.created_at""", (user_id,))

    # ---------------------------------------------------------------- members & invitations
    def members(self, org_id: str) -> list[dict[str, Any]]:
        with self.conn() as c:
            return db.rows(c, """SELECT u.id AS user_id, u.email, u.name, m.role, m.created_at FROM memberships m
                                 JOIN users u ON u.id = m.user_id WHERE m.org_id = ? ORDER BY m.created_at""", (org_id,))

    def invitations(self, org_id: str) -> list[dict[str, Any]]:
        with self.conn() as c:
            return db.rows(c, """SELECT substr(token_hash, 1, 12) AS id, email, role, invited_by, created_at, expires_at
                                 FROM invitations WHERE org_id = ? AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > ?
                                 ORDER BY created_at""", (org_id, self.now()))

    def invite(self, org_id: str, actor_id: str, email: Any, role: Any) -> str:
        email = validate_email(email)
        if role not in ROLES:
            raise AuthError(422, "role must be owner, operator or viewer")
        with self.conn() as c, db.transaction(c):
            existing = db.row(c, """SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.org_id = ? AND u.email = ?""", (org_id, email))
            if existing:
                raise AuthError(409, "that person is already a member")
            c.execute("UPDATE invitations SET revoked_at = ? WHERE org_id = ? AND email = ? AND accepted_at IS NULL AND revoked_at IS NULL",
                      (self.now(), org_id, email))
            token = secrets.token_urlsafe(32)
            c.execute("INSERT INTO invitations VALUES (?,?,?,?,?,?,?,NULL,NULL)",
                      (token_hash(token), org_id, email, role, actor_id, self.now(), iso(self.clock.now() + INVITE_TTL)))
            self._audit(c, actor_id, "member.invited", org_id, {"email": email, "role": role})
            return token

    def revoke_invitation(self, org_id: str, actor_id: str, invite_id: str) -> None:
        with self.conn() as c, db.transaction(c):
            n = c.execute("UPDATE invitations SET revoked_at = ? WHERE org_id = ? AND substr(token_hash,1,12) = ? AND accepted_at IS NULL AND revoked_at IS NULL",
                          (self.now(), org_id, invite_id)).rowcount
            if not n:
                raise AuthError(404, "no open invitation with that id")
            self._audit(c, actor_id, "member.invitation_revoked", org_id, {"invite": invite_id})

    def invitation_info(self, token: str) -> dict[str, Any]:
        with self.conn() as c:
            inv = db.row(c, """SELECT i.email, i.role, i.expires_at, o.name AS org_name,
                                      (SELECT 1 FROM users u WHERE u.email = i.email) AS existing_user
                               FROM invitations i JOIN organizations o ON o.id = i.org_id
                               WHERE i.token_hash = ? AND i.accepted_at IS NULL AND i.revoked_at IS NULL AND i.expires_at > ?""",
                         (token_hash(token), self.now()))
        if not inv:
            raise AuthError(404, "this invitation is invalid, used or expired")
        return {**inv, "existing_user": bool(inv["existing_user"])}

    def _check_invitation_password(self, email: str, password: Any, ip: str) -> None:
        """Existing-account invitations share login's failure budget.

        Commit failed attempts before raising, otherwise the transaction rollback
        would silently make the invitation endpoint an unlimited password oracle.
        """
        keys = self._throttle_keys(email, ip)
        since = iso(self.clock.now() - THROTTLE_WINDOW)
        with self.conn() as c, db.transaction(c):
            for key in keys:
                fails = db.rows(c, "SELECT at FROM login_failures WHERE key = ? AND at > ? ORDER BY at", (key, since))
                if len(fails) >= THROTTLE_MAX_FAILURES:
                    retry = int((parse_iso(fails[0]["at"]) + THROTTLE_WINDOW - self.clock.now()).total_seconds()) + 1
                    raise AuthError(429, "too many failed sign-in attempts; try again later", retry_after=max(1, retry))
            user = db.row(c, "SELECT * FROM users WHERE email = ?", (email,))
            valid = verify_password(password if isinstance(password, str) else "", user["password_hash"] if user else _DUMMY_HASH)
            failed = not user or not valid or bool(user["disabled"])
            if failed:
                for key in keys:
                    c.execute("INSERT INTO login_failures(key, at) VALUES (?,?)", (key, self.now()))
                self._audit(c, email, "invitation.authentication_failed", None, {"ip": ip})
        if failed:
            raise AuthError(403, "enter your existing Ledgerline password to join")

    def accept_invitation(self, token: str, *, name: Any, password: Any, user_agent: str = "", ip: str = "unknown") -> str:
        preview = self.invitation_info(token)
        if preview["existing_user"]:
            self._check_invitation_password(preview["email"], password, ip)
        with self.conn() as c, db.transaction(c):
            inv = db.row(c, "SELECT * FROM invitations WHERE token_hash = ? AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > ?",
                         (token_hash(token), self.now()))
            if not inv:
                raise AuthError(404, "this invitation is invalid, used or expired")
            user = db.row(c, "SELECT * FROM users WHERE email = ?", (inv["email"],))
            if user:
                if not verify_password(password if isinstance(password, str) else "", user["password_hash"]):
                    raise AuthError(403, "enter your existing Ledgerline password to join")
                user_id = user["id"]
            else:
                name = _text(name, "name", 1, 80)
                validate_password(password)
                user_id = "usr_" + uuid.uuid4().hex[:12]
                c.execute("INSERT INTO users(id, email, name, password_hash, created_at, password_changed_at) VALUES (?,?,?,?,?,?)",
                          (user_id, inv["email"], name, hash_password(password), self.now(), self.now()))
            c.execute("INSERT OR IGNORE INTO memberships VALUES (?,?,?,?)", (user_id, inv["org_id"], inv["role"], self.now()))
            c.execute("UPDATE invitations SET accepted_at = ? WHERE token_hash = ?", (self.now(), token_hash(token)))
            self._audit(c, inv["email"], "member.joined", inv["org_id"], {"role": inv["role"]})
            return self._new_session(c, user_id, inv["org_id"], user_agent)

    def _owners(self, c: sqlite3.Connection, org_id: str) -> int:
        return int(c.execute("SELECT COUNT(*) FROM memberships WHERE org_id = ? AND role = 'owner'", (org_id,)).fetchone()[0])

    def set_role(self, org_id: str, actor_id: str, user_id: str, role: Any) -> None:
        if role not in ROLES:
            raise AuthError(422, "role must be owner, operator or viewer")
        with self.conn() as c, db.transaction(c):
            m = db.row(c, "SELECT role FROM memberships WHERE org_id = ? AND user_id = ?", (org_id, user_id))
            if not m:
                raise AuthError(404, "not a member of this organization")
            if m["role"] == "owner" and role != "owner" and self._owners(c, org_id) == 1:
                raise AuthError(409, "an organization needs at least one owner")
            c.execute("UPDATE memberships SET role = ? WHERE org_id = ? AND user_id = ?", (role, org_id, user_id))
            self._audit(c, actor_id, "member.role_changed", org_id, {"user_id": user_id, "from": m["role"], "to": role})

    def remove_member(self, org_id: str, actor_id: str, user_id: str) -> None:
        with self.conn() as c, db.transaction(c):
            m = db.row(c, "SELECT role FROM memberships WHERE org_id = ? AND user_id = ?", (org_id, user_id))
            if not m:
                raise AuthError(404, "not a member of this organization")
            if m["role"] == "owner" and self._owners(c, org_id) == 1:
                raise AuthError(409, "an organization needs at least one owner")
            c.execute("DELETE FROM memberships WHERE org_id = ? AND user_id = ?", (org_id, user_id))
            c.execute("UPDATE sessions SET org_id = NULL WHERE user_id = ? AND org_id = ?", (user_id, org_id))
            self._audit(c, actor_id, "member.removed", org_id, {"user_id": user_id})

    def control_audit(self, org_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.conn() as c:
            return db.rows(c, "SELECT * FROM control_audit WHERE org_id = ? ORDER BY id DESC LIMIT ?", (org_id, limit))

    # ---------------------------------------------------------------- sign in with Google / Apple
    def oauth_begin(self, *, provider: str, binding: str, intent: str, link_user_id: str | None, return_to: str,
                    use_pkce: bool) -> tuple[str, str, str | None]:
        """Create a single-use sign-in attempt. Returns (state, nonce, code_verifier)."""
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(48) if use_pkce else None
        now = self.clock.now()
        with self.conn() as c, db.transaction(c):
            c.execute("DELETE FROM oauth_states WHERE expires_at < ?", (iso(now - OAUTH_STATE_TTL),))
            c.execute("""INSERT INTO oauth_states(state_hash, provider, binding_hash, nonce, code_verifier, intent, link_user_id,
                                                  return_to, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      (token_hash(state), provider, token_hash(binding), nonce, verifier, intent, link_user_id, return_to,
                       iso(now), iso(now + OAUTH_STATE_TTL)))
        return state, nonce, verifier

    def oauth_consume(self, *, provider: str, state: str, binding: str | None) -> dict[str, Any]:
        """Use a sign-in attempt exactly once, from the browser that started it, before it expires.

        The attempt is marked used in its own transaction first, so a refused callback still burns it.
        """
        with self.conn() as c, db.transaction(c):
            rec = db.row(c, "SELECT * FROM oauth_states WHERE state_hash = ?", (token_hash(state or ""),))
            if rec and not rec["used_at"]:
                c.execute("UPDATE oauth_states SET used_at = ? WHERE state_hash = ?", (self.now(), rec["state_hash"]))
        if not rec or rec["provider"] != provider:
            raise AuthError(400, "unknown_state")
        if rec["used_at"]:
            raise AuthError(400, "state_reused")
        if parse_iso(rec["expires_at"]) <= self.clock.now():
            raise AuthError(400, "state_expired")
        if not binding or not hmac.compare_digest(token_hash(binding), rec["binding_hash"]):
            raise AuthError(400, "browser_mismatch")
        return rec

    def oauth_signin(self, *, provider: str, subject: str, email: str | None, verified: bool, name: str | None,
                     allow_signup: bool, ip: str, user_agent: str = "") -> tuple[str, bool]:
        """Sign in an existing identity, or create a new account for a new one. Returns (session token, created)."""
        with self.conn() as c, db.transaction(c):
            ident = db.row(c, "SELECT * FROM oauth_identities WHERE provider = ? AND subject = ?", (provider, subject))
            created = False
            if ident:
                user = db.row(c, "SELECT * FROM users WHERE id = ?", (ident["user_id"],))
                if not user or user["disabled"]:
                    raise AuthError(403, "account_disabled")
                c.execute("UPDATE oauth_identities SET last_login_at = ? WHERE provider = ? AND subject = ?", (self.now(), provider, subject))
            else:
                if not email or not verified:
                    raise AuthError(403, "email_unverified")
                email = validate_email(email)
                if db.row(c, "SELECT 1 FROM users WHERE email = ?", (email,)):
                    # Never merge into an existing account by email alone: password sign-ups do not verify
                    # email ownership, so auto-linking would let anyone pre-register a victim's address.
                    raise AuthError(409, "account_exists")
                if not allow_signup:
                    raise AuthError(403, "signup_disabled")
                user_id = "usr_" + uuid.uuid4().hex[:12]
                display = (name or "").strip()[:80] or email.split("@")[0]
                c.execute("INSERT INTO users(id, email, name, password_hash, created_at, password_changed_at) VALUES (?,?,?,?,?,?)",
                          (user_id, email, display, NO_PASSWORD, self.now(), self.now()))
                c.execute("INSERT INTO oauth_identities(provider, subject, user_id, email, created_at, last_login_at) VALUES (?,?,?,?,?,?)",
                          (provider, subject, user_id, email, self.now(), self.now()))
                user = db.row(c, "SELECT * FROM users WHERE id = ?", (user_id,))
                self._audit(c, email, "user.signup", None, {"method": provider})
                created = True
            membership = db.row(c, "SELECT org_id FROM memberships WHERE user_id = ? ORDER BY created_at LIMIT 1", (user["id"],))
            org_id = membership["org_id"] if membership else None
            self._audit(c, user["email"], "login.succeeded", org_id, {"ip": ip, "method": provider})
            return self._new_session(c, user["id"], org_id, user_agent), created

    def oauth_link(self, *, user_id: str, provider: str, subject: str, email: str | None) -> None:
        with self.conn() as c, db.transaction(c):
            other = db.row(c, "SELECT user_id FROM oauth_identities WHERE provider = ? AND subject = ?", (provider, subject))
            if other and other["user_id"] != user_id:
                raise AuthError(409, "identity_in_use")
            if other:
                return
            if db.row(c, "SELECT 1 FROM oauth_identities WHERE user_id = ? AND provider = ?", (user_id, provider)):
                raise AuthError(409, "already_linked")
            c.execute("INSERT INTO oauth_identities(provider, subject, user_id, email, created_at) VALUES (?,?,?,?,?)",
                      (provider, subject, user_id, (email or "").lower(), self.now()))
            u = db.row(c, "SELECT email FROM users WHERE id = ?", (user_id,))
            self._audit(c, u["email"] if u else user_id, "identity.linked", None, {"provider": provider})

    def identities(self, user_id: str) -> dict[str, Any]:
        with self.conn() as c:
            rows = db.rows(c, "SELECT provider, email, created_at, last_login_at FROM oauth_identities WHERE user_id = ? ORDER BY provider", (user_id,))
            u = db.row(c, "SELECT password_hash FROM users WHERE id = ?", (user_id,))
        return {"identities": rows, "has_password": bool(u) and u["password_hash"] != NO_PASSWORD}

    def oauth_unlink(self, user_id: str, provider: str) -> None:
        with self.conn() as c, db.transaction(c):
            u = db.row(c, "SELECT email, password_hash FROM users WHERE id = ?", (user_id,))
            if not db.row(c, "SELECT 1 FROM oauth_identities WHERE user_id = ? AND provider = ?", (user_id, provider)):
                raise AuthError(404, "that sign-in method is not connected")
            n = int(c.execute("SELECT COUNT(*) FROM oauth_identities WHERE user_id = ?", (user_id,)).fetchone()[0])
            if u["password_hash"] == NO_PASSWORD and n <= 1:
                raise AuthError(409, "this is your only way to sign in; connect another provider first")
            c.execute("DELETE FROM oauth_identities WHERE user_id = ? AND provider = ?", (user_id, provider))
            self._audit(c, u["email"], "identity.unlinked", None, {"provider": provider})

    def accept_invitation_signed_in(self, token: str, *, user_id: str, email: str, session_token: str) -> str:
        """Join with the account already signed in (e.g. via Google), when it is the invited address."""
        with self.conn() as c, db.transaction(c):
            inv = db.row(c, "SELECT * FROM invitations WHERE token_hash = ? AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > ?",
                         (token_hash(token), self.now()))
            if not inv:
                raise AuthError(404, "this invitation is invalid, used or expired")
            if inv["email"].lower() != email.lower():
                raise AuthError(403, f"this invitation is for {inv['email']}; sign in with that account to join")
            c.execute("INSERT OR IGNORE INTO memberships VALUES (?,?,?,?)", (user_id, inv["org_id"], inv["role"], self.now()))
            c.execute("UPDATE invitations SET accepted_at = ? WHERE token_hash = ?", (self.now(), token_hash(token)))
            c.execute("UPDATE sessions SET org_id = ? WHERE token_hash = ?", (inv["org_id"], token_hash(session_token)))
            self._audit(c, email, "member.joined", inv["org_id"], {"role": inv["role"]})
            return inv["org_id"]
