# Ledgerline security scan — November 2026

**Scope:** Authorised security testing of the owner's own project, against a **local copy only**.
No real keys were used; the live site (`35-207-220-110.sslip.io`) and the `main` / `deploy/vercel-render`
deployment paths were never touched. All traffic was against `http://127.0.0.1:8000` on this machine.

**Target commit:** `d22f23243d908fc02b28d3a835cf82b157f6d466` (branch `deploy/vercel-render`,
_"Account basics: change your name, an owner's reset link, leave, delete a company, delete your account"_).

**How the app was run:** `python -m ledgerline` with the **local simulated bank**
(`LEDGERLINE_PROVIDER=local`) and the **offline deterministic Claude fixture** (no `ANTHROPIC_API_KEY`;
`/api/status` reports `claude: deterministic_fixture`). Two companies were created:

| Company | Kind | Users (per role) |
|:--|:--|:--|
| **A** — "Alpha Practice" | `sample` (Practice) | `owner.a@`, `op.a@`, `view.a@` |
| **B** — "Bravo Trading" | `workspace` (real) | `owner.b@`, `op.b@`, `view.b@` |

**Tooling:** semgrep 1.183.0, bandit 1.9.4, pip-audit 2.10.1, npm 10.9.9, OWASP ZAP 2.16.1,
Playwright (Chromium) for DOM/XSS verification, plus ~95 hand-crafted HTTP checks over real HTTP.

---

## Executive summary

The application is **strongly hardened**. Across 25,310 ZAP active-scan requests and ~95 hand-crafted
attacks, **no cross-tenant data access, no privilege escalation, no CSRF bypass, no injection (SQL/XSS/path),
no SSRF, and no webhook forgery or replay** was achieved. Tenant isolation (separate database per
organization) and the role model held on every route. Dependency audits (`pip-audit`, `npm audit`) are
clean.

Two **Medium** issues were found, both in the **edge/`deploy/vercel-render` deployment configuration**
(not in the application's request handling), plus one Low and two Informational observations.

| Sev | ID | Title |
|:--|:--|:--|
| 🟠 Medium | M1 | Per-IP sign-in throttle and sign-up/organisation rate limit bypass via `X-Forwarded-For` (the `deploy/vercel-render` env sets `TRUSTED_PROXY_HOPS=2` but no `LEDGERLINE_EDGE_SECRET`) |
| 🟠 Medium | M2 | No `Content-Security-Policy` / `Permissions-Policy` on the Vercel/edge path, contradicting the documented posture |
| 🟡 Low | L1 | SPA catch-all serves `200` + `index.html` for every unknown path (no `404`) |
| ⚪ Info | I1 | Payer-agent registration accepts decimal/octal IP host encodings (refused at connect time; no SSRF) |
| ⚪ Info | I2 | Static-analysis triage: every flagged item is a false positive or intentional; 0 dependency CVEs |

**Critical: none. High: none.**

---

## Findings

### 🟠 M1 — Per-IP throttle and sign-up limit bypass via `X-Forwarded-For`

**Severity:** Medium (availability / abuse-control bypass; individual accounts remain protected by the
per-email throttle).

**Where:** `backend/ledgerline/api/security.py:74` (`client_ip`), driven by `deploy/vm/setup.sh:82-84`
(env generation for the multi-tier / Vercel topology).

**What it is.** `client_ip()` decides the caller's address for the per-IP sign-in throttle and the
account/organisation creation limits. Behind proxies it reads `X-Forwarded-For`, trusting the rightmost
`LEDGERLINE_TRUSTED_PROXY_HOPS` entries. An optional shared secret (`LEDGERLINE_EDGE_SECRET`, header
`X-Ledgerline-Edge`) is meant to ensure XFF is trusted **only** on requests that actually came through the
edge — so a client hitting the origin directly "cannot choose its throttling identity"
(config.py:120-121). But the trust gate is:

```python
# security.py:74
edge_ok = settings.edge_secret is None or same_secret(request.headers.get("x-ledgerline-edge"), settings.edge_secret)
```

When `edge_secret` is **unset**, `edge_ok` is unconditionally `True`, so `X-Forwarded-For` is trusted with
no proof it came from the edge. The deployment generator sets `LEDGERLINE_TRUSTED_PROXY_HOPS=2` for the
Vercel topology but **never sets `LEDGERLINE_EDGE_SECRET`** (`deploy/vm/setup.sh:82-99`), and the
multi-tier `deploy/vm/Caddyfile` trusts every upstream (`trusted_proxies static 0.0.0.0/0 ::/0`) and does
not inject an edge header or strip client-supplied XFF. The VM's Caddy is publicly reachable on 443
(`https://$HOST` is in `LEDGERLINE_ALLOWED_ORIGINS`), so an attacker can connect to the origin directly,
bypass Vercel, and supply any XFF they like.

**Reproduction (local, with the deployment's own settings `TRUSTED_PROXY_HOPS=2`, no edge secret):**

```bash
# Second instance mimicking the deploy config
LEDGERLINE_PORT=8001 LEDGERLINE_TRUSTED_PROXY_HOPS=2 LEDGERLINE_PROVIDER=local \
LEDGERLINE_DATA_DIR=./var2 python -m ledgerline &

# The throttling identity is whatever the client puts in X-Forwarded-For:
curl -s -H 'X-Forwarded-For: 203.0.113.9' http://127.0.0.1:8001/api/health      # -> "client":"203.0.113.9"
curl -s -H 'X-Forwarded-For: 6.6.6.6, 7.7.7.7, 8.8.8.8' http://127.0.0.1:8001/api/health  # -> "client":"7.7.7.7"
```

Bypassing the sign-up / organisation limit (10 per IP per hour):

```
rotating X-Forwarded-For per request -> 14/14 sign-ups succeed   (limit defeated)
fixed    X-Forwarded-For (one identity) -> 10x 200 then 4x 429    (limit enforced)
```

**Impact.** The per-IP controls become advisory:
- **Sign-up / organisation creation** (10/hr, 40/day per IP; 500/day server-wide): an attacker rotating XFF
  creates unlimited accounts and organisations. Each organisation provisions its own SQLite database and
  disk directory, so this is a **disk-exhaustion / availability risk** for the whole multi-tenant host.
- **Per-IP sign-in-failure throttle**: an attacker spreads a password-spray across many accounts without
  the per-IP lockout slowing them. (The **per-email** throttle, 5 failures / 15 min, still caps attempts
  against any single account — verified in "What held" — so this is distributed abuse, not single-account
  brute force.)

**Verified locally in the shipped default (loopback, `hops=0`):** XFF is correctly **ignored**
(`/api/health` returns `client: 127.0.0.1` regardless of XFF). The issue is specific to the multi-tier
configuration that sets `hops=2` without an edge secret.

**Suggested fix.** In the Vercel/multi-tier topology, generate and set `LEDGERLINE_EDGE_SECRET` in
`deploy/vm/setup.sh`, have the edge (Vercel) send it as `X-Ledgerline-Edge`, and have Caddy drop any
client-supplied `X-Ledgerline-Edge`/`X-Forwarded-For` on requests that do not come from the edge.
Consider making `client_ip` **fail closed** when `trusted_proxy_hops > 0` but no `edge_secret` is set
(treat XFF as untrusted and fall back to the socket peer), so a missing secret cannot silently disable the
protection.

---

### 🟠 M2 — No Content-Security-Policy / Permissions-Policy on the Vercel/edge path

**Severity:** Medium (defence-in-depth gap; no active XSS vector was found, and `X-Frame-Options: DENY`
already prevents framing).

**Where:** `deploy/vm/Caddyfile` (multi-tier / Vercel topology — the topology this branch targets) vs
`deploy/vm/Caddyfile.single`; application middleware `backend/ledgerline/api/app.py:102-104`.

**What it is.** `Caddyfile.single` ships a strong CSP:

```
Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
  img-src 'self' data:; font-src 'self' data:; connect-src 'self'; form-action 'self'
  https://accounts.google.com https://appleid.apple.com; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
```

…plus `Permissions-Policy`. The multi-tier `deploy/vm/Caddyfile` (used when `MODE != single`, i.e. the
Vercel deployment) sets **only** `Strict-Transport-Security`. There is **no `vercel.json`** in the
repository to supply these headers at the Vercel edge, and the application middleware sets
`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and `Cache-Control` but **not** CSP or
Permissions-Policy. So in the `deploy/vercel-render` topology no CSP is delivered — while `README.md:279,352`
and `docs/DEPLOYMENT.md:6` advertise "strict CSP" as part of the security posture.

**Reproduction / evidence:**
- OWASP ZAP flagged `Content Security Policy (CSP) Header Not Set` (Medium) on `/`, `/robots.txt`,
  `/sitemap.xml`.
- `curl -si http://127.0.0.1:8000/ | grep -i content-security-policy` → no header (SPA document and API).

**Impact.** If a cross-site-scripting bug were ever introduced (none found today — the SPA escapes all
tested fields), there would be no CSP as a second line of containment, and no `Permissions-Policy` to
restrict powerful browser features. For a money-movement SPA this header set is expected.

**Suggested fix.** Add the `Caddyfile.single` CSP + Permissions-Policy to the multi-tier `Caddyfile`
(or a `vercel.json` `headers` block), and/or set a baseline CSP in the app middleware
(`app.py:102`) so coverage does not depend on which edge is in front.

---

### 🟡 L1 — SPA catch-all returns `200` + `index.html` for every unknown path

**Severity:** Low (no information disclosure; this is deliberate SPA routing, but it weakens
"does-not-exist" signalling and produces scanner false positives).

**Where:** `backend/ledgerline/api/app.py:193-200` (`spa` route).

**What it is.** Any non-`api/` path that is not a real file returns `index.html` with `200`, including
`/.hg`, `/.bzr`, `/BitKeeper`, `/._darcs`, `/robots.txt`, `/sitemap.xml`, and arbitrary junk paths.

```
curl -s http://127.0.0.1:8000/.hg       -> <!doctype html> ... (the SPA shell, HTTP 200)
curl -s http://127.0.0.1:8000/nonexistent -> <!doctype html> ... (HTTP 200)
```

This is why ZAP raised four `Hidden File Found` (Medium) alerts — all **false positives**: the paths do not
expose any VCS metadata, they return the app shell (confirmed). Path traversal is **not** possible (see
"What held").

**Suggested fix.** Optional hardening: return `404` for paths that look like asset/file requests
(contain a dot or a known asset prefix) and do not resolve to a real file, reserving the `index.html`
fallback for client-route paths. This removes the scanner noise and gives honest `404`s.

---

### ⚪ I1 — Payer-agent registration accepts decimal/octal IP host encodings

**Severity:** Informational (not exploitable — the connect-time guard refuses them).

**Where:** `backend/ledgerline/payer_agents/remote.py:48-79` (`check_url`).

At registration (`PUT /api/customers/{id}/payer-agent`), `check_url` only rejects hosts that parse as
literal non-public IPs. Non-standard encodings of loopback — `https://2130706433/` (decimal),
`https://0177.0.0.1/` (octal) — are not recognised as IP literals, so they pass the shape check and would
be stored. They are then **refused at connect time**, because `_GuardedBackend` resolves the host
(`getaddrinfo("2130706433") -> 127.0.0.1`) and `address_allowed()` rejects the loopback result:

```
connect 2130706433  -> REFUSED: 2130706433 resolves to a non-public address; not calling it
connect 0177.0.0.1  -> REFUSED: 0177.0.0.1 resolves to a non-public address; not calling it
```

So there is **no SSRF**. As defence-in-depth, consider normalising/rejecting these encodings at
registration too, so an obviously-internal URL cannot be saved on a customer record.

---

### ⚪ I2 — Static-analysis triage

**pip-audit** (`backend/requirements-lock.txt`) and **npm audit** (`frontend/`): **0 known
vulnerabilities**.

**semgrep 1.183.0** — the public registry (`semgrep.dev`) is blocked by this environment's egress policy
(403), so the scan was run offline against the upstream community ruleset (`semgrep/semgrep-rules`, the
same source the `p/python` / `p/javascript` packs are built from): `python`, `javascript`, `typescript`
rule directories, 574 rules over 87 files. 728 findings, of which **679 were `jsx-not-internationalized`
(i18n, not security)** and the remainder code-quality. The security-relevant rules
(`formatted-sql-query`, `sqlalchemy-execute-raw-query`, `python-logger-credential-disclosure`,
`insecure-file-permissions`) were all triaged as false positives (see below).

**bandit 1.9.4** (`backend/ledgerline`) — 13 findings (9 Medium, 4 Low), **all false positives or
intentional**:

| Finding | Locations | Verdict |
|:--|:--|:--|
| B608 "SQL built from strings" | `control.py:240,551`, `workspace.py:283,376`, `api/auth_routes.py:378`, `providers/local.py:88`, `scenario.py:83`, `pg.py` | **FP** — every interpolated token is a whitelisted literal (column keys built from validated `changes` dicts; fixed table-name tuples; schema names validated by `pg.schema_for` / `_SCHEMA_RE`). All **values** are bound parameters (`?`). PostgreSQL identifiers cannot be bound, so validated interpolation is the correct pattern. |
| B105/B106 "hardcoded password" | `control.py:39` (`NO_PASSWORD` sentinel), `oidc.py:90,101` (`token_url=` OAuth endpoint URLs) | **FP** — a non-verifying marker and two provider URLs, not secrets. |
| B110 try/except/pass | `pg.py:134` | **FP** — deliberate best-effort cleanup of a libpq descriptor. |
| B103 chmod `0o660` | `sender.py:278` | **Intentional** — the sender's Unix-domain socket is restricted to owner+group ("nobody else"), with an optional peer-uid check. |

---

## What was tested and held (defences that worked)

All of the following were attempted and **blocked**. 95 hand-crafted checks produced **0 control
failures**; ZAP's 25,310-request authenticated active scan produced **0 High/Critical** alerts.

### Tenant isolation (Company A ⇄ Company B)
- Every single-resource `GET` and every mutating route of Company A's resources (deposits `DEP-1003..1006`,
  customers `CUST-ACME/BRIGHTWAVE/…`, invoices, obligations) was replayed with **Company B's** operator
  session. Result: `404` / `409` / `422` — **never** another tenant's data. Each request is bound to the
  session's own `org_id` → a separate database file (`tenancy.py`, `api/security.py:_principal`).
- `POST /api/auth/switch-organization` to Company A's `org_id` → `403` (membership checked,
  `control.py:switch_org`).
- `GET /api/team` as B returns only B's members.

### Role model (viewer < operator < owner)
- Viewer → operator actions (`POST /customers`, `POST /settings/pause`) → `403`.
- Operator → owner actions (`PUT /settings/policy`, `PUT …/payer-agent`, `POST /team/invitations`,
  `PUT /team/members/{id}`, `POST /organization/delete`, resume money-out) → `403`.
- Operator *can* pause money-out but *cannot* resume it (owner-only) → `403`. Confirmed.

### CSRF (`api/security.py:check_csrf`)
- State-changing request with **no** `X-CSRF-Token` → `403`.
- **Wrong** token → `403`.
- Valid token but **foreign `Origin`** (`https://evil.example.com`) → `403`.
- Valid token but `Sec-Fetch-Site: cross-site` → `403`.
- Unauthenticated `POST /api/auth/signup` from a foreign Origin → `403` (`auth_routes._check_origin`).

### Sessions
- Attacker-chosen cookie value (`ll_session=attacker-chosen-…`) → `401` (tokens are server-minted random,
  stored only as SHA-256; **no session fixation**).
- `POST /api/auth/logout` then reusing the token → `401` (**logout invalidates**). Idle (2 h) and absolute
  (12 h) expiry enforced in `control.authenticate`.

### Sign-in throttle (shipped default, loopback)
- 5 failed sign-ins → `429` on the 6th; persists for a correct attempt in the window; keyed on **email**
  *and* **ip**, so a single account is protected even when the IP identity changes (the per-email key still
  applies). Verified. (XFF-based evasion of the **per-IP** dimension is finding **M1**, above.)

### Path traversal
- `/../../../../etc/passwd`, encoded variants, and `/assets/..%2f..%2f…/etc/passwd` (sent with
  `curl --path-as-is` to defeat client normalisation) → SPA `index.html` (`200`) or `404`; **no file
  disclosure**. The `spa` route resolves and containment-checks under `FRONTEND_DIST`
  (`app.py:197-199`); the `/assets` mount refused traversal with `404`.

### Malformed / oversized input
- 300 KB CSV (`POST /api/payments/import`, 200 KB cap) → `422`; broken JSON → `422`; 500-deep nested JSON
  → `422`; 2 MB field value → `422`. Pydantic `Strict*` typed bodies and field length caps reject before
  the database.

### Webhook signature & replay (`webhooks.py`)
- No signature → `401`; wrong signature → `401`; signature made with the **source-tree default secret**
  → `401` (each organisation has its own random `webhook_secret_local`, confirmed in `tenancy.py:38`);
  stale timestamp → `401 timestamp outside tolerance`; tampered body with a valid-shaped signature →
  `401 signature mismatch`; `>64 KB` body → `413`.
- A **validly signed** event processed (`200 processed`); **replaying the same `event_id`** →
  `200 duplicate` (dedup inside the same transaction that applies the event — **replay cannot act twice**).

### Payer-agent SSRF guard (`payer_agents/remote.py`)
- Registration (owner-only `PUT …/payer-agent`) refused (`422`): `https://169.254.169.254/` (cloud
  metadata), `https://localhost/`, `https://127.0.0.1/`, `https://10.0.0.5/`, `https://192.168.1.1/`,
  `https://[::1]/`, `https://[::ffff:169.254.169.254]/` (IPv4-mapped), `http://…` (plain HTTP),
  `https://user:pass@…` (userinfo), `https://0.0.0.0/`. Only a public `https://` host was accepted.
- Connect-time guard (`_GuardedBackend`) refused a DNS name resolving to a private address, to a
  **mixed** public+private answer set, and to the metadata address — defeating DNS-rebinding. IPv6
  embeddings (`::ffff:`, 6to4 `2002::`, NAT64 `64:ff9b::`/`64:ff9b:1::`, `fd00::`, `fe80::`) are rejected by
  `address_allowed`. Redirects are not followed (`follow_redirects=False`); cookies/authorization headers
  are stripped; responses are byte-capped (256 KB); `data:`/`file:`/`gopher:` schemes refused.

### Practice-only endpoints from a real company (Company B = workspace)
- `POST /api/practice/tamper`, `/practice/tamper/restore` → `403`;
  `/demo/practice-unclear-payment`, `/demo/practice-wrong-currency`, `/treasury/practice-squeeze`,
  `/demo/step` → `409` (sample-org only);
  `/approvals/{id}/send-as-practice-teammate` → `403` on a real company.

### XSS through UI text fields (verified in a real browser with Playwright)
- Stored payloads (`<img src=x onerror=…>`, `<script>…</script>`, `"><svg onload=…>`) in customer **name**,
  **payer names**, **refund beneficiary**, and a deposit's **payer name** and **reference**, then rendered
  `#/customers`, `#/payments`, `#/overview` in headless Chromium with the operator cookie. **No** dialog
  fired, **no** `onerror`/`onload` executed, **no** injected `<img>`/`<svg>` node was created; the payload
  renders as escaped text, e.g.:

  ```html
  <div class="primary-text">&lt;img src=x onerror=window.__xss_img=1&gt; Evil Co</div>
  ```

  The frontend has **no** `dangerouslySetInnerHTML`, `innerHTML`, `eval`, or user-data-driven `href`
  (grep of `frontend/src`). React's default escaping holds. The payment `external_ref` field is additionally
  charset-restricted to `[A-Za-z0-9._:-]`.

### Security headers & cookie flags (observed locally)
- **Present:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`
  (all responses); `Cache-Control: no-store` (API).
- **Session cookie:** `HttpOnly; SameSite=Strict; Path=/api; Max-Age=43200`. The `Secure` flag is off only
  because the local test runs over plain HTTP; production sets `LEDGERLINE_COOKIE_SECURE=1`
  (`deploy/vm/setup.sh:82`), so `Secure` is applied there — **not a finding**.
- `Strict-Transport-Security` is set at the edge in both Caddy configs. Missing CSP/Permissions-Policy on
  the Vercel path is finding **M2**.

---

## Methodology notes & limitations

- **ZAP** ran as a daemon (2.16.1); the OpenAPI definition (`/api/openapi.json`, 122 route+method combos)
  was imported, the Operator session of the Practice company was supplied as a `Cookie` + `X-CSRF-Token` +
  `Origin` via replacer rules, and session-destroying / destructive endpoints (`logout`,
  `delete-account`, `organization/delete`, `switch-organization`, `change-password`, `reset`, `airwallex/*`)
  were excluded so the authenticated scan would not end its own session. Baseline = spider + passive scan;
  then a full authenticated active scan (25,310 requests).
- **semgrep registry blocked:** the environment's egress policy returns 403 for `semgrep.dev`, so the
  managed `p/python` / `p/javascript` / `p/owasp-top-ten` packs could not be downloaded. The scan instead
  used the upstream `semgrep/semgrep-rules` repository offline (the same rule source). This is equivalent in
  substance for the Python/JS/TS rules; a handful of registry-only curated rules in `p/owasp-top-ten` may
  not be represented.
- **Docker/ZAP image:** the ghcr.io blob CDN is also blocked by egress policy (403), so the official ZAP
  Docker image could not be pulled; ZAP was downloaded as the signed Linux release and run directly.
- Testing was against the **local simulated bank** and the **offline Claude fixture**; no Airwallex or
  Anthropic calls were made, and no real credentials exist in this environment.

---

_Authorised local security test. No code was changed by this review; this document is the only artefact._
