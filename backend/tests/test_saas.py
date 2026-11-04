"""SaaS boundaries: authentication, sessions, roles, invitations, tenant isolation, migrations, adjustments."""
import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from ledgerline.api.app import create_app
from ledgerline.clock import Clock

from .conftest import PASSWORD, new_client, signup


def _invite_and_join(owner: TestClient, app, email: str, role: str) -> TestClient:
    r = owner.post("/api/team/invitations", json={"email": email, "role": role})
    assert r.status_code == 200, r.text
    token = r.json()["invite_path"].split("token=")[1]
    c = new_client(app)
    info = c.get(f"/api/invitations/{token}").json()
    assert info["email"] == email and info["role"] == role
    me = c.post(f"/api/invitations/{token}/accept", json={"name": role.title(), "password": PASSWORD}).json()
    c.headers["X-CSRF-Token"] = me["csrf_token"]
    assert me["role"] == role
    return c


# --------------------------------------------------------------------------- authentication
def test_signup_login_logout_and_cookie_flags(app):
    c = new_client(app)
    r = c.post("/api/auth/signup", json={"email": "Ana@Example.test", "name": "Ana", "password": PASSWORD,
                                         "organization_name": "Kestrel Labs", "start_with": "empty"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie
    me = c.get("/api/auth/me").json()
    assert me["user"]["email"] == "ana@example.test" and me["role"] == "owner" and me["organization"]["kind"] == "workspace"
    stolen = c.cookies.get("ll_session")
    assert c.post("/api/auth/logout", headers={"X-CSRF-Token": me["csrf_token"]}).status_code == 200
    replay = new_client(app)
    replay.cookies.set("ll_session", stolen, path="/api")
    assert replay.get("/api/auth/me").status_code == 401  # server-side invalidation, not just cookie deletion
    assert replay.get("/api/deposits").status_code == 401
    c2 = new_client(app)
    assert c2.post("/api/auth/login", json={"email": "ana@example.test", "password": PASSWORD}).status_code == 200
    assert c2.get("/api/customers").status_code == 200


def test_secure_cookie_when_configured(settings):
    settings.cookie_secure = True
    c = TestClient(create_app(settings))
    r = c.post("/api/auth/signup", json={"email": "s@example.test", "name": "S", "password": PASSWORD,
                                         "organization_name": "Secure Co"})
    assert "secure" in r.headers["set-cookie"].lower()


@pytest.mark.parametrize("password", ["short1A", "alllowercase123", "ALLUPPERCASE123", "NoDigitsHereAtAll"])
def test_password_policy(app, password):
    r = new_client(app).post("/api/auth/signup", json={"email": "p@example.test", "name": "P", "password": password,
                                                       "organization_name": "Weak Co"})
    assert r.status_code == 422


def test_duplicate_signup_and_generic_login_error(app):
    c = new_client(app)
    signup(c, email="dup@example.test")
    r = new_client(app).post("/api/auth/signup", json={"email": "dup@example.test", "name": "D", "password": PASSWORD,
                                                       "organization_name": "Again"})
    assert r.status_code == 409
    wrong = new_client(app).post("/api/auth/login", json={"email": "dup@example.test", "password": "Wrong-password-99"})
    nobody = new_client(app).post("/api/auth/login", json={"email": "nobody@example.test", "password": "Wrong-password-99"})
    assert wrong.status_code == nobody.status_code == 401
    assert wrong.json()["detail"] == nobody.json()["detail"]  # no account enumeration


def test_login_throttling(app):
    signup(new_client(app), email="t@example.test")
    c = new_client(app)
    for _ in range(5):
        assert c.post("/api/auth/login", json={"email": "t@example.test", "password": "Wrong-password-99"}).status_code == 401
    r = c.post("/api/auth/login", json={"email": "t@example.test", "password": PASSWORD})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0  # even the right password waits out the window


def test_session_idle_and_absolute_expiry(settings):
    clock = Clock()
    app = create_app(settings, clock)
    c = new_client(app)
    signup(c)
    clock.advance(timedelta(minutes=110))
    assert c.get("/api/customers").status_code == 200  # activity refreshes idle timer
    clock.advance(timedelta(hours=2, minutes=1))
    assert c.get("/api/customers").status_code == 401
    c2 = new_client(app)
    c2.post("/api/auth/login", json={"email": "owner@northbeam.test", "password": PASSWORD})
    for _ in range(8):  # 800 minutes of continuous activity
        clock.advance(timedelta(minutes=100))
        c2.get("/api/customers")
    assert c2.get("/api/customers").status_code == 401  # 12 h absolute limit


def test_change_password_signs_out_other_sessions(app):
    a = new_client(app)
    me = signup(a, email="cp@example.test")
    b = new_client(app)
    b.post("/api/auth/login", json={"email": "cp@example.test", "password": PASSWORD})
    r = a.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "Another-Strong-Pass-7"},
               headers={"X-CSRF-Token": me["csrf_token"]})
    assert r.status_code == 200
    assert b.get("/api/auth/me").status_code == 401
    assert a.get("/api/auth/me").status_code == 200


def test_unauthenticated_requests_refused(app):
    c = new_client(app)
    for path in ["/api/deposits", "/api/customers", "/api/ledger", "/api/audit/export", "/api/status", "/api/team"]:
        assert c.get(path).status_code == 401, path
    assert c.post("/api/payments", json={}).status_code == 401


# --------------------------------------------------------------------------- tenant isolation
def test_organizations_cannot_see_or_touch_each_other(app):
    a = new_client(app)
    signup(a, email="a@alpha.test", org="Alpha", start_with="sample")
    for step in ["deposits", "links", "agents"]:
        assert a.post("/api/demo/step", json={"step": step}).status_code == 200
    a_approval = next(x for x in a.get("/api/approvals").json() if x["status"] == "pending")

    b = new_client(app)
    signup(b, email="b@beta.test", org="Beta", start_with="empty")
    assert b.get("/api/deposits").json() == []
    assert b.get("/api/customers").json() == []
    assert b.get("/api/deposits/DEP-1006").status_code == 404
    assert b.get("/api/approvals").json() == []
    r = b.post(f"/api/approvals/{a_approval['id']}/approve", json={"scope_hash": a_approval["scope_hash"]})
    assert r.status_code == 409 and "unknown approval" in r.json()["detail"]
    assert b.post("/api/auth/switch-organization", json={"organization_id": a.org_id}).status_code == 403
    export = b.get("/api/audit/export").json()
    assert export["organization"]["id"] == b.org_id and export["deposits"] == [] and export["approvals"] == []
    # A's state is untouched by B's attempts.
    assert next(x for x in a.get("/api/approvals").json() if x["id"] == a_approval["id"])["status"] == "pending"
    # Data lives in separate files.
    ctx_a, ctx_b = app.state.orgs.get(a.org_id), app.state.orgs.get(b.org_id)
    assert ctx_a.settings.db_path != ctx_b.settings.db_path


def test_money_out_and_evidence_of_one_organization_are_unreachable_from_another(app):
    a = new_client(app)
    signup(a, email="a2@alpha.test", org="Alpha Two", start_with="sample")
    for step in ["deposits", "links", "agents", "treasury"]:
        assert a.post("/api/demo/step", json={"step": step}).status_code == 200
    approval = next(x for x in a.get("/api/approvals").json() if x["status"] == "pending")
    assert a.post(f"/api/approvals/{approval['id']}/approve", json={"scope_hash": approval["scope_hash"]}).status_code == 200
    operation = a.get("/api/operations").json()[0]
    before = (a.get("/api/approvals").json(), a.get("/api/operations").json(), len(a.get("/api/audit/export").json()["audit_events"]))

    b = new_client(app)
    signup(b, email="b2@beta.test", org="Beta Two", start_with="empty")
    for path in [f"/api/approvals/{approval['id']}/execute", f"/api/approvals/{approval['id']}/send-as-practice-teammate",
                 f"/api/approvals/{approval['id']}/reject", f"/api/operations/{operation['id']}/sync",
                 "/api/deposits/DEP-1006/ask-agent", "/api/deposits/DEP-1004/return-to-sender"]:
        body = {"scope_hash": approval["scope_hash"]} if path.endswith("/reject") else {}
        r = b.post(path, json=body)
        assert r.status_code in (403, 404, 409, 422), (path, r.status_code, r.text)
    r = b.post(f"/api/operations/{operation['id']}/simulate-bank", json={"next_status": "SENT"})
    assert r.status_code in (403, 404, 409), r.text
    assert b.get("/api/operations").json() == [] and b.get("/api/evidence").json() == []
    assert b.get("/api/treasury/bill-payments").json() == []
    assert b.get(f"/api/deposits/{approval['deposit_id']}").status_code == 404
    # Nothing Beta tried changed Alpha: same approvals, same operations, no new audit events.
    assert (a.get("/api/approvals").json(), a.get("/api/operations").json(), len(a.get("/api/audit/export").json()["audit_events"])) == before


def test_user_in_two_orgs_switches_context(app):
    c = new_client(app)
    me = signup(c, email="multi@example.test", org="First", start_with="sample")
    r = c.post("/api/organizations", json={"name": "Second", "start_with": "empty"})
    assert r.status_code == 200 and r.json()["organization"]["name"] == "Second"
    assert c.get("/api/customers").json() == []
    c.post("/api/auth/switch-organization", json={"organization_id": me["organization"]["id"]})
    assert len(c.get("/api/customers").json()) == 6


# --------------------------------------------------------------------------- roles
def test_viewer_is_read_only(client, app):
    viewer = _invite_and_join(client, app, "viewer@northbeam.test", "viewer")
    assert viewer.get("/api/customers").status_code == 200
    assert viewer.get("/api/audit/export").status_code == 200
    for method, path, body in [
        ("post", "/api/payments", {"external_ref": "x", "currency": "USD", "amount": "1.00", "payer_name": "ACME ROBOTICS INC"}),
        ("post", "/api/customers", {"name": "X"}),
        ("post", "/api/demo/step", {"step": "deposits"}),
        ("post", "/api/settings/pause", {"paused": True}),
        ("post", "/api/team/invitations", {"email": "z@z.test", "role": "viewer"}),
        ("put", "/api/settings/policy", {}),
    ]:
        r = getattr(viewer, method)(path, json=body)
        assert r.status_code == 403, (path, r.status_code, r.text)


def test_operator_works_but_cannot_govern(client, app):
    op = _invite_and_join(client, app, "ops@northbeam.test", "operator")
    r = op.post("/api/payments", json={"external_ref": "STMT-1", "currency": "USD", "amount": "2000.00",
                                       "payer_name": "ACME ROBOTICS INC", "reference": "INV-2240"})
    assert r.status_code == 200
    assert op.post("/api/settings/pause", json={"paused": True}).status_code == 200  # emergency stop allowed
    assert op.post("/api/settings/pause", json={"paused": False}).status_code == 403  # resume is owner-only
    assert op.put("/api/settings/policy", json={}).status_code == 403
    assert op.post("/api/team/invitations", json={"email": "z@z.test", "role": "viewer"}).status_code == 403
    assert op.put("/api/organization", json={"name": "Hijacked"}).status_code == 403
    assert op.post("/api/demo/step", json={"step": "seed"}).status_code == 403
    assert client.post("/api/settings/pause", json={"paused": False}).status_code == 200


def test_proposer_cannot_approve_own_refund(client, app):
    for step in ["deposits", "links", "agents"]:
        client.post("/api/demo/step", json={"step": step})
    op = _invite_and_join(client, app, "ops2@northbeam.test", "operator")
    a = op.post("/api/deposits/DEP-1004/return-to-sender").json()
    assert a["status"] == "pending" and a["created_by"] == "ops2@northbeam.test"
    r = op.post(f"/api/approvals/{a['id']}/approve", json={"scope_hash": a["scope_hash"]})
    assert r.status_code == 403 and "different team member" in r.json()["detail"]
    r = client.post(f"/api/approvals/{a['id']}/approve", json={"scope_hash": a["scope_hash"]})
    assert r.status_code == 200 and r.json()["decided_by"] == "owner@northbeam.test"


def test_role_changes_and_removal_take_effect_immediately(client, app):
    op = _invite_and_join(client, app, "ops3@northbeam.test", "operator")
    team = client.get("/api/team").json()
    uid = next(m["user_id"] for m in team["members"] if m["email"] == "ops3@northbeam.test")
    assert client.put(f"/api/team/members/{uid}", json={"role": "viewer"}).status_code == 200
    assert op.post("/api/payments", json={"external_ref": "S2", "currency": "USD", "amount": "1.00", "payer_name": "X Y"}).status_code == 403
    assert client.delete(f"/api/team/members/{uid}").status_code == 200
    assert op.get("/api/customers").status_code == 403
    owner_id = team["you"]
    assert client.put(f"/api/team/members/{owner_id}", json={"role": "viewer"}).status_code == 409  # last owner


def test_invitation_single_use_and_expiry(settings):
    clock = Clock()
    app = create_app(settings, clock)
    owner = new_client(app)
    signup(owner)
    r = owner.post("/api/team/invitations", json={"email": "late@northbeam.test", "role": "viewer"}).json()
    token = r["invite_path"].split("token=")[1]
    clock.advance(timedelta(days=3, minutes=1))
    assert new_client(app).get(f"/api/invitations/{token}").status_code == 404
    owner = new_client(app)  # the owner's own session idled out meanwhile
    owner.headers["X-CSRF-Token"] = owner.post("/api/auth/login", json={"email": "owner@northbeam.test", "password": PASSWORD}).json()["csrf_token"]
    token = owner.post("/api/team/invitations", json={"email": "ok@northbeam.test", "role": "viewer"}).json()["invite_path"].split("token=")[1]
    c = new_client(app)
    assert c.post(f"/api/invitations/{token}/accept", json={"name": "Ok", "password": "weak"}).status_code == 422
    assert c.post(f"/api/invitations/{token}/accept", json={"name": "Ok", "password": PASSWORD}).status_code == 200
    assert new_client(app).post(f"/api/invitations/{token}/accept", json={"name": "Ok", "password": PASSWORD}).status_code == 404


# --------------------------------------------------------------------------- operations without the walkthrough
def test_empty_workspace_full_workflow(app):
    c = new_client(app)
    signup(c, email="fin@harbour.test", org="Harbour Lane", start_with="empty")
    assert c.get("/api/demo").json()["available"] is False
    assert c.post("/api/demo/step", json={"step": "deposits"}).status_code == 409
    assert c.post("/api/treasury/opening-balance", json={"currency": "GBP", "amount": "5000.00"}).status_code == 200
    assert c.post("/api/treasury/opening-balance", json={"currency": "GBP", "amount": "1.00"}).status_code == 422
    cust = c.post("/api/customers", json={"name": "Orchard Tea Co", "country": "GB", "payer_names": ["ORCHARD TEA CO"],
                                          "refund_beneficiary": "Orchard Tea - UK account"}).json()
    inv = c.post("/api/invoices", json={"customer_id": cust["id"], "currency": "GBP", "amount": "1000.00",
                                        "due_date": "2026-12-15", "description": "Brand site"}).json()
    r = c.post("/api/payments", json={"external_ref": "HSBC-0001", "currency": "GBP", "amount": "600.00",
                                      "payer_name": "Orchard Tea Co", "reference": inv["id"]}).json()
    d = c.get(f"/api/deposits/{r['deposit_id']}").json()
    assert d["category"] == "partial_payment" and d["buckets"]["allocated"] == 60_000
    # Credit note for part of the balance; history is not edited.
    assert c.patch(f"/api/invoices/{inv['id']}", json={"amount": "900.00"}).status_code == 422
    adj = c.post(f"/api/invoices/{inv['id']}/adjustments", json={"kind": "decrease", "amount": "100.00", "reason": "Agreed discount"})
    assert adj.status_code == 200
    row = next(i for i in c.get("/api/invoices").json() if i["id"] == inv["id"])
    assert row["remaining_minor"] == 30_000 and row["effective_amount_minor"] == 90_000
    assert c.post(f"/api/invoices/{inv['id']}/adjustments", json={"kind": "decrease", "amount": "300.01", "reason": "too much"}).status_code == 422
    assert c.post(f"/api/invoices/{inv['id']}/adjustments", json={"kind": "void", "reason": "mistake"}).status_code == 422
    ob = c.post("/api/treasury/obligations", json={"payee": "Shoreditch Workspace", "currency": "GBP", "amount": "300.00",
                                                   "due_date": "2026-11-20"})
    assert ob.status_code == 200
    assert c.get("/api/ledger").json()["conservation"]["all_balanced"]
    page = c.get("/api/invoices?limit=1&offset=0")
    assert page.headers["x-total-count"] == "1"


def test_voided_invoice_can_never_be_paid(client):
    inv = client.post("/api/invoices", json={"customer_id": "CUST-ACME", "currency": "USD", "amount": "750.00",
                                             "due_date": "2026-12-01", "description": "Workshop"}).json()
    assert client.post(f"/api/invoices/{inv['id']}/adjustments", json={"kind": "void", "reason": "Cancelled engagement"}).status_code == 200
    r = client.post("/api/payments", json={"external_ref": "VOIDPAY", "currency": "USD", "amount": "750.00",
                                           "payer_name": "ACME ROBOTICS INC", "reference": inv["id"]}).json()
    d = client.get(f"/api/deposits/{r['deposit_id']}").json()
    assert d["buckets"]["allocated"] == 0
    assert client.get("/api/ledger").json()["conservation"]["all_balanced"]


def test_csv_import_is_idempotent_per_row(client):
    csv = ("external_ref,received_at,currency,amount,payer_name,reference\n"
           "B-1,2026-10-20,USD,2000.00,ACME ROBOTICS INC,INV-2240\n"
           "B-2,2026-10-20,EUR,abc,BRIGHTWAVE GMBH,INV-2253\n"
           "B-1,2026-10-20,USD,2000.00,ACME ROBOTICS INC,INV-2240\n")
    r = client.post("/api/payments/import", json={"csv": csv}).json()
    assert (r["created"], r["duplicates"], r["errors"]) == (1, 1, 1)
    assert client.post("/api/payments/import", json={"csv": "a,b\n1,2"}).status_code == 422


def test_customer_edit_invalidates_bound_approval(client):
    for step in ["deposits", "links", "agents"]:
        client.post("/api/demo/step", json={"step": step})
    a = next(x for x in client.get("/api/approvals").json() if x["status"] == "pending")
    assert client.patch("/api/customers/CUST-EASTGATE", json={"refund_beneficiary": "New account - changed"}).status_code == 200
    r = client.post(f"/api/approvals/{a['id']}/approve", json={"scope_hash": a["scope_hash"]})
    assert r.status_code == 409 and "destination" in r.json()["detail"]


# --------------------------------------------------------------------------- migrations
def test_migrations_recorded_and_legacy_tenant_upgraded(settings, tmp_path):
    from ledgerline.db import SCHEMA
    from ledgerline.migrations import TENANT, migrate

    legacy = sqlite3.connect(tmp_path / "legacy.sqlite3", isolation_level=None)
    legacy.executescript(SCHEMA)  # a pre-SaaS database: v1 tables, no migration table
    ran = migrate(legacy, TENANT)
    assert ran == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    cols = {r[1] for r in legacy.execute("PRAGMA table_info(approvals)")}
    assert "created_by" in cols
    assert migrate(legacy, TENANT) == []  # idempotent
    legacy.close()
    app = create_app(settings)
    with app.state.control.conn() as c:
        assert [r[0] for r in c.execute("SELECT version FROM schema_migrations")] == [1, 2, 3, 4, 5, 6]
        if app.state.settings.postgres:
            tables = {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()").fetchall()}
        else:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"oauth_identities", "oauth_states"} <= tables
    create_app(settings)  # restart: nothing re-applied, no error
