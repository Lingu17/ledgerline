"""A customer's own payer agent, reached over the network.

The reference agent (tools/payer_agent/agent.py) runs here as a separate process with its own key, on localhost,
which only the test-only loopback allowance permits. Everything Ledgerline does with its answer is the same three
checks as for any other agent.
"""
import base64
import json
import socket
import subprocess
import sys
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient

from ledgerline import crypto
from ledgerline.api.app import create_app
from ledgerline.payer_agents import remote
from ledgerline.payer_agents.client import QUESTION_FIELDS

from .conftest import signup
from .test_saas import _invite_and_join

ROOT = Path(__file__).resolve().parents[2]
QUESTION = {"customer_id": "CUST-DUNMORE", "deposit_id": "DEP-1005", "currency": "USD", "amount_minor": 120_000,
            "received_at": "2026-11-03T00:00:00Z", "reference": ""}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def agent(tmp_path_factory):
    """The reference agent as its own process: its own key file, its own answers, a real HTTP port."""
    d = tmp_path_factory.mktemp("agent")
    answers = d / "answers.json"
    answers.write_text(json.dumps([
        {"currency": "USD", "amount_minor": 120_000, "invoice_id": "INV-2291", "reason": "advance_payment", "note": "Advance for March."},
        {"currency": "GBP", "amount_minor": 480_000, "invoice_id": "INV-2238", "reason": "duplicate_payment", "note": "Paid twice in error."},
    ]))
    port = _free_port()
    proc = subprocess.Popen([sys.executable, str(ROOT / "tools/payer_agent/agent.py"), "--port", str(port),
                             "--key-file", str(d / "key.json"), "--answers", str(answers)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    public_key = proc.stdout.readline().split(": ", 1)[1].strip()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield {"url": f"http://127.0.0.1:{port}/mcp", "public_key": public_key, "key_file": d / "key.json"}
    proc.terminate()
    proc.wait(10)


@pytest.fixture(autouse=True)
def _fresh_backoff():
    from ledgerline.payer_agents import client as agent_client

    agent_client._failures.clear()
    yield
    agent_client._failures.clear()


@pytest.fixture
def loopback_app(settings):
    settings.payer_agent_allow_loopback = True
    return create_app(settings)


def practice_client(app, email="owner@practice.test"):
    c = TestClient(app)
    signup(c, email=email, org="Practice", start_with="sample")
    assert c.post("/api/demo/step", json={"step": "deposits"}).status_code == 200
    return c


def register(c, url, public_key, customer="CUST-DUNMORE"):
    return c.put(f"/api/customers/{customer}/payer-agent", json={"url": url, "public_key": public_key})


def evidence_for(c, deposit_id):
    return next(r for r in c.get("/api/evidence").json() if r["deposit"]["id"] == deposit_id)["evidence"]


def test_reference_agent_keeps_its_private_key_and_imports_nothing_from_ledgerline(agent):
    source = (ROOT / "tools/payer_agent/agent.py").read_text(encoding="utf-8")
    assert "import ledgerline" not in source and "from ledgerline" not in source
    stored = json.loads(agent["key_file"].read_text())["private_key"]
    assert crypto.public_from_private(stored) == agent["public_key"]


def test_own_agent_answer_revises_the_plan(loopback_app, agent):
    c = practice_client(loopback_app)
    r = register(c, agent["url"], agent["public_key"])
    assert r.status_code == 200 and r.json()["agent_url"] == agent["url"]
    assert r.json()["agent_key_id"] == crypto.key_id_for(agent["public_key"])
    r = c.post("/api/deposits/DEP-1005/ask-agent")
    assert r.status_code == 200, r.text
    assert r.json()["verification"]["verdict"] == "verified"
    assert c.get("/api/deposits/DEP-1005").json()["status"] == "credited"
    ev = evidence_for(c, "DEP-1005")[-1]
    assert ev["transport"] == "mcp/http 127.0.0.1" and ev["verdict"] == "verified"
    actions = [e["action"] for e in c.get("/api/audit/export").json()["audit_events"]]
    assert "customer.payer_agent_registered" in actions
    # Who set the key is on the customer and on every answer the key signs.
    dunmore = next(x for x in c.get("/api/customers").json() if x["id"] == "CUST-DUNMORE")
    assert dunmore["agent_key_set_by"] == "owner@practice.test" and dunmore["agent_key_set_at"]
    signature = next(ch for ch in ev["checks"] if ch["name"] == "signature")
    assert "key set by owner@practice.test on " in signature["detail"]


def test_own_agent_cannot_move_money_and_refunds_keep_two_people(loopback_app, agent):
    c = practice_client(loopback_app, "owner2@practice.test")
    assert register(c, agent["url"], agent["public_key"], "CUST-EASTGATE").status_code == 200
    assert c.post("/api/deposits/DEP-1006/ask-agent").json()["verification"]["verdict"] == "verified"
    a = next(x for x in c.get("/api/approvals").json() if x["deposit_id"] == "DEP-1006")
    assert a["status"] == "pending" and a["created_by"] == "system" and a["sender_must_differ"]
    assert [o for o in c.get("/api/operations").json() if o["kind"] == "refund"] == []


def test_wrong_key_is_rejected(loopback_app, agent):
    c = practice_client(loopback_app, "owner3@practice.test")
    other = crypto.generate_keypair()[1]
    assert register(c, agent["url"], other).status_code == 200
    r = c.post("/api/deposits/DEP-1005/ask-agent").json()["verification"]
    assert r["verdict"] == "rejected" and "Signature check failed" in r["reason"]
    assert c.get("/api/deposits/DEP-1005").json()["status"] == "escalated"


def test_tampered_answer_is_rejected(loopback_app, agent, monkeypatch):
    real = remote.ask_remote

    def tamper(*a, **k):
        answers = real(*a, **k)
        answers[0]["envelope"]["claim"]["invoice_id"] = "INV-2244"  # changed in transit; the signature no longer fits
        return answers
    monkeypatch.setattr(remote, "ask_remote", tamper)
    c = practice_client(loopback_app, "owner4@practice.test")
    register(c, agent["url"], agent["public_key"])
    r = c.post("/api/deposits/DEP-1005/ask-agent").json()["verification"]
    assert r["verdict"] == "rejected" and "signature does not verify" in r["reason"]


def test_stale_answer_is_rejected(loopback_app, agent):
    c = practice_client(loopback_app, "owner5@practice.test")
    register(c, agent["url"], agent["public_key"])
    loopback_app.state.orgs.get(c.org_id).clock.advance(timedelta(hours=1))  # our clock is an hour past the agent's answer
    r = c.post("/api/deposits/DEP-1005/ask-agent").json()["verification"]
    assert r["verdict"] == "rejected" and "expired" in r["reason"]


def test_only_the_question_leaves_the_server(loopback_app, agent, monkeypatch):
    sent = []
    real = remote.ask_remote

    def spy(url, reqs, *a, **k):
        sent.extend(reqs)
        return real(url, reqs, *a, **k)
    monkeypatch.setattr(remote, "ask_remote", spy)
    c = practice_client(loopback_app, "owner6@practice.test")
    register(c, agent["url"], agent["public_key"])
    c.post("/api/deposits/DEP-1005/ask-agent")
    assert sent and all(set(r) == set(QUESTION_FIELDS) for r in sent)


def test_clearing_returns_a_practice_customer_to_its_simulated_agent(loopback_app, agent):
    c = practice_client(loopback_app, "owner7@practice.test")
    simulated_key = next(x for x in c.get("/api/customers").json() if x["id"] == "CUST-DUNMORE")["agent_public_key"]
    register(c, agent["url"], agent["public_key"])
    r = c.delete("/api/customers/CUST-DUNMORE/payer-agent")
    assert r.status_code == 200 and r.json()["agent_url"] is None and r.json()["agent_public_key"] == simulated_key
    assert c.post("/api/deposits/DEP-1005/ask-agent").json()["verification"]["verdict"] == "verified"
    assert evidence_for(c, "DEP-1005")[-1]["transport"].startswith("mcp/")
    assert not evidence_for(c, "DEP-1005")[-1]["transport"].startswith("mcp/http")


def test_only_an_owner_registers_an_agent(loopback_app, agent):
    c = practice_client(loopback_app, "owner8@practice.test")
    op = _invite_and_join(c, loopback_app, "op@practice.test", "operator")
    assert register(op, agent["url"], agent["public_key"]).status_code == 403
    assert register(c, agent["url"], agent["public_key"]).status_code == 200
    r = op.patch("/api/customers/CUST-DUNMORE", json={"agent_public_key": crypto.generate_keypair()[1]})
    assert r.status_code == 422 and "own agent" in r.json()["detail"]


# --------------------------------------------------------------------------- refusals
@pytest.mark.parametrize("url", [
    "http://agent.example.com/mcp",            # not https
    "ftp://agent.example.com/mcp",
    "https://user:secret@agent.example.com/mcp",
    "https://10.0.0.5/mcp",                    # private
    "https://192.168.1.10/mcp",
    "https://172.16.0.1/mcp",
    "https://100.64.0.1/mcp",                  # shared address space
    "https://169.254.169.254/latest",          # cloud metadata (link-local)
    "https://127.0.0.1/mcp",                   # loopback
    "https://localhost/mcp",
    "https://[::1]/mcp",
    "https://[fd00::1]/mcp",                   # IPv6 private
    "https://[fe80::1]/mcp",                   # IPv6 link-local
    "https://[::ffff:127.0.0.1]/mcp",          # IPv4-mapped loopback
    "https://0.0.0.0/mcp",
    "https://224.0.0.1/mcp",                   # multicast
    "https://2130706433/mcp",                  # 127.0.0.1 written as one decimal number
    "https://0177.0.0.1/mcp",                  # octal loopback
    "https://0x7f.1/mcp",                      # hex loopback
    "https://2130706433./mcp",                 # the same with a trailing dot (final verification N2)
    "https://localhost./mcp",
    "https://127.0.0.1./mcp",
    "https://agent.example.com/mcp#frag",
    "",
    "https://" + "a" * 300 + ".example.com/mcp",
])
def test_registration_refuses_unsafe_urls(client, url):
    r = register(client, url, crypto.generate_keypair()[1])
    assert r.status_code == 422, (url, r.status_code, r.text)
    assert next(x for x in client.get("/api/customers").json() if x["id"] == "CUST-DUNMORE")["agent_url"] is None


def test_plain_http_localhost_needs_the_test_only_allowance(client, agent):
    assert register(client, agent["url"], agent["public_key"]).status_code == 422


@pytest.mark.parametrize("addresses", [["10.1.2.3"], ["169.254.169.254"], ["127.0.0.1"], ["fd12::5"],
                                       ["93.184.216.34", "10.0.0.1"],
                                       ["64:ff9b::a9fe:a9fe"],          # NAT64 carrying 169.254.169.254
                                       ["64:ff9b::a00:5"],              # NAT64 carrying 10.0.0.5
                                       ["64:ff9b:1::1"],                # local-use NAT64
                                       ["2002:a00:5::1"],               # 6to4 carrying 10.0.0.5
                                       ["2002:a9fe:a9fe::1"],           # 6to4 carrying the metadata address
                                       ["::ffff:10.0.0.5"]])
def test_a_name_that_resolves_to_a_non_public_address_is_refused_at_connect_time(addresses):
    with pytest.raises(remote.AgentRefused):
        remote.ask_remote("https://agent.example.com/mcp", [QUESTION], resolve=lambda _h, _p: addresses)


def test_a_refused_address_at_ask_time_leaves_the_payment_waiting(client, monkeypatch):
    client.post("/api/demo/step", json={"step": "deposits"})
    assert register(client, "https://agent.example.com/mcp", crypto.generate_keypair()[1]).status_code == 200
    monkeypatch.setattr(remote, "_resolve", lambda _h, _p: ["169.254.169.254"])  # DNS now points at the metadata service
    r = client.post("/api/deposits/DEP-1005/ask-agent")
    assert r.status_code == 502 and "non-public address" in r.json()["detail"]
    assert client.get("/api/deposits/DEP-1005").json()["status"] == "awaiting_evidence"
    assert all(row["deposit"]["id"] != "DEP-1005" or not row["evidence"] for row in client.get("/api/evidence").json())


# --------------------------------------------------------------------------- limits on what comes back
class _Server:
    def __init__(self, handler):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/mcp"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


def test_an_oversized_response_is_cut_off():
    class Big(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", 0)))  # read the request, or closing resets the connection
            body = b"x" * (remote.MAX_RESPONSE_BYTES + 50_000)
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a):
            pass
    s = _Server(Big)
    try:
        with pytest.raises(remote.AgentUnreachable, match="larger than"):
            remote.ask_remote(s.url, [QUESTION], allow_loopback=True)
    finally:
        s.close()


def test_a_slow_agent_times_out(monkeypatch):
    monkeypatch.setattr(remote, "READ_TIMEOUT", 0.5)
    monkeypatch.setattr(remote, "OVERALL_DEADLINE", 3.0)

    class Slow(BaseHTTPRequestHandler):
        def do_POST(self):
            time.sleep(2)

        def log_message(self, *_a):
            pass
    s = _Server(Slow)
    try:
        with pytest.raises(remote.AgentUnreachable, match="in time|could not reach"):
            remote.ask_remote(s.url, [QUESTION], allow_loopback=True)
    finally:
        s.close()


def test_no_cookies_or_credentials_are_sent():
    seen = []

    class Cookie(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append({k.lower(): v for k, v in self.headers.items()})
            self.send_response(200)
            self.send_header("set-cookie", "session=abc; Path=/")
            self.send_header("content-length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_a):
            pass
    s = _Server(Cookie)

    async def twice():
        async with remote.guarded_http_client(allow_loopback=True) as http:
            await http.get(s.url)
            await http.get(s.url, headers={"authorization": "Bearer should-not-leave"})
    try:
        anyio.run(twice)
    finally:
        s.close()
    assert len(seen) == 2 and all("cookie" not in h and "authorization" not in h for h in seen)


class _SlowAgent(BaseHTTPRequestHandler):
    hits = 0

    def do_POST(self):
        type(self).hits += 1
        self.rfile.read(int(self.headers.get("content-length", 0)))
        time.sleep(4)

    def log_message(self, *_a):
        pass


def test_one_organizations_slow_agents_cannot_hold_up_another(loopback_app, monkeypatch):
    from ledgerline import agent_loop
    from ledgerline.payer_agents import client as agent_client

    monkeypatch.setattr(agent_client, "ROUND_BUDGET", 1.5)
    slow = practice_client(loopback_app, "slow@practice.test")
    servers = [_Server(_SlowAgent) for _ in range(3)]
    try:
        for customer, s in zip(("CUST-FJORD", "CUST-DUNMORE", "CUST-EASTGATE"), servers):
            assert register(slow, s.url, crypto.generate_keypair()[1], customer).status_code == 200
        started = time.monotonic()
        r = agent_loop.ask_pending(loopback_app.state.orgs.get(slow.org_id))
        assert time.monotonic() - started < 3.5, "the round must stop at its budget, not wait for every slow agent"
        assert r["asked"] == 0
        assert all(slow.get(f"/api/deposits/{d}").json()["status"] == "awaiting_evidence" for d in ("DEP-1004", "DEP-1005", "DEP-1006"))
        other = practice_client(loopback_app, "other@practice.test")  # simulated agents, a different organization
        started = time.monotonic()
        assert agent_loop.ask_pending(loopback_app.state.orgs.get(other.org_id))["asked"] == 3
        assert time.monotonic() - started < 10
    finally:
        for s in servers:
            s.close()


def test_an_agent_that_keeps_failing_is_left_alone_for_a_while(loopback_app):
    from ledgerline.payer_agents.client import ask_agents

    class Broken(BaseHTTPRequestHandler):
        hits = 0

        def do_POST(self):
            type(self).hits += 1
            self.rfile.read(int(self.headers.get("content-length", 0)))
            self.send_response(500)
            self.send_header("content-length", "0")
            self.end_headers()

        def log_message(self, *_a):
            pass
    c = practice_client(loopback_app, "broken@practice.test")
    s = _Server(Broken)
    try:
        register(c, s.url, crypto.generate_keypair()[1])
        ctx = loopback_app.state.orgs.get(c.org_id)
        q = [dict(QUESTION, unapplied_minor=120_000)]
        for _ in range(3):
            assert ask_agents(ctx, q)[0][1] is None
        hits = Broken.hits
        _q, answer, _t, problem = ask_agents(ctx, q)[0]
        assert answer is None and "failed 3 times in a row" in problem and Broken.hits == hits  # not contacted again
        other = practice_client(loopback_app, "other-org@practice.test")  # same URL, another organization: not backed off
        register(other, s.url, crypto.generate_keypair()[1])
        ask_agents(loopback_app.state.orgs.get(other.org_id), q)
        assert Broken.hits > hits  # contacted (the client may retry its first request)
    finally:
        s.close()


def test_at_most_twenty_customers_have_their_own_agent(loopback_app, agent):
    c = practice_client(loopback_app, "many@practice.test")
    ids = []
    for i in range(21):
        r = c.post("/api/customers", json={"name": f"Payer {i:02d} Ltd", "country": "GB", "payer_names": [f"PAYER {i:02d} LTD"],
                                           "refund_beneficiary": f"Payer {i:02d} account"})
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
    for cid in ids[:20]:
        assert register(c, agent["url"], agent["public_key"], cid).status_code == 200
    r = register(c, agent["url"], agent["public_key"], ids[20])
    assert r.status_code == 422 and "at most 20" in r.json()["detail"]


def test_a_redirect_to_another_origin_is_not_followed():
    hits = []

    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(self.path)
            self.send_response(307)
            self.send_header("location", "http://169.254.169.254/latest/meta-data")
            self.send_header("content-length", "0")
            self.end_headers()

        def log_message(self, *_a):
            pass
    s = _Server(Redirect)
    try:
        with pytest.raises((remote.AgentUnreachable, remote.AgentRefused)):
            remote.ask_remote(s.url, [QUESTION], allow_loopback=True)
    finally:
        s.close()
    # The client may retry its first request, but only ever at the agent's own address, never at the redirect target.
    assert hits and set(hits) == {"/mcp"}


def test_an_outside_exchange_is_recorded_as_proof_an_owner_can_download(loopback_app, agent):
    """The record a reviewer reads: where the answer came from, which key signed it, the three checks, and the plan
    before and after. Downloaded as the evidence file the docs commit."""
    c = practice_client(loopback_app)
    register(c, agent["url"], agent["public_key"])
    assert c.post("/api/deposits/DEP-1005/ask-agent").status_code == 200
    r = c.get("/api/agents/outside-proof")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    runs = r.json()["runs"]
    assert len(runs) == 1
    run = runs[0]
    assert run["deposit_id"] == "DEP-1005" and run["endpoint_host"] == "127.0.0.1"
    assert run["key_id"] == crypto.key_id_for(agent["public_key"]) and run["signature_valid"] is True
    assert run["checks"] == {"signature": True, "binding": True, "records": True} and run["verdict"] == "verified"
    assert run["plan_before"]["category"] == "apparent_duplicate" and run["plan_after"]["category"] == "verified_advance_credit"
    # The simulated agents on this server leave no such record: only an outside agent's answer counts as one.
    c2 = practice_client(loopback_app, email="second@practice.test")
    c2.post("/api/deposits/DEP-1005/ask-agent")
    assert c2.get("/api/agents/outside-proof").json()["runs"] == []
    from .test_saas import _invite_and_join

    op = _invite_and_join(c, loopback_app, "op2@practice.test", "operator")
    assert op.get("/api/agents/outside-proof").status_code == 403  # an Owner's download
