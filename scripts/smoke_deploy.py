"""End-to-end probe of a deployed Ledgerline through its public frontend URL (same-origin /api proxy).

  python scripts/smoke_deploy.py https://ledgerline.vercel.app --save state.json   # full probe, remember one account
  python scripts/smoke_deploy.py https://ledgerline.vercel.app --verify state.json # after a backend restart: data still there?

Creates throwaway accounts with random passwords and synthetic data only. The state file holds a
throwaway test password: keep it outside the repository. Exit code 1 on any failed check.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import time

import httpx

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: object, detail: str = "") -> bool:
    ok = bool(cond)
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail[:300]}]" if detail and not ok else ""), flush=True)
    return ok


class Site:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.origin = self.base

    def client(self) -> httpx.Client:
        return httpx.Client(base_url=f"{self.base}/api", headers={"Origin": self.origin, "Sec-Fetch-Site": "same-origin"},
                            timeout=90, follow_redirects=False)

    def signup(self, email: str, password: str, org: str, start: str) -> tuple[httpx.Client, dict, httpx.Response]:
        c = self.client()
        r = c.post("/auth/signup", json={"email": email, "name": email.split("@")[0], "password": password,
                                         "organization_name": org, "start_with": start})
        if r.status_code != 200:
            raise SystemExit(f"signup failed: {r.status_code} {r.text[:300]}")
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        return c, r.json(), r

    def login(self, email: str, password: str) -> tuple[httpx.Client, httpx.Response]:
        c = self.client()
        r = c.post("/auth/login", json={"email": email, "password": password})
        if r.status_code == 200:
            c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        return c, r


def full(site: Site, save: str | None) -> None:
    h = site.client().get("/health")
    check("health endpoint ok through the frontend proxy", h.status_code == 200 and h.json().get("status") == "ok", h.text)
    check("backend reports durable storage", h.json().get("storage") in ("persistent mount", "postgresql"), h.text)
    page = httpx.get(site.base, timeout=60)
    check("frontend serves the app", page.status_code == 200 and "<div id=\"root\">" in page.text)
    check("frontend sends a Content-Security-Policy", "content-security-policy" in page.headers)

    tag, pw = secrets.token_hex(4), "Judge-" + secrets.token_urlsafe(10) + "-7a"
    email = f"probe-{tag}@deploy.test"

    # ---- empty workspace: ordinary operations without the walkthrough
    c, me, r = site.signup(email, pw, f"Probe Co {tag}", "empty")
    cookie = r.headers.get("set-cookie", "")
    check("session cookie is HttpOnly, Secure, SameSite=Strict, Path=/api",
          all(x in cookie for x in ("ll_session=", "HttpOnly", "Secure", "SameSite=strict", "Path=/api")) or
          all(x.lower() in cookie.lower() for x in ("ll_session=", "httponly", "secure", "samesite=strict", "path=/api")), cookie)
    check("cookie is scoped to the frontend host (no Domain attribute)", "domain=" not in cookie.lower(), cookie)
    check("reload keeps the session (/auth/me)", c.get("/auth/me").json()["user"]["email"] == email)
    check("opening balance set", c.post("/treasury/opening-balance", json={"currency": "GBP", "amount": "25000.00"}).status_code == 200)
    cust = c.post("/customers", json={"name": f"Harbour {tag}", "country": "GB", "payer_names": [f"HARBOUR {tag.upper()} LTD"],
                                      "refund_beneficiary": "Harbour - UK account (synthetic)"})
    check("customer created", cust.status_code == 200, cust.text)
    cid = cust.json()["id"]
    inv = c.post("/invoices", json={"customer_id": cid, "currency": "GBP", "amount": "1000.00", "due_date": "2027-01-31",
                                    "description": "Deployment probe"})
    check("invoice created", inv.status_code == 200, inv.text)
    iid = inv.json()["id"]
    pay = c.post("/payments", json={"external_ref": f"PROBE-{tag}", "currency": "GBP", "amount": "970.00",
                                    "payer_name": f"HARBOUR {tag.upper()} LTD", "reference": iid})
    check("payment recorded", pay.status_code == 200 and pay.json()["created"], pay.text)
    dep = c.get(f"/deposits/{pay.json()['deposit_id']}").json()
    check("970 against 1,000 stays partial with 30.00 due",
          dep["category"] == "partial_payment" and c.get(f"/invoices/{iid}").json()["remaining_minor"] == 3000, json.dumps(dep)[:300])
    again = c.post("/payments", json={"external_ref": f"PROBE-{tag}", "currency": "GBP", "amount": "970.00",
                                      "payer_name": f"HARBOUR {tag.upper()} LTD", "reference": iid})
    check("same statement line is idempotent", again.json().get("created") is False, again.text)
    check("ledger balanced (empty workspace)", c.get("/ledger").json()["conservation"]["all_balanced"])

    # ---- security through the proxy
    no_csrf = site.client()
    no_csrf.cookies = c.cookies
    check("mutation without CSRF token refused", no_csrf.post("/settings/pause", json={"paused": True}).status_code == 403)
    check("foreign Origin refused", c.post("/settings/pause", json={"paused": True}, headers={"Origin": "https://evil.example"}).status_code == 403)
    check("unauthenticated API refused", site.client().get("/deposits").status_code == 401)

    # ---- sample workspace: signed MCP evidence, approvals, treasury, refund lifecycle
    s, smeta, _ = site.signup(f"sample-{tag}@deploy.test", pw, f"Sample {tag}", "sample")
    check("sample workspace has six received payments", len(s.get("/deposits").json()) == 6)
    ask = s.post("/deposits/DEP-1006/ask-agent")
    check("payer agent answers over MCP with verified signed evidence",
          ask.status_code == 200 and ask.json()["verification"]["verdict"] == "verified", ask.text)
    bad = s.post("/deposits/DEP-1004/ask-agent")
    check("cross-customer claim rejected by the record check",
          bad.status_code == 200 and bad.json()["verification"]["verdict"] == "rejected", bad.text)
    state = s.get("/demo").json()
    for step in [x["id"] for x in state["steps"] if not x.get("done")]:
        if step == "approve":
            for a in s.get("/approvals").json():
                if a["status"] == "pending":
                    s.post(f"/approvals/{a['id']}/approve", json={"scope_hash": a["scope_hash"]})
        r = s.post("/demo/step", json={"step": step})
        if not check(f"walkthrough step {step}", r.status_code == 200, r.text):
            break
    t = s.get("/treasury").json()
    check("treasury: EUR shortfall covered by a settled conversion",
          any(x["status"] == "paid" for x in t["conversions"]) or any(x["status"] in ("paid", "settled") for x in t["conversions"]), json.dumps(t["conversions"])[:300])
    score = s.get("/overview").json()["scorecard"]
    check("scorecard: no double payments, ledger balanced", score["double_payments"] == 0 and score["ledger_balanced"], json.dumps(score))
    own = s.post("/deposits/DEP-1004/return-to-sender")
    if own.status_code == 200:
        check("proposer cannot approve own refund (four-eyes)",
              s.post(f"/approvals/{own.json()['id']}/approve", json={"scope_hash": own.json()["scope_hash"]}).status_code == 403)

    # ---- isolation between judges
    check("another organization cannot read this one's payment", c.get("/deposits/DEP-1006").status_code == 404)
    check("another organization cannot switch in",
          c.post("/auth/switch-organization", json={"organization_id": smeta["organization"]["id"]}).status_code == 403)

    # ---- sign in again from a fresh browser, then logout invalidation
    c2, r2 = site.login(email, pw)
    check("login from a fresh browser", r2.status_code == 200, r2.text)
    stolen = dict(c2.cookies)
    c2.post("/auth/logout")
    replay = site.client()
    replay.cookies.update(stolen)
    check("logged-out session cannot be replayed", replay.get("/deposits").status_code == 401)

    if save:
        with open(save, "w", encoding="utf-8") as f:
            json.dump({"base": site.base, "email": email, "password": pw, "invoice": iid, "deposit": pay.json()["deposit_id"],
                       "sample_email": f"sample-{tag}@deploy.test", "saved_at": time.time()}, f)
        print(f"saved throwaway account to {save}")


def verify(site: Site, path: str) -> None:
    st = json.load(open(path, encoding="utf-8"))
    h = site.client().get("/health")
    check("health ok after restart", h.status_code == 200 and h.json().get("status") == "ok", h.text)
    c, r = site.login(st["email"], st["password"])
    check("account survives restart (login)", r.status_code == 200, r.text)
    if r.status_code == 200:
        check("invoice survives with the same balance", c.get(f"/invoices/{st['invoice']}").json().get("remaining_minor") == 3000)
        check("payment survives with its decision", c.get(f"/deposits/{st['deposit']}").json().get("category") == "partial_payment")
        check("ledger still balanced", c.get("/ledger").json()["conservation"]["all_balanced"])
    s, r = site.login(st["sample_email"], st["password"])
    if check("sample account survives restart", r.status_code == 200, r.text):
        check("sample refund lifecycle still recorded", s.get("/deposits/DEP-1006").json().get("status") == "refunded")
        a = s.post("/deposits/DEP-1005/ask-agent")  # payer-agent signing keys must still exist on disk
        check("payer-agent signing keys survive (MCP call after restart)", a.status_code in (200, 409), a.text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--save")
    ap.add_argument("--verify")
    a = ap.parse_args()
    site = Site(a.base)
    verify(site, a.verify) if a.verify else full(site, a.save)
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
