# Claude handoff — Ledgerline SaaS build

Date: 2026-10-27. Scope: `docs/SAAS_REQUIREMENTS.md` on top of the earlier single-tenant build (whose findings 1–10 in `docs/CODEX_REVIEW_FINDINGS.md` stay fixed, with regressions still passing). **Nothing committed or pushed; no git repository initialised; HackerEarth untouched. No billing, no real money.**

## Start commands (Windows, PowerShell)

```
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1     # venv + pip install -r backend\requirements-lock.txt, npm ci, npm run build
powershell -ExecutionPolicy Bypass -File scripts\start.ps1     # API + built UI on http://127.0.0.1:8000
powershell -ExecutionPolicy Bypass -File scripts\test.ps1      # pytest + tsc/vite build
backend\.venv\Scripts\python scripts\smoke_live.py              # live HTTP probe against the running server (throwaway accounts)
cd frontend; npm run e2e                                         # Playwright browser suite (own server on :8765, throwaway data dir, system Edge)
```

First use: open http://127.0.0.1:8000 → *Create an organization* (sample data or empty). No default credentials exist. CLI alternative: `cd backend; .venv\Scripts\python -m ledgerline.manage create-owner --email you@company.test --org "Company" [--sample]` (password prompted, or `LEDGERLINE_BOOTSTRAP_PASSWORD`). Fresh start: stop the server, delete `backend\var\`.

Local note: `backend\var\LOCAL_TEST_ACCOUNTS.txt` (gitignored, local only) records the throwaway browser-test owner I created on localhost; delete `backend\var\` to discard it. `backend\.venv` and `frontend\node_modules` exist from the build session. The preview server has been stopped; port 8000 is free.

## Test results (actually run, this session)

| Check | Result |
|---|---|
| `scripts\test.ps1` (PowerShell) | **174 passed** (~64 s); `tsc -b` strict + `vite build` OK |
| `scripts\smoke_live.py` against the running server | **18/18**: signup cookie; sample data; viewer read-only (payment, ask-agent refused); operator cannot change policy; **real stdio MCP** ask-agent → verified; malicious claim rejected by check 3; operator approves system proposal; operator **cannot approve own** return proposal; owner executes refund; no-CSRF and foreign-origin mutations refused; other org sees nothing, cannot read DEP-1006 or switch in; ledger balanced; logged-out cookie replay refused |
| Browser pane (built UI on :8000) | Sign-up form → sample org Inbox; Team page; invoice drawer with details/adjustment forms; Settings integrations; sign-in after logout; Payments at 375 px with no page-level horizontal overflow. Only console error: the expected 401 from `/api/auth/me` before sign-in. The pane closed itself once mid-session; role/tenant checks were therefore done over HTTP by `smoke_live.py` rather than click-through for every role. |
| `npm run e2e` (Playwright 1.48.2, system Microsoft Edge) | **9/9**: Google/Apple buttons shown and disabled with an explanation when the server has no OAuth credentials, provider error explained on sign-in, Settings lists sign-in methods; product home page sections, section links scroll without changing route, Get started → sign-up, logo → home; sign up with sample data, sign out (server-side 401 afterwards), sign back in; wrong password non-enumerating; empty workspace manual payment via the form; invited viewer sees Read-only, no record/import buttons, and the API returns 403 for a viewer POST; second org sees none of the first org's payments and gets 404 on DEP-1006; no page-level horizontal overflow at 375 px on home, inbox, payments, treasury, customers, team, settings. |
| CI steps run locally | Fresh venv from `requirements-lock.txt` → **141 passed**; `npm ci` + build OK; e2e 7/7. Locally on Windows with Python 3.14 only (no 3.13 installed); GitHub Actions itself has **not** run (no repository, no push). |
| Not run | Airwallex sandbox and Claude API: no `AIRWALLEX_CLIENT_ID`/`AIRWALLEX_API_KEY` or `ANTHROPIC_API_KEY` exists in the environment or `backend/.env`. With keys in `backend/.env`, Settings → Integrations → *Check connections* performs a real Airwallex login and Claude model lookup and reports the result verbatim. |

Bugs found by the browser suite and fixed (with regressions): manual payments dated today were refused as "in the future" before 12:00 UTC because date-only input was pinned to noon UTC (`workspace.py`; test `test_statement_dated_today_is_accepted_at_any_hour`); Treasury tables overflowed the page at phone width (now wrapped in scroll containers).

New test module `backend/tests/test_saas.py` (23 tests): signup/login/logout with server-side replay refusal; cookie flags incl. Secure; password policy; duplicate email and non-enumerating login errors; throttling with Retry-After; idle (2 h) and absolute (12 h) expiry; password change revokes other sessions; unauthenticated refusal; **cross-organization reads/approvals/switch/export refused**; multi-org switching; viewer read-only; operator vs owner governance (pause yes, resume no); four-eyes; role change and removal immediate, last owner protected; invitation expiry and single use; empty-workspace full workflow without the walkthrough (opening balance once, customer, invoice, partial payment, credit note, obligation, pagination header); voided invoice never paid; CSV import idempotency; customer refund-account edit invalidates bound approval; migrations recorded and a legacy v1 tenant DB upgraded idempotently. `test_api_webhooks.py` gained CSRF/origin/Sec-Fetch-Site and per-organization webhook secret tests.

## What was built

- **Control plane** (`backend/ledgerline/control.py`): users (scrypt), organizations, memberships (owner/operator/viewer), sessions (SHA-256 of token stored; idle + absolute expiry; revocation), invitations (one-time, 3-day), login throttling, control-plane audit.
- **Tenancy** (`tenancy.py`): database-per-organization under `backend/var/orgs/<org_id>/` with its own simulated bank and payer-agent keys; per-org webhook secret and bank mode; registry cache invalidated on settings change. Org ids are validated before becoming paths.
- **Auth layer** (`api/security.py`, `api/auth_routes.py`): HttpOnly SameSite=Strict cookie, CSRF header, Origin and Sec-Fetch-Site checks, role dependencies; signup/login/logout/me/switch/change-password, organizations, invitations, team, organization settings, integration readiness check (performs a real Airwallex login / Claude model lookup only when keys exist, reports results verbatim).
- **Migrations** (`migrations.py`, `python -m ledgerline.manage migrate`): versioned, transactional, append-only; tenant v2 adds invoice adjustments, approval author, edit timestamps, void marker.
- **Workspace features** (`workspace.py`): customer edits, invoice detail edits (non-monetary only), journaled adjustments and void, CSV statement import, obligations, one-time opening balances; plus earlier manual payment, operator resolution, remittance reading.
- **Four-eyes** (`payouts.py`): `approvals.created_by`; proposer cannot approve (`SelfApproval` → 403).
- **API**: pagination via `limit/offset` + `X-Total-Count` on deposits, invoices, audit; search on customers/invoices/audit; invoice detail endpoint; per-org webhook URL `/api/webhooks/airwallex/{org_id}`; security headers and request logging.
- **Sign in with Google / Apple** (`oidc.py`, `api/oauth_routes.py`, control migration v2 `oauth_identities` + `oauth_states`, `components/OAuthButtons.tsx`, Settings → Sign-in methods): OIDC code flow; server-side code exchange (Google with PKCE; Apple with a per-request ES256 client-secret JWT and form_post callback); single-use 10-minute state bound to the browser by an HttpOnly cookie; nonce; RS256 signature via provider JWKS (cached, refetched on unknown kid); iss/aud/azp/exp/iat checks; verified email required for new accounts. **Never auto-links to an existing password account by email** (password sign-ups don't verify email, so that would allow pre-registration takeover): the user connects the provider from Settings while signed in. Provider-only accounts have no password; the last sign-in method cannot be removed. Invitees can sign in with a provider and join when the address matches (`POST /invitations/{token}/accept-signed-in`). Return targets are allow-listed (no open redirect). `tests/test_oauth.py` (19 tests) uses fake IdPs signing real RS256 tokens via httpx MockTransport: state reuse, other-browser replay, expiry, wrong nonce/aud/iss, expired token, foreign signing key, unverified email, failed exchange, cancel, no email auto-link, link/unlink rules, signup disabled, Apple form_post with the client-secret JWT verified against the .p8 public key, invitation join. **Not run against real Google or Apple** (no OAuth clients exist); Apple requires HTTPS.
- **Randomized accuracy harness** (`tests/accuracy_harness.py`, `scripts/accuracy_run.py`, report `docs/ACCURACY_REPORT.md`): 250 synthetic companies + 25 sample walkthroughs through the real API, every figure compared with an independent reference model: **PASS, 64,215 checks, 11,046 payments, 5,059 invoices, 0 mismatches**. Planted bugs (fee tolerance x2, amount-only matching, unapplied off by 1 cent) were caught. Found and fixed: a second operator allocation of the same payment to the same invoice was refused (`reconcile._allocate` now tops up; regression in `test_workspace.py`).
- **Product home page** (`views/Landing.tsx`, `components/Globe.tsx`, `landing.css`): `#/home`, shown to signed-out visitors and reached from the Ledgerline logo everywhere. Hero with a canvas-2D 3D globe of currency hubs and payment arcs (static under reduced motion), six-case strip, how it works, features, safety, roles, integrations (truthful default/sandbox/optional labels), FAQ, CTA, footer stating it is a hackathon project, not a bank, synthetic data. No testimonials or customer logos.
- **Frontend**: sign-in / create organization / accept invitation / no-organization screens; organization switcher and "new organization"; Team page; role-aware controls (viewers see a Read-only badge); Settings with organization, integrations (write-only webhook secret, readiness check), policy (owner-only), password change; Customers with search, edit, invoice drawer, adjustments, pagination; Payments CSV import and pagination; Activity server-side search and paging; Treasury obligations and opening balances; walkthrough limited to sample organizations.

## Files changed or added in this scope

Backend: `control.py`, `tenancy.py`, `migrations.py`, `manage.py`, `api/auth_routes.py`, `api/security.py` (rewritten), `api/app.py` (rewritten), `api/routes.py`, `context.py`, `config.py`, `__main__.py`, `payouts.py`, `reconcile.py`, `workspace.py`, `scenario.py`, `.env.example`; tests `conftest.py`, `test_saas.py` (new), `test_api_webhooks.py`, `test_review_regressions.py`, `test_payouts.py`.
Frontend: `auth.tsx` (new), `views/Auth.tsx` (new), `views/Team.tsx` (new), `components/Pager.tsx` (new), `App.tsx`, `api.ts`, `styles.css`, `views/{Settings,Customers,Payments,Activity,Approvals,Treasury,Walkthrough}.tsx`.
Repo: `README.md` (rewritten for SaaS), `scripts/smoke_live.py` (new), this file.

Must never be committed (all gitignored): `backend/var/` (databases, payer-agent **private keys**, local test account note), `.env`, `backend/.venv`, `frontend/node_modules`, `frontend/dist`, `.claude/`.

## Credentials needed for optional paths

- Airwallex sandbox: server env `AIRWALLEX_CLIENT_ID`, `AIRWALLEX_API_KEY`; per organization (Settings, owner): global account ids, Airwallex webhook secret, sandbox beneficiary IDs as refund destinations, a public tunnel for the webhook URL.
- Claude: `ANTHROPIC_API_KEY` (default model `claude-opus-5-5`); request uses strict tools with `tool_choice: auto`; never executed in this build.

## Known gaps and judgement calls for review

- Database-per-organization instead of row-level `org_id` filters: isolation is structural; the boundary is session → membership → registry. Cross-org tests cover reads, mutations, export, switching and webhooks.
- Airwallex credentials are server-wide (per-org vault not built). Per-org Airwallex webhook secrets are stored in plaintext in `control.sqlite3`, never returned by the API.
- No email delivery, password reset, SSO or MFA. Invitation links are shown once to the owner.
- Operators may pause money-out; only owners resume. Operators can approve proposals made by someone else (including system proposals for verified duplicates).
- `LEDGERLINE_WEBHOOK_SECRET`, `AIRWALLEX_WEBHOOK_SECRET` and `AIRWALLEX_GLOBAL_ACCOUNT_IDS` env vars are still parsed for the single-org `build_context` used by domain tests; the SaaS app uses per-organization values.
- Payments table on phones scrolls horizontally inside its card (status column off-screen until scrolled).
- Some evidence check detail lines show raw minor units (technical detail, not headline figures).
