"""Try to tamper: a practice company can change one audit event and watch the chain catch it at that event, then
restore it. A real company is refused. A backup taken mid-demo still checks clean once the change is put back."""
from fastapi.testclient import TestClient

from ledgerline import audit, db, tamper_demo

from .conftest import signup


def test_the_chain_catches_the_changed_event_and_restore_mends_it(client, app):
    client.post("/api/demo/step", json={"step": "deposits"})
    assert client.get("/api/audit/verify").json()["ok"]
    r = client.post("/api/practice/tamper")
    assert r.status_code == 200, r.text
    changed, chain = r.json()["changed"], r.json()["chain"]
    assert chain["ok"] is False and chain["broken_at"] == changed["id"] and changed["to"] == changed["from"] + 100_000
    assert client.get("/api/audit/verify").json()["broken_at"] == changed["id"]
    assert client.post("/api/practice/tamper").status_code == 409  # one at a time
    r = client.post("/api/practice/tamper/restore").json()
    assert r["restored"] and r["chain"]["ok"]
    last = client.get("/api/audit", params={"limit": 1}).json()[0]
    assert last["action"] == "practice.tamper_tried" and last["detail"]["caught_at_event"] == changed["id"]
    assert client.get("/api/practice/tamper").json()["changed"] is None


def test_a_real_company_is_refused(app):
    c = TestClient(app)
    signup(c, email="real@tamper.test", start_with="empty")
    for method, path in (("get", "/api/practice/tamper"), ("post", "/api/practice/tamper"), ("post", "/api/practice/tamper/restore")):
        r = getattr(c, method)(path)
        assert r.status_code == 403 and "practice" in r.text
    assert c.get("/api/audit/verify").json()["ok"]


def test_a_viewer_cannot_tamper(client, app):
    from .test_saas import _invite_and_join

    client.post("/api/demo/step", json={"step": "deposits"})
    viewer = _invite_and_join(client, app, "viewer@northbeam.test", "viewer")
    assert viewer.post("/api/practice/tamper").status_code == 403
    assert client.get("/api/audit/verify").json()["ok"]


def test_a_backup_taken_mid_demo_checks_clean_with_the_change_put_back(client, app):
    client.post("/api/demo/step", json={"step": "deposits"})
    client.post("/api/practice/tamper")
    ctx = app.state.orgs.get(client.org_id)
    with ctx.conn() as conn:
        assert not audit.verify_chain(conn)["ok"]
        with db.transaction(conn):
            record = tamper_demo.undo(conn)
        assert record and audit.verify_chain(conn)["ok"]


def test_practice_reset_clears_an_open_demo(client):
    client.post("/api/demo/step", json={"step": "deposits"})
    client.post("/api/practice/tamper")
    assert client.post("/api/demo/step", json={"step": "seed"}).status_code == 200
    assert client.get("/api/practice/tamper").json()["changed"] is None
    assert client.get("/api/audit/verify").json()["ok"]
