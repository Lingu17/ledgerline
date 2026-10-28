"""HTTP surface: webhook HMAC + dedupe, origin/operator guards, and the guided demo over the API."""
import json
import threading
import time
import pytest

from ledgerline import webhooks

from .conftest import OP


@pytest.mark.parametrize("timestamp,signature", [
    ("9" * 5000, "0" * 64), ("１２３", "0" * 64),
    ("123", "非" * 64), ("123", "g" * 64), ("123", "0" * 63),
])
def test_malformed_signature_headers_are_controlled_rejections(timestamp, signature):
    with pytest.raises(webhooks.WebhookRejected) as exc:
        webhooks.verify_signature("test-only", timestamp, signature, b"{}", now_ms=123, tolerance_s=300)
    assert exc.value.status == 401



def _event(eid="evt_1", ref="AWX-DEP-9001", amount=1000.00, ccy="USD", payer="ACME ROBOTICS INC", reference="INV-2240"):
    """Documented deposit.settled shape: fields directly under data (payer block optional)."""
    data = {"id": ref, "type": "LOCAL", "status": "SETTLED", "created_at": "2026-10-27T00:00:00+0000",
            "settled_at": "2026-10-27T00:00:01+0000", "currency": ccy, "amount": amount, "reference": reference}
    if payer is not None:
        data["payer"] = {"name": payer}
    return json.dumps({"accountId": "acct_test", "data": data, "id": eid, "name": "deposit.settled"}).encode()


def _post(client, body, ts=None, sig=None, secret=None):
    ts = ts or str(int(time.time() * 1000))
    sig = sig or webhooks.sign(secret or client.webhook_secret, ts, body)
    return client.post(client.webhook_url, content=body, headers={"x-timestamp": ts, "x-signature": sig,
                                                                        "content-type": "application/json"})


def test_valid_webhook_ingests_and_matches(client):
    r = _post(client, _event(amount=2000.00))
    assert r.status_code == 200 and r.json()["status"] == "processed"
    d = client.get(f"/api/deposits/{r.json()['deposit_id']}").json()
    assert d["category"] == "clean_match" and d["buckets"]["allocated"] == 200_000


def test_duplicate_event_id_is_ignored(client):
    body = _event()
    assert _post(client, body).json()["status"] == "processed"
    assert _post(client, body).json()["status"] == "duplicate"
    assert len(client.get("/api/deposits").json()) == 1


def test_nested_sandbox_webhook_uses_stored_payer_and_reference_hints(client):
    from ledgerline import db
    ctx = client.app.state.orgs.get(client.org_id)
    with ctx.conn() as conn, db.transaction(conn):
        conn.execute("INSERT INTO deposit_hints VALUES (?,?,?,?)",
                     ("awx-nested", "ACME ROBOTICS INC", "INV-2240", "2026-10-28T00:00:00Z"))
    event = json.loads(_event(ref="awx-nested", amount=2000, payer=None))
    event['data'].pop('reference')
    event['data'] = {'object': event['data']}
    response = _post(client, json.dumps(event).encode())
    assert response.status_code == 200, response.text
    deposit = client.get(f"/api/deposits/{response.json()['deposit_id']}").json()
    assert deposit['category'] == 'clean_match'
    assert deposit['buckets']['allocated'] == 200_000


def test_concurrent_duplicate_deliveries_apply_once(client):
    body = _event(eid="evt_race")
    out = []
    threads = [threading.Thread(target=lambda: out.append(_post(client, body).json()["status"])) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(out).count("processed") == 1
    assert len(client.get("/api/deposits").json()) == 1


def test_same_deposit_under_new_event_id_not_double_counted(client):
    _post(client, _event(eid="evt_a"))
    assert _post(client, _event(eid="evt_b")).json()["status"] == "deposit_already_known"
    assert len(client.get("/api/deposits").json()) == 1


def test_bad_signature_stale_timestamp_and_malformed_rejected(client):
    body = _event()
    assert _post(client, body, sig="00" * 32).status_code == 401
    old = str(int(time.time() * 1000) - 10 * 60 * 1000)
    assert _post(client, body, ts=old).status_code == 401
    assert _post(client, b"not json").status_code == 400
    assert _post(client, _event(amount=10.001)).status_code == 400
    assert _post(client, _event(ccy="JPY")).status_code == 400
    assert client.post(client.webhook_url, content=body).status_code == 401
    assert client.get("/api/deposits").json() == []


def test_mutations_need_csrf_token_and_allowed_origin(client):
    token = client.headers.pop("X-CSRF-Token")
    assert client.post("/api/demo/step", json={"step": "seed"}).status_code == 403
    client.headers["X-CSRF-Token"] = "wrong"
    assert client.post("/api/demo/step", json={"step": "seed"}).status_code == 403
    client.headers["X-CSRF-Token"] = token
    r = client.post("/api/demo/step", json={"step": "seed"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.post("/api/demo/step", json={"step": "seed"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    r = client.post("/api/demo/step", json={"step": "seed"}, headers={"Origin": "http://127.0.0.1:5173"})
    assert r.status_code == 200


def test_webhook_secret_is_per_organization(client, app):
    from .conftest import new_client, signup

    other = new_client(app)
    signup(other, email="owner@other.test", org="Other Co")
    body = _event()
    # Signed with the other organization's secret: refused at this organization's endpoint.
    assert _post(client, body, secret=other.webhook_secret).status_code == 401
    assert client.post("/api/webhooks/airwallex/org_000000000000", content=body).status_code == 404


def test_guided_demo_over_api_with_stale_view_protection(client):
    for step in ["seed", "deposits", "links", "agents", "treasury"]:
        r = client.post("/api/demo/step", json={"step": step}, headers=OP)
        assert r.status_code == 200, r.text
    assert client.get("/api/demo").json()["blocked"].startswith("waiting for a person")
    assert client.post("/api/demo/step", json={"step": "approve"}, headers=OP).status_code == 409
    ap = next(a for a in client.get("/api/approvals").json() if a["status"] == "pending")
    assert ap["scope"]["amount_minor"] == 480_000 and ap["scope"]["currency"] == "GBP"
    assert ap["evidence"]["verdict"] == "verified"
    r = client.post(f"/api/approvals/{ap['id']}/approve", json={"scope_hash": "a" * 64}, headers=OP)
    assert r.status_code == 409
    r = client.post(f"/api/approvals/{ap['id']}/approve", json={"scope_hash": ap["scope_hash"]}, headers=OP)
    assert r.json()["status"] == "approved"
    for step in ["approve", "bank_sent", "bank_paid"]:
        assert client.post("/api/demo/step", json={"step": step}, headers=OP).status_code == 200
    ledger = client.get("/api/ledger").json()
    assert ledger["conservation"]["all_balanced"]
    export = client.get("/api/audit/export")
    assert export.headers["content-disposition"].startswith("attachment")
    data = export.json()
    assert data["synthetic_data_only"] and any(o["request_id"] for o in data["operations"])
    assert client.get("/api/status").json()["claude"]["mode"] == "deterministic_fixture"


def test_pause_endpoint_blocks_money_out_but_not_matching(client):
    client.post("/api/demo/step", json={"step": "seed"}, headers=OP)
    assert client.post("/api/settings/pause", json={"paused": True, "reason": "test"}, headers=OP).status_code == 200
    for step in ["deposits", "links", "agents"]:
        assert client.post("/api/demo/step", json={"step": step}, headers=OP).status_code == 200
    r = client.post("/api/demo/step", json={"step": "treasury"}, headers=OP)
    assert r.status_code == 423
    assert client.get("/api/status").json()["paused"] is True


def test_evidence_reader_fixture_is_advisory_and_labelled(client):
    for step in ["seed", "deposits", "links", "agents"]:
        client.post("/api/demo/step", json={"step": step}, headers=OP)
    r = client.post("/api/deposits/DEP-1004/read-remittance", headers=OP).json()
    assert "Claude not invoked" in r["mode"]
    assert r["proposal"]["tool"] == "propose_invoice_match"
    assert r["checks"][0]["passed"] is False  # unsigned: can never authorise money movement
    d = client.get("/api/deposits/DEP-1004").json()
    assert d["status"] == "escalated" and d["evidence"][-1]["verdict"] == "advisory"


def test_return_to_sender_needs_explicit_approval(client):
    for step in ["seed", "deposits", "links", "agents"]:
        client.post("/api/demo/step", json={"step": step}, headers=OP)
    a = client.post("/api/deposits/DEP-1004/return-to-sender", headers=OP).json()
    assert a["status"] == "pending" and a["scope"]["destination"].startswith("Fjord")
