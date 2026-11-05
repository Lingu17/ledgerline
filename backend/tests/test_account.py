"""Account basics a real product needs: a display name, a reset link an Owner hands over (no email is sent), leaving
an organization, deleting an organization with typed confirmation, and deleting one's own account."""
from .conftest import PASSWORD, new_client
from .test_saas import _invite_and_join

NEW_PASSWORD = "Another-Secret-42"


def _org_storage(app, org_id):
    """Where an organization's books live: its folder on SQLite; its ledger and bank schemas on PostgreSQL."""
    s = app.state.settings
    if not s.postgres:
        return {"orgs": (s.data_dir / "orgs" / org_id).exists()}
    from ledgerline.pg import schema_for

    names = {k: schema_for(s.pg_schema_prefix, k, org_id) for k in ("t", "b")}
    with app.state.control.conn() as c:
        found = {r[0] for r in c.execute("SELECT schema_name FROM information_schema.schemata").fetchall()}
    return {k: n in found for k, n in names.items()}


def test_a_person_changes_their_display_name(client):
    r = client.put("/api/auth/me", json={"name": "Ada Lovelace"})
    assert r.status_code == 200 and r.json()["user"]["name"] == "Ada Lovelace"
    assert client.put("/api/auth/me", json={"name": "  "}).status_code == 422


def test_an_owner_hands_a_member_a_one_hour_single_use_reset_link(client, app):
    member = _invite_and_join(client, app, "forgetful@northbeam.test", "operator")
    uid = next(m["user_id"] for m in client.get("/api/team").json()["members"] if m["email"] == "forgetful@northbeam.test")
    assert member.post(f"/api/team/members/{uid}/reset-link").status_code == 403  # owners only
    r = client.post(f"/api/team/members/{uid}/reset-link")
    assert r.status_code == 200, r.text
    token = r.json()["path"].split("token=")[1]
    fresh = new_client(app)
    assert fresh.get(f"/api/auth/reset/{token}").json()["email"] == "forgetful@northbeam.test"
    r = fresh.post(f"/api/auth/reset/{token}", json={"password": NEW_PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["email"] == "forgetful@northbeam.test"
    assert member.get("/api/auth/me").status_code == 401  # every old session is signed out
    assert fresh.post(f"/api/auth/reset/{token}", json={"password": NEW_PASSWORD}).status_code == 404
    login = new_client(app).post("/api/auth/login", json={"email": "forgetful@northbeam.test", "password": NEW_PASSWORD})
    assert login.status_code == 200
    actions = [a["action"] for a in client.get("/api/organization").json()["control_audit"]]
    assert "member.reset_link_issued" in actions and "user.password_reset" in actions


def test_no_reset_link_for_someone_who_also_belongs_elsewhere_or_for_yourself(client, app):
    member = _invite_and_join(client, app, "busy@northbeam.test", "viewer")
    member.post("/api/organizations", json={"name": "Busy Side Co", "start_with": "empty"})
    team = client.get("/api/team").json()
    uid = next(m["user_id"] for m in team["members"] if m["email"] == "busy@northbeam.test")
    r = client.post(f"/api/team/members/{uid}/reset-link")
    assert r.status_code == 409 and "another organization" in r.text
    assert client.post(f"/api/team/members/{team['you']}/reset-link").status_code == 409


def test_deleting_an_organization_needs_its_exact_name_and_removes_its_data(client, app):
    org_id, name = client.org_id, client.get("/api/organization").json()["name"]
    assert any(_org_storage(app, org_id).values())
    assert client.post("/api/organization/delete", json={"confirm": name.upper() + "x"}).status_code == 422
    r = client.post("/api/organization/delete", json={"confirm": name})
    assert r.status_code == 200, r.text
    assert not any(_org_storage(app, org_id).values()) and app.state.control.org(org_id) is None
    me = client.get("/api/auth/me").json()
    assert me["organization"] is None
    rows = app.state.control.control_audit(org_id)
    assert rows[0]["action"] == "organization.deleted"


def test_only_an_owner_deletes_and_never_while_money_is_being_sent(client, app):
    viewer = _invite_and_join(client, app, "look@northbeam.test", "viewer")
    name = client.get("/api/organization").json()["name"]
    assert viewer.post("/api/organization/delete", json={"confirm": name}).status_code == 403
    ctx = app.state.orgs.get(client.org_id)
    with ctx.conn() as conn:
        conn.execute("INSERT INTO operations(id, kind, request_id, amount_minor, currency, destination, status, created_at, updated_at) "
                     "VALUES ('OP-X','refund','req-x',100,'USD','acct','processing','2026-11-04T00:00:00Z','2026-11-04T00:00:00Z')")
    r = client.post("/api/organization/delete", json={"confirm": name})
    assert r.status_code == 409 and "still being sent" in r.text
    assert client.get("/api/status").json()["paused"] is False  # refused, so the pause it took is undone


def test_a_context_held_during_deletion_never_recreates_the_database(client, app):
    import pytest

    held = app.state.orgs.get(client.org_id)  # as a background round would hold it
    name = client.get("/api/organization").json()["name"]
    assert client.post("/api/organization/delete", json={"confirm": name}).status_code == 200
    with pytest.raises(RuntimeError, match="no longer exists"):
        with held.conn():
            pass
    assert not any(_org_storage(app, client.org_id).values())


def test_leave_then_delete_my_account(client, app):
    member = _invite_and_join(client, app, "leaving@northbeam.test", "operator")
    assert member.post("/api/auth/delete-account", json={"confirm": "leaving@northbeam.test"}).status_code == 409  # still a member
    assert member.post("/api/auth/leave-organization").status_code == 200
    assert member.post("/api/auth/delete-account", json={"confirm": "wrong@northbeam.test"}).status_code == 422
    assert member.post("/api/auth/delete-account", json={"confirm": "leaving@northbeam.test"}).status_code == 200
    assert member.get("/api/auth/me").status_code == 401
    r = new_client(app).post("/api/auth/login", json={"email": "leaving@northbeam.test", "password": PASSWORD})
    assert r.status_code in (401, 403)
    assert all(m["email"] != "leaving@northbeam.test" for m in client.get("/api/team").json()["members"])


def test_the_only_owner_cannot_leave(client):
    r = client.post("/api/auth/leave-organization")
    assert r.status_code == 409 and "only owner" in r.text
