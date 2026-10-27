"""Payer MCP over a real stdio subprocess, and the Airwallex sandbox adapter against a mocked transport."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from ledgerline.payer_agents.client import explain_payments
from ledgerline.providers.airwallex import SANDBOX_BASE_URL, AirwallexSandbox
from ledgerline.providers.base import ProviderAmbiguous, ProviderUnsupported


def test_explain_payment_over_stdio_mcp(tmp_path):
    from ledgerline.payer_agents.keys import ensure_keys

    ensure_keys(tmp_path)  # keys exist only once an organization is seeded; the agent never creates them
    answers, transport = explain_payments(tmp_path, [{
        "customer_id": "CUST-EASTGATE", "deposit_id": "DEP-1006", "currency": "GBP", "amount_minor": 480_000,
        "received_at": "2026-10-27T00:00:00Z", "reference": "INV-2238",
    }, {
        "customer_id": "CUST-EASTGATE", "deposit_id": "DEP-X", "currency": "GBP", "amount_minor": 1,
        "received_at": "2026-10-27T00:00:00Z", "reference": "",
    }], transport="stdio")
    assert transport == "mcp/stdio"
    assert answers[0]["status"] == "answered"
    env = answers[0]["envelope"]
    assert env["alg"] == "Ed25519" and env["claim"]["deposit_id"] == "DEP-1006"
    assert answers[1]["status"] == "unknown"


class FakeAirwallex:
    def __init__(self):
        self.calls = []
        self.logins = 0
        self.fail_transfer = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path.removeprefix("/api/v1")
        if path == "/authentication/login":
            self.logins += 1
            assert request.headers["x-client-id"] == "cid" and request.headers["x-api-key"] == "key"
            assert request.content == b""
            exp = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            return httpx.Response(201, json={"token": "tok", "expires_at": exp})
        assert request.headers["authorization"] == "Bearer tok"
        assert "x-api-version" not in request.headers
        body = json.loads(request.content) if request.content else {}
        if path == "/fx/quotes/create":
            return httpx.Response(201, json={"quote_id": "q1", "sell_amount": 4907.61, "buy_amount": body["buy_amount"],
                                             "client_rate": 0.92, "usage": "SINGLE_USE",
                                             "valid_to_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()})
        if path == "/transfers/create":
            if self.fail_transfer == "timeout":
                raise httpx.ReadTimeout("timeout", request=request)
            return httpx.Response(201, json={"id": "tr1", "request_id": body["request_id"], "status": "PROCESSING"})
        if path == "/transfers":
            return httpx.Response(200, json={"items": [{"id": "tr1", "request_id": request.url.params["request_id"], "status": "SENT"}]})
        if path == "/simulation/deposit/create":
            return httpx.Response(201, json={"id": "dep1", "currency": "USD", "amount": body["amount"], "status": "SETTLED"})
        if path == "/pa/payment_links/create":
            return httpx.Response(404, json={"code": "not_found"})
        return httpx.Response(404)


def _adapter(fake):
    return AirwallexSandbox("cid", "key", transport=httpx.MockTransport(fake))


def test_sandbox_host_is_fixed():
    assert SANDBOX_BASE_URL == "https://api.sandbox.airwallex.com/api/v1"


def test_token_cached_and_amounts_sent_as_exact_major_units():
    fake = FakeAirwallex()
    aw = _adapter(fake)
    q = aw.create_quote(sell_currency="USD", buy_currency="EUR", buy_amount_minor=451_500)
    aw.create_quote(sell_currency="USD", buy_currency="EUR", buy_amount_minor=451_500)
    assert fake.logins == 1
    sent = json.loads(fake.calls[1].content)
    assert sent["buy_amount"] == 4515.0 and sent["validity"] == "MIN_1"
    assert q.sell_amount_minor == 490_761 and q.buy_amount_minor == 451_500


def test_transfer_timeout_is_ambiguous_and_lookup_uses_request_id():
    fake = FakeAirwallex()
    fake.fail_transfer = "timeout"
    aw = _adapter(fake)
    with pytest.raises(ProviderAmbiguous):
        aw.create_transfer(request_id="rid-1", amount_minor=480_000, currency="GBP", destination="ben_1", reference="r")
    sent = json.loads(fake.calls[-1].content)
    assert sent["request_id"] == "rid-1" and sent["transfer_amount"] == "4800.00" and sent["beneficiary_id"] == "ben_1"
    found = aw.find_transfer("rid-1")
    assert found.provider_id == "tr1" and found.status == "sent"  # SENT normalised, not treated as final


def test_deposit_simulation_does_not_send_currency():
    fake = FakeAirwallex()
    aw = _adapter(fake)
    aw.simulate_deposit(global_account_id="ga_usd", currency="USD", amount_minor=500_000, payer_name="P", reference="R")
    body = json.loads(fake.calls[-1].content)
    assert "currency" not in body and body["amount"] == 5000.0 and body["global_account_id"] == "ga_usd"


def test_payment_link_unavailable_is_reported_not_faked():
    aw = _adapter(FakeAirwallex())
    with pytest.raises(ProviderUnsupported):
        aw.create_payment_link(title="t", amount_minor=120_000, currency="GBP", reference="INV-2260")


def test_airwallex_readiness_is_read_only_and_follows_the_hackathon_guide():
    """Login, list global accounts, list current balances: GETs only, nothing created, no money moved."""
    calls = []

    def fake(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/authentication/login"):
            assert request.headers["x-client-id"] == "cid" and request.headers["x-api-key"] == "key"
            return httpx.Response(201, json={"token": "t", "expires_at": "2099-01-01T00:00:00+00:00"})
        assert request.headers["authorization"] == "Bearer t"
        if request.url.path.endswith("/global_accounts"):
            return httpx.Response(200, json={"items": [{"id": "ga_1", "currency": "USD", "status": "ACTIVE", "account_number": "x"}], "has_more": False})
        if request.url.path.endswith("/balances/current"):
            return httpx.Response(200, json=[{"currency": "USD", "available_amount": 1000.5, "total_amount": 1000.5}])
        return httpx.Response(404)

    r = AirwallexSandbox("cid", "key", transport=httpx.MockTransport(fake)).readiness()
    assert r == {"global_accounts": [{"id": "ga_1", "currency": "USD", "status": "ACTIVE"}],
                 "balances": [{"currency": "USD", "available_amount": 1000.5}]}
    assert [m for m, _ in calls[1:]] == ["GET", "GET"]


def test_payloads_follow_the_official_reference():
    """Checked against airwallex.com/docs (27 Oct 2026): transfer and conversion amounts are strings,
    rejected/recalled approvals never move money, deposits name their global account in global_account_id."""
    from ledgerline.providers.base import normalise_transfer_status
    from ledgerline.webhooks import _parse_deposit as parse_deposit_event

    assert normalise_transfer_status("approval_rejected") == "cancelled"
    assert normalise_transfer_status("approval_recalled") == "cancelled"
    assert normalise_transfer_status("in_approval") == "processing"
    assert normalise_transfer_status("sent") == "sent"  # SENT is never final
    event = {"id": "evt_1", "name": "deposit.settled", "data": {"object": {
        "id": "dep_1", "amount": 1250.5, "currency": "USD", "status": "SETTLED", "settled_at": "2026-10-27T10:00:00Z",
        "global_account_id": "ga_usd", "payer": {"name": "ACME ROBOTICS INC"}, "reference": "INV 2231"}}}
    d = parse_deposit_event(event)
    assert (d["provider_ref"], d["amount_minor"], d["payer_name"], d["reference"], d["global_account_id"]) == \
        ("dep_1", 125050, "ACME ROBOTICS INC", "INV 2231", "ga_usd")


def test_payer_agent_never_creates_a_signing_identity(tmp_path):
    """With no stored key the agent reports no_agent instead of minting a key that would not match the registry."""
    from ledgerline.payer_agents.keys import keys_path

    answers, _ = explain_payments(tmp_path, [{"customer_id": "CUST-EASTGATE", "deposit_id": "DEP-1006", "currency": "GBP",
                                              "amount_minor": 480_000, "received_at": "2026-10-27T00:00:00Z", "reference": ""}],
                                  transport="memory")
    assert answers[0]["status"] == "no_agent" and not keys_path(tmp_path).exists()
