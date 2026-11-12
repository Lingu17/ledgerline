"""One-click judge demo: its own practice company, two demo people for the two-person rule, rate-limited, simulated
bank only, and deleted after 48 hours."""
from fastapi.testclient import TestClient

from ledgerline import judge_demo
from ledgerline.api.app import create_app
from ledgerline.config import load_settings

from .conftest import signup


def demo(app, ip="203.0.113.10"):
    c = TestClient(app, headers={"X-Forwarded-For": ip})
    r = c.post("/api/auth/judge-demo")
    assert r.status_code == 200, r.text
    me = r.json()
    c.headers["X-CSRF-Token"] = me["csrf_token"]
    c.org_id = me["organization"]["id"]
    return c, me


def payments(c):
    if not c.get("/api/deposits").json():
        c.post("/api/demo/step", json={"step": "deposits"})
    return {d["id"]: d for d in c.get("/api/deposits").json()}


def test_one_click_opens_a_practice_company_as_judge_a(app):
    c, me = demo(app)
    assert me["organization"]["kind"] == "sample" and me["role"] == "owner"
    assert me["judge_demo"]["you"] == "Judge A (Owner)" and me["judge_demo"]["deleted_after"]
    deps = payments(c)
    assert deps["DEP-1005"]["status"] == "awaiting_evidence" and deps["DEP-1004"]["status"] == "awaiting_evidence"
    assert c.get("/api/status").json()["bank"]["mode"] == "local"  # the simulated bank


def test_each_click_is_its_own_company_and_one_judge_cannot_see_another(app):
    c1, me1 = demo(app)
    c2, me2 = demo(app)
    assert c1.org_id != c2.org_id
    c1.post("/api/deposits/DEP-1005/ask-agent") if payments(c1) else None
    assert payments(c2)["DEP-1005"]["status"] == "awaiting_evidence"  # judge 1's answer is not in judge 2's company
    assert c2.post("/api/auth/switch-organization", json={"organization_id": c1.org_id}).status_code in (403, 404)
    assert [o["id"] for o in me2["organizations"]] == [c2.org_id]


def test_judge_a_approves_and_teammate_b_sends_the_agent_proposed_refund(app):
    c, _ = demo(app)
    payments(c)
    assert c.post("/api/deposits/DEP-1006/ask-agent").status_code == 200
    a = next(x for x in c.get("/api/approvals").json() if x["deposit_id"] == "DEP-1006")
    assert c.post(f"/api/approvals/{a['id']}/approve", json={"scope_hash": a["scope_hash"]}).status_code == 200
    assert c.post(f"/api/approvals/{a['id']}/execute").status_code == 403  # the approver cannot also send it
    r = c.post("/api/auth/judge-demo/switch")
    assert r.status_code == 200 and r.json()["judge_demo"]["you"] == "Teammate B (Operator)" and r.json()["role"] == "operator"
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert c.post(f"/api/approvals/{a['id']}/execute").status_code == 200  # a different, real member sends it
    ops = [o for o in c.get("/api/operations").json() if o["kind"] == "refund"]
    assert len(ops) == 1
    back = c.post("/api/auth/judge-demo/switch").json()
    assert back["judge_demo"]["you"] == "Judge A (Owner)"


def test_only_demo_people_can_switch(client):
    assert client.post("/api/auth/judge-demo/switch").status_code == 403


def test_a_demo_company_cannot_connect_airwallex_keys(app):
    c, _ = demo(app)
    r = c.post("/api/integrations/airwallex/connect", json={"client_id": "x" * 20, "api_key": "y" * 40, "webhook_secret": "z" * 20})
    assert r.status_code == 403 and "simulated bank only" in r.json()["detail"]


def test_demo_clicks_are_rate_limited_per_network(tmp_path):
    app = create_app(load_settings({"LEDGERLINE_DATA_DIR": str(tmp_path), "LEDGERLINE_PAYER_MCP_TRANSPORT": "memory",
                                    "LEDGERLINE_JUDGE_DEMO_PER_IP_HOUR": "2", "LEDGERLINE_TRUSTED_PROXY_HOPS": "1",
                                    "ANTHROPIC_API_KEY": "", "GOOGLE_CLIENT_ID": "", "APPLE_CLIENT_ID": ""}))
    for _ in range(2):
        demo(app, ip="198.51.100.7")
    r = TestClient(app, headers={"X-Forwarded-For": "198.51.100.7"}).post("/api/auth/judge-demo")
    assert r.status_code == 429
    demo(app, ip="198.51.100.8")  # another network is not affected


def test_the_demo_can_be_switched_off(tmp_path):
    app = create_app(load_settings({"LEDGERLINE_DATA_DIR": str(tmp_path), "LEDGERLINE_JUDGE_DEMO": "0",
                                    "ANTHROPIC_API_KEY": "", "GOOGLE_CLIENT_ID": "", "APPLE_CLIENT_ID": ""}))
    assert TestClient(app).post("/api/auth/judge-demo").status_code == 403


def test_demos_older_than_48_hours_are_deleted_with_their_people(app):
    old, _ = demo(app)
    fresh, _ = demo(app)
    path = app.state.settings.data_dir / "orgs" / old.org_id
    payments(old)
    assert path.exists()
    with app.state.control.conn() as conn:
        conn.execute("UPDATE judge_demos SET created_at = '2020-01-01T00:00:00Z' WHERE org_id = ?", (old.org_id,))
    assert judge_demo.cleanup(app) == 1
    assert app.state.control.org(old.org_id) is None and not path.exists()
    assert old.get("/api/deposits").status_code in (401, 403, 404, 409)  # the session no longer reaches it
    assert app.state.control.org(fresh.org_id) is not None and payments(fresh)  # a newer demo is untouched
    assert judge_demo.cleanup(app) == 0


def test_a_normal_signup_is_never_treated_as_a_demo(app):
    c = TestClient(app)
    me = signup(c, email="real@company.test", org="Real Co", start_with="sample")
    assert me.get("judge_demo") is None


def test_a_demo_person_cannot_create_companies_outside_the_demo(app):
    """Everything a demo person can reach is inside the demo company, so the 48-hour cleanup removes all of it."""
    c, _ = demo(app)
    r = c.post("/api/organizations", json={"name": "Escape Co", "start_with": "empty"})
    assert r.status_code == 403 and "demo" in r.json()["detail"]
    c.post("/api/auth/judge-demo/switch")
    assert c.post("/api/organizations", json={"name": "Escape Co", "start_with": "sample"}).status_code == 403
    assert [o["id"] for o in c.get("/api/auth/me").json()["organizations"]] == [c.org_id]
