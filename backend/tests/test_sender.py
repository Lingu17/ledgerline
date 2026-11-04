"""The sending service: with it turned on, the app holds no Airwallex keys, cannot unseal stored credentials, cannot
call create_transfer, and asks for money-out by id only. Errors keep their type; a stopped service sends nothing."""
import os
import socket
import threading

import pytest
from fastapi.testclient import TestClient

from ledgerline import connections, payouts, sender
from ledgerline.api.app import create_app
from ledgerline.config import load_settings
from ledgerline.providers import airwallex

from .conftest import signup

KEY = "very-secret-api-key"
READY = {"global_accounts": [{"id": "ga_eur", "supported_currencies": ["EUR"]}], "balances": [{"currency": "EUR", "available_amount": 10}]}
BASE = {"LEDGERLINE_PAYER_MCP_TRANSPORT": "memory", "ANTHROPIC_API_KEY": "", "GOOGLE_CLIENT_ID": "", "APPLE_CLIENT_ID": ""}


@pytest.fixture
def pair(tmp_path, monkeypatch):
    """The sending service (with the keys) and the app (without them), sharing one data directory."""
    monkeypatch.setattr(airwallex.AirwallexSandbox, "readiness", lambda self: READY)
    keys = load_settings({**BASE, "LEDGERLINE_DATA_DIR": str(tmp_path), "AIRWALLEX_CLIENT_ID": "cid", "AIRWALLEX_API_KEY": "server-key",
                          "LEDGERLINE_CONNECTIONS_KEY_PATH": str(tmp_path / "sender" / "connections.key")})
    server = sender.serve(keys, "tcp:127.0.0.1:0")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f"tcp:127.0.0.1:{server.server_address[1]}"
    app_settings = load_settings({**BASE, "LEDGERLINE_DATA_DIR": str(tmp_path), "LEDGERLINE_SENDER_SOCKET": address,
                                  "LEDGERLINE_PG_SCHEMA_PREFIX": keys.pg_schema_prefix,  # one database for both, as in production
                                  "AIRWALLEX_CLIENT_ID": "", "AIRWALLEX_API_KEY": ""})
    app = create_app(app_settings)
    c = TestClient(app)
    signup(c, email="owner@real.test", org="Real Company", start_with="empty")
    r = c.post("/api/integrations/airwallex/connect", json={"client_id": "client-123456", "api_key": KEY, "webhook_secret": "whsec-12345678"})
    assert r.status_code == 200, r.text
    yield {"app": app, "client": c, "keys": keys, "server": server, "address": address}
    server.shutdown()
    server.server_close()


def test_the_app_holds_no_keys_and_cannot_unseal_or_send_by_itself(pair):
    app, c = pair["app"], pair["client"]
    blob = app.state.control.org(c.org_id)["airwallex_credentials_enc"]
    assert KEY not in blob
    with pytest.raises(connections.ConnectionError_):
        connections.unseal(app.state.settings, c.org_id, blob)
    assert connections.unseal(pair["keys"], c.org_id, blob) == ("client-123456", KEY)  # sealed by the service, with its key
    assert not (app.state.settings.data_dir / "connections.key").exists()
    ctx = app.state.orgs.get(c.org_id)
    assert isinstance(ctx.provider, sender.SenderProxy) and ctx.sandbox is ctx.provider
    for method in ("create_transfer", "create_conversion"):
        with pytest.raises(sender.SenderRefused):
            getattr(ctx.provider, method)
    assert ctx.provider.readiness() == READY  # reads go through the service
    status = c.get("/api/status").json()["bank"]
    assert status["airwallex_keys_held_by"] == "sending service" and status["mode"] == "airwallex_sandbox"


def test_money_out_is_asked_for_by_id_and_runs_inside_the_service(pair, monkeypatch):
    app, c = pair["app"], pair["client"]
    seen = []

    def spy(ctx, approval_id, actor, automatic=False):
        seen.append((type(ctx.provider).__name__, approval_id, actor, automatic))
        return {"status": "processing"}
    monkeypatch.setattr(sender, "_money_out", lambda: {"send_refund": spy})
    ctx = app.state.orgs.get(c.org_id)
    assert payouts.execute_refund(ctx, "APR-1", "second@real.test", automatic=True) == {"status": "processing"}
    assert seen == [("AirwallexSandbox", "APR-1", "second@real.test", True)]  # the real bank client, in the service


def test_errors_keep_their_type_across_the_socket(pair):
    app, c = pair["app"], pair["client"]
    with pytest.raises(payouts.PayoutError, match="unknown approval"):
        payouts.execute_refund(app.state.orgs.get(c.org_id), "APR-NOPE", "owner@real.test")
    r = c.post("/api/approvals/APR-NOPE/execute")
    assert r.status_code == 409 and "unknown approval" in r.text


def test_the_service_refuses_anything_but_ids_and_the_fixed_reads(pair):
    client, org = sender.SenderClient(pair["address"]), pair["client"].org_id
    with pytest.raises(sender.SenderRefused, match="ids only"):
        client.call("send_refund", org, args=["APR-1", "x@real.test"], kwargs={"amount_minor": [1]})
    with pytest.raises(sender.SenderRefused):
        client.call("provider", org, op="create_transfer", args=[], kwargs={})
    with pytest.raises(sender.SenderRefused):
        client.call("pay_anyone", org, args=[], kwargs={})


def test_a_company_not_connected_to_airwallex_never_reaches_the_service(pair):
    app = pair["app"]
    c = TestClient(app)
    signup(c, email="practice@real.test", org="Practice", start_with="sample")
    assert app.state.orgs.get(c.org_id).sender is None
    while c.get("/api/demo").json()["next"] in ("deposits", "links", "agents"):  # practice steps run on the simulated bank
        assert c.post("/api/demo/step", json={"step": c.get("/api/demo").json()["next"]}).status_code == 200
    assert c.get("/api/demo").json()["next"] == "treasury"
    with pytest.raises(sender.SenderRefused, match="not connected to Airwallex"):
        sender.SenderClient(pair["address"]).call("send_refund", c.org_id, args=["APR-1", "x"], kwargs={})


def test_a_stopped_service_sends_nothing_and_says_so(pair):
    app, c = pair["app"], pair["client"]
    pair["server"].shutdown()
    pair["server"].server_close()
    with pytest.raises(sender.SenderUnavailable, match="nothing was sent"):
        payouts.execute_refund(app.state.orgs.get(c.org_id), "APR-1", "owner@real.test")
    r = c.post("/api/approvals/APR-1/execute")
    assert r.status_code == 503 and "nothing was sent" in r.text


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="Unix sockets are not available on this platform")
def test_over_a_unix_socket_only_the_owner_and_group_can_connect(tmp_path):
    keys = load_settings({**BASE, "LEDGERLINE_DATA_DIR": str(tmp_path)})
    path = str(tmp_path / "send.sock")
    server = sender.serve(keys, f"unix:{path}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert oct(os.stat(path).st_mode & 0o777) == "0o660"
        with pytest.raises(KeyError):
            sender.SenderClient(f"unix:{path}").call("send_refund", "org_000000000000", args=["APR-1", "x"], kwargs={})
    finally:
        server.shutdown()
        server.server_close()


def test_the_test_only_tcp_address_must_be_loopback():
    with pytest.raises(ValueError, match="loopback"):
        sender.SenderClient("tcp:10.0.0.5:9000")


def test_bank_results_cross_the_socket_unchanged():
    from datetime import datetime, timezone
    from decimal import Decimal

    from ledgerline.providers.base import Quote, TransferResult

    q = Quote("q1", "EUR", "USD", 100, 108, Decimal("1.08"), datetime(2026, 11, 4, tzinfo=timezone.utc), "airwallex")
    t = TransferResult("tr1", "req", "sent", "SENT")
    assert sender._decode(sender._encode([q, {"t": t}])) == [q, {"t": t}]
    assert sender._plain(["APR-1", "a@b", True, None]) and not sender._plain([{"x": 1}]) and not sender._plain([[1]])


def test_the_service_refuses_to_listen_on_tcp_outside_tests(monkeypatch):
    monkeypatch.setenv("LEDGERLINE_SENDER_LISTEN", "tcp:127.0.0.1:0")
    monkeypatch.delenv("LEDGERLINE_SENDER_ALLOW_TCP", raising=False)
    with pytest.raises(SystemExit, match="Unix socket"):
        sender.main()


def test_ping_answers_without_the_bank(pair, monkeypatch):
    """harden.sh checks the socket with ping, so a bank outage cannot undo the step."""
    def no_bank(*_a, **_k):
        raise AssertionError("ping must not reach Airwallex")
    monkeypatch.setattr(airwallex.AirwallexSandbox, "readiness", no_bank)
    assert sender.SenderClient(pair["address"], timeout=10).call("ping", "") == {"pong": True}
