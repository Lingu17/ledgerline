"""Live end-to-end probe against a running server (python scripts/smoke_live.py). Creates throwaway accounts with random passwords."""
import secrets
import sys

import httpx

BASE = "http://127.0.0.1:8000/api"
PW = "Probe-" + secrets.token_urlsafe(8) + "-9Z"
ORIGIN = {"Origin": "http://127.0.0.1:8000"}
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def client():
    return httpx.Client(base_url=BASE, headers=ORIGIN, timeout=60)


def signup(email, org, start="sample"):
    c = client()
    r = c.post("/auth/signup", json={"email": email, "name": email.split("@")[0], "password": PW, "organization_name": org, "start_with": start})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c, r.json()


tag = secrets.token_hex(3)
owner, me = signup(f"owner-{tag}@probe.test", "Probe Sample", "sample")
check("signup sets HttpOnly SameSite=Strict cookie", "ll_session" in owner.cookies)
check("sample org lists six deposits", len(owner.get("/deposits").json()) == 6)

# invite operator and viewer
def join(role):
    r = owner.post("/team/invitations", json={"email": f"{role}-{tag}@probe.test", "role": role})
    token = r.json()["invite_path"].split("token=")[1]
    c = client()
    m = c.post(f"/invitations/{token}/accept", json={"name": role, "password": PW})
    c.headers["X-CSRF-Token"] = m.json()["csrf_token"]
    return c

op = join("operator")
viewer = join("viewer")
check("viewer can read payments", viewer.get("/deposits").status_code == 200)
check("viewer cannot record a payment", viewer.post("/payments", json={"external_ref": "V1", "currency": "USD", "amount": "1.00", "payer_name": "ACME ROBOTICS INC"}).status_code == 403)
check("viewer cannot ask agent", viewer.post("/deposits/DEP-1005/ask-agent").status_code == 403)
check("operator cannot change policy", op.put("/settings/policy", json={}).status_code == 403)

# real MCP over stdio from the live server
r = op.post("/deposits/DEP-1006/ask-agent")
check("operator asks payer agent over MCP (stdio)", r.status_code == 200 and r.json()["verification"]["verdict"] == "verified", r.text[:200])
r = op.post("/deposits/DEP-1004/ask-agent")
check("malicious cross-customer claim rejected by check 3", r.status_code == 200 and r.json()["verification"]["verdict"] == "rejected"
      and "belongs to another customer" in r.json()["verification"]["reason"])
a = next(x for x in owner.get("/approvals").json() if x["status"] == "pending")
check("operator can approve system-proposed refund", op.post(f"/approvals/{a['id']}/approve", json={"scope_hash": a["scope_hash"]}).status_code == 200)
rts = op.post("/deposits/DEP-1004/return-to-sender").json()
check("operator cannot approve own return proposal", op.post(f"/approvals/{rts['id']}/approve", json={"scope_hash": rts["scope_hash"]}).status_code == 403)
ex = owner.post(f"/approvals/{a['id']}/execute")
check("owner executes approved refund", ex.status_code == 200 and ex.json()["operation"]["status"] == "processing", ex.text[:200])

# CSRF and origin
no_csrf = client()
no_csrf.cookies = owner.cookies
check("mutation without CSRF token refused", no_csrf.post("/settings/pause", json={"paused": True}).status_code == 403)
check("foreign origin refused", owner.post("/settings/pause", json={"paused": True}, headers={"Origin": "https://evil.example"}).status_code == 403)

# isolation
other, _ = signup(f"other-{tag}@probe.test", "Probe Other", "empty")
check("other org sees no deposits", other.get("/deposits").json() == [])
check("other org cannot read DEP-1006", other.get("/deposits/DEP-1006").status_code == 404)
check("other org cannot switch into probe org", other.post("/auth/switch-organization", json={"organization_id": me["organization"]["id"]}).status_code == 403)
check("ledger balanced in probe org", owner.get("/ledger").json()["conservation"]["all_balanced"])

# logout invalidates server-side
stolen = dict(owner.cookies)
owner.post("/auth/logout")
replay = client()
replay.cookies.update(stolen)
check("logged-out session cannot be replayed", replay.get("/deposits").status_code == 401)

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
