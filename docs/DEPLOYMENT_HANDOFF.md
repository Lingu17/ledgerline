# Deployment handoff (Claude → Codex)

Last updated 27 Oct 2026. Branch `deploy/vercel-render` (not merged to `main`). This file states only what was observed; anything not yet executed is marked **not yet run**.

## Selected architecture (user decision)

```
Browser ── https ──> Vercel (static React app, frontend/, free Hobby)
                       │ /api/* same-origin rewrite (frontend/vercel.json)
                       ▼
                     Render web service `ledgerline-api` (FREE plan, Singapore, Python 3.14.8)
                       │ psycopg pool, TLS (sslmode=require)
                       ▼
                     Supabase PostgreSQL (free), shared pooler in SESSION mode (port 5432, IPv4)
                       schemas: <prefix>_control · <prefix>_t_<org_id> (ledger) · <prefix>_b_<org_id> (simulated bank)
```

Why: the user has no card that Render's paid plan or Oracle/alwaysdata accept (Render declined the user's Indian debit card twice; alwaysdata email sign-up requires card validation from the user's network). PythonAnywhere free blocks outbound HTTPS to `api.sandbox.airwallex.com` (observed from its console). Render's free plan is available without a card in the user's "My Workspace" (observed: service created). Render free has no persistent disk, so all durable state moves to PostgreSQL.

Free-tier behaviour to disclose: Render free instances spin down after inactivity and the first request can take 50 s or more; Supabase free projects pause after 1 week of inactivity, include 500 MB, and have no automatic backups (supabase.com/pricing, 27 Oct 2026). Neither is promised to stay free or always on.

## Current state

| Item | Status |
|---|---|
| Render free service `ledgerline-api` | **Created, live** at `https://ledgerline-api-4dt3.onrender.com` (deploy of `cf3f61c`). Running as a **probe on ephemeral storage** (`LEDGERLINE_DATA_DIR=/tmp/...`): data is lost on restart. Not for judges until PostgreSQL is configured. |
| Probe results (observed over HTTPS) | `/api/health` 200 in 0.5 s; signup 200 with cookie `HttpOnly; Secure; SameSite=strict; Path=/api`; sample org lists 6 deposits; **real stdio MCP** ask-agent → `verified` in 8.6 s on the 0.1 CPU instance; integrations report Airwallex/Claude `not_configured`. Health `client` showed a Cloudflare address: Render's edge adds hops; `LEDGERLINE_TRUSTED_PROXY_HOPS` must be calibrated once Vercel is in front. |
| Supabase project | **Not created** (user step) |
| `LEDGERLINE_DATABASE_URL` on Render | **Not set** (user step: Supabase Connect → Session pooler URI with `?sslmode=require`) |
| `LEDGERLINE_SECRET_KEY` on Render | **Not set** (to be generated with Render's Generate button; never seen or typed by Claude) |
| Vercel project | **Not created** (needs the user's Vercel sign-in) |
| Paid resources | None. Render paid plan and disk were not purchased. |

## PostgreSQL storage (commits `8f8293b`, `022b520`)

- `backend/ledgerline/pg.py`: same connection surface as SQLite so the money code is unchanged. One schema per logical database; a connection's `search_path` is that schema only. `BEGIN IMMEDIATE` → `BEGIN` + `pg_advisory_xact_lock(schema)` (one writer per logical database, as in SQLite); READ COMMITTED reads. DDL: `INTEGER` → `BIGINT`, identity columns; dialect translation (`?`, `INSERT OR IGNORE`, `LIKE`→`ILIKE`, JSON, `PRAGMA table_info`); integral `NUMERIC` sums returned as `int`. Pool returns connections rolled back and reset.
- Hardening: `REVOKE ALL` on Ledgerline schemas from `PUBLIC`, `anon`, `authenticated`; RLS enabled with no policies on every table. The server role owns the tables (bypasses RLS); tenant isolation is enforced in the application (session → membership → registry → that organization's schema).
- Payer-agent signing keys: table `agent_keys` per organization, AES-256-GCM, key from HKDF(`LEDGERLINE_SECRET_KEY`), associated data `schema:customer_id`. Keys are created only when a sample organization is seeded; the agent only loads them (missing or undecryptable → error, never a new identity). The stdio MCP child receives the organization's keys via its environment (not argv) and has no database access.
- Config refuses a remote database URL without `sslmode`, and PostgreSQL mode without a 32+ character `LEDGERLINE_SECRET_KEY`.

## Tests

| Run | Result |
|---|---|
| Local SQLite suite (`backend\.venv\Scripts\python -m pytest -q`) at `022b520` | **192 passed, 8 skipped** (skips = live PostgreSQL tests) |
| PostgreSQL translation/encryption unit tests | pass locally |
| Live PostgreSQL tests (`tests/test_postgres.py`: walkthrough + restart continuity, tenant switching/isolation/privileges/RLS, concurrent refund execution, concurrent duplicate webhooks, concurrent FX execution, failed-transaction rollback + pool recovery, stdio MCP signing identity across restart and refusal with a different secret, random-company accuracy) | **not yet run** locally: running downloaded PostgreSQL binaries was refused by this machine's permission policy and the EDB installer download returned HTTP 403. They run in GitHub Actions job `postgres` (postgres:17 service container), together with the whole suite on PostgreSQL. Result: see the latest Actions run for the branch; recorded below when observed. |
| Supabase session pooler | **not yet run** (needs the user's `backend\.env.test`) |
| Deployed end-to-end, restart persistence | **not yet run** |

## Blockers needing the user

1. Supabase: sign in, create project `ledgerline` (Singapore), copy the Session pooler URI (password substituted, `?sslmode=require`), and paste it (a) into Render → `ledgerline-api` → Environment as `LEDGERLINE_DATABASE_URL`, (b) into `backend\.env.test` as `LEDGERLINE_TEST_DATABASE_URL=...` (gitignored). Never in chat.
2. Vercel: sign in (GitHub) so the frontend project can be created.
3. Optional integrations, server-side only: `AIRWALLEX_CLIENT_ID`, `AIRWALLEX_API_KEY`, `LEDGERLINE_SANDBOX_ORGS`, `ANTHROPIC_API_KEY`.

## Superseded

The Render Starter + disk configuration in `render.yaml` and the Oracle VM kit in `deploy/vm/` are kept as documented alternatives; neither is deployed.
