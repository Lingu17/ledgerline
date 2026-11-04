"""Saving the Policy form changes only what it sends; everything else keeps its value, and the log says what changed."""


def test_saving_part_of_the_policy_keeps_the_rest(client):
    assert client.put("/api/settings/policy", json={"approval_ttl_hours": 24, "obligation_lookahead_days": 30}).status_code == 200
    money = {k: client.get("/api/status").json()["policy"][k] for k in ("fee_tolerance_minor", "refund_auto_limit_minor", "reserve_minor", "ring_fenced_minor")}
    money["refund_auto_limit_minor"]["USD"] = 50_000
    r = client.put("/api/settings/policy", json={**money, "fee_tolerance_bps": 100})  # what the form sends
    assert r.status_code == 200
    p = client.get("/api/status").json()["policy"]
    assert p["approval_ttl_hours"] == 24 and p["obligation_lookahead_days"] == 30 and p["refund_auto_limit_minor"]["USD"] == 50_000
    last = next(e for e in client.get("/api/audit", params={"q": "policy.updated"}).json())
    assert last["detail"]["changed"] == {"refund_auto_limit_minor": {"from": {"USD": 100_000, "EUR": 100_000, "GBP": 100_000},
                                                                     "to": {"USD": 50_000, "EUR": 100_000, "GBP": 100_000}}}


def test_out_of_range_expiry_is_refused(client):
    assert client.put("/api/settings/policy", json={"approval_ttl_hours": 0}).status_code == 422
    assert client.get("/api/status").json()["policy"]["approval_ttl_hours"] == 72
