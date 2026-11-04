"""A brand-new real company is not "short" of money it never said it had: no reserves it did not choose, wallets say
the opening balance is not set, the checklist asks for it, and the CEO view agrees with the table."""
from .conftest import new_client, signup


def test_a_new_real_company_starts_without_assumed_reserves_or_shortfalls(app):
    c = new_client(app)
    signup(c, email="owner@dayone.test", org="Day One Co", start_with="empty")
    policy = c.get("/api/status").json()["policy"]
    assert policy["reserve_minor"] == {"USD": 0, "EUR": 0, "GBP": 0} and policy["approval_ttl_hours"] == 72
    wallets = c.get("/api/overview").json()["wallets"]
    assert all(w["cash_known"] is False and w["free_after_commitments"] == 0 for w in wallets)
    ceo = c.get("/api/ceo").json()
    assert ceo["verdict"] in ("ok", "attention") and "short" not in ceo["headline"]
    steps = {s["id"]: s["done"] for s in c.get("/api/setup").json()["steps"]}
    assert steps["opening"] is False
    assert c.post("/api/treasury/opening-balance", json={"currency": "USD", "amount": "10000.00"}).status_code == 200
    usd = next(w for w in c.get("/api/overview").json()["wallets"] if w["currency"] == "USD")
    assert usd["cash_known"] is True and usd["cash"] == 1_000_000
    assert {s["id"]: s["done"] for s in c.get("/api/setup").json()["steps"]}["opening"] is True


def test_short_cash_is_not_all_clear(app):
    c = new_client(app)
    signup(c, email="owner@short.test", org="Short Co", start_with="empty")
    c.post("/api/treasury/opening-balance", json={"currency": "EUR", "amount": "100.00"})
    money = {k: c.get("/api/status").json()["policy"][k] for k in ("fee_tolerance_minor", "refund_auto_limit_minor", "reserve_minor", "ring_fenced_minor")}
    money["reserve_minor"]["EUR"] = 50_000
    assert c.put("/api/settings/policy", json=money).status_code == 200
    ceo = c.get("/api/ceo").json()
    assert ceo["verdict"] == "attention" and "cash is short in EUR" in ceo["headline"] and "0 items" not in ceo["headline"]


def test_a_practice_company_keeps_its_example_reserves(client):
    assert client.get("/api/status").json()["policy"]["reserve_minor"]["USD"] == 500_000
