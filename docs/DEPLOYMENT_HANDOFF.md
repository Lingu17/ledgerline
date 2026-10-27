# Deployment handoff (Claude → Codex)

Last updated 27 Oct 2026. Branch `deploy/vercel-render` (not merged to `main`). This file states only what was observed; anything not yet executed is marked **not yet run**.

## Review fixes after `eeaf1e6` (27 Oct 2026)

Codex's review of `eeaf1e6` reproduced five issues; all are fixed with regressions:

| # | Issue | Fix | Regressions |
|---|---|---|---|
| 1 | Live `/api/health` 502 (Vercel) / timeout (Render) | **Not reproduced** on 27 Oct: both returned 200 in ~0.3 s. The service is on Render Free, which spins down when idle; a cold start can exceed Vercel's rewrite timeout (502) and a client timeout. Render logs were not inspected (dashboard not signed in from this session), so this cause is likely, not established. The same probe showed `"storage":"local directory"`, i.e. the live service is **still on ephemeral SQLite**; that is the real deployment blocker (see below). | probe only |
| 2 | Claude limit race; failed calls free | Control-plane migration v3 `claude_calls`. `ControlPlane.reserve_claude_call` checks the organization limit and the new server-wide `LEDGERLINE_CLAUDE_SERVER_DAILY_LIMIT` (default 200) and inserts a `reserved` row in one serialized transaction, committed **before** the API call; the call runs with no transaction open; the row is then settled `succeeded`/`failed`. Every reservation counts, including failed and never-settled (interrupted) ones. Without the control plane a configured key is never used. | `test_judge_safety.py`: 6 simultaneous requests at limit 1 → exactly 1 model call; failed calls consume budget; server-wide cap across organizations |
| 3 | `sslmode=disable/allow/prefer` accepted; `application_name=@localhost` looked local | `config.check_database_tls` parses the URL: scheme must be postgres(ql); hosts from the authority **and** `host=`/`hostaddr=` query parameters; local only if every host is loopback or a socket path; otherwise every `sslmode` must be `require`, `verify-ca` or `verify-full`. | `test_deployment.py` negative cases |
| 4 | Wrong JSON types → 500 | Typed pydantic bodies (`StrictStr`, strict numbers) for create/update customer and invoice; wrong types are 422 before database binding or key decoding. Domain functions also type-check `agent_public_key` and `customer_id`. | `test_input_validation.py`: 422 and state unchanged |
| 5 | Non-ASCII `x-ledgerline-edge` crashed `compare_digest` | `security.same_secret` compares bytes with a length bound; malformed proof is simply untrusted. Same helper for `X-CSRF-Token`. | `test_deployment.py` |

## Selected architecture (user decision)

```
Browser ── https ──> Vercel (static React app, frontend/, free Hobby)
                       │ /api/* same-origin rewrite (frontend/vercel.json)
                       ▼
                     Render web service `ledgerline-api` (FREE plan, Singapore, Python 3.14.8)
                       │ psycopg pool, TLS (sslmode=require)
                       ▼
                     Neon PostgreSQL (free), DIRECT endpoint (hostname without -pooler), sslmode=require
                       schemas: <prefix>_control · <prefix>_t_<org_id> (ledger) · <prefix>_b_<org_id> (simulated bank)
```

Why: the user has no card that Render's paid plan or Oracle/alwaysdata accept (Render declined the user's Indian debit card twice; alwaysdata email sign-up requires card validation from the user's network). PythonAnywhere free blocks outbound HTTPS to `api.sandbox.airwallex.com` (observed from its console). Render's free plan is available without a card in the user's "My Workspace" (observed: service created). Render free has no persistent disk, so all durable state moves to PostgreSQL.

Free-tier behaviour to disclose: Render free instances spin down after inactivity and the first request can take 50 s or more. Neon free (neon.com/pricing, 27 Oct 2026): no card, permanent (not a trial), 1 GB storage per project, 100 CU-hours per project per month (compute suspends until the next period if exceeded), scale-to-zero after 5 idle minutes (cannot be disabled on Free), 6-hour history window, 1 manual snapshot, no scheduled snapshots. Supabase was not used: both free project slots in the user's account are occupied by other projects, which were not modified. Nothing is promised to stay free or always on.

## Current state (observed)

| Item | Status |
|---|---|
| Public URL | **https://ledgerline-black-iota.vercel.app** (Vercel Hobby project `ledgerline`, root `frontend`, production branch `deploy/vercel-render`). `/api/*` is routed to Render by `frontend/vercel.json` `routes` (with an `x-ledgerline-edge` request-header transform from the Vercel env `LEDGERLINE_EDGE_SECRET`). |
| Render free service `ledgerline-api` | Live at `https://ledgerline-api-4dt3.onrender.com`, branch `deploy/vercel-render`, auto-deploy on commit. **Still on ephemeral SQLite (`/tmp`)**: data is lost on restart until `LEDGERLINE_DATABASE_URL` is set. Env set by Claude (non-secret): `LEDGERLINE_ALLOWED_ORIGINS` and `LEDGERLINE_PUBLIC_URL` = the Vercel origin, `LEDGERLINE_TRUSTED_PROXY_HOPS=4`; `LEDGERLINE_SECRET_KEY` generated with Render's Generate button (regenerated once after it was displayed on screen; current value never displayed). |
| Proxy calibration | Measured with `/api/health` (`forwarded_entries`, `client`): through Vercel the chain has 4 entries and Vercel overwrites a client-sent X-Forwarded-For; Render adds 3 entries after the connecting address. With hops=4 the server resolved this PC's real public address through Vercel, ignored a forged header through Vercel, and resolved a direct Render call to Render's internal peer (fail closed). Remaining gap until the edge secret is set on both sides: a direct caller to the Render URL who forges exactly one entry can choose its per-IP throttling identity; commit `1d7a90b` closes it once `LEDGERLINE_EDGE_SECRET` is set identically on Render and Vercel. |
| Neon | Being provisioned by Codex (user request). Claude does not create projects or handle database credentials. |
| Fail-closed storage | `LEDGERLINE_REQUIRE_DATABASE=1` (commit `1d7a90b`) to be set on Render together with the database URL. |
| Paid resources | None. |

## PostgreSQL storage (commits `8f8293b`, `022b520`)

- Connection policy: transaction-mode poolers (Neon `-pooler` hostnames, Supabase port 6543, `pgbouncer=true`) are refused at startup, because the per-connection `search_path` that pins a tenant schema is session state those poolers drop; every checkout also verifies `current_schema()`. Pooled connections are validated on checkout (Neon suspends idle compute after 5 minutes). Transaction-scoped advisory locks (`pg_advisory_xact_lock`) are used, never session-level locks.
- `backend/ledgerline/pg.py`: same connection surface as SQLite so the money code is unchanged. One schema per logical database; a connection's `search_path` is that schema only. `BEGIN IMMEDIATE` → `BEGIN` + `pg_advisory_xact_lock(schema)` (one writer per logical database, as in SQLite); READ COMMITTED reads. DDL: `INTEGER` → `BIGINT`, identity columns; dialect translation (`?`, `INSERT OR IGNORE`, `LIKE`→`ILIKE`, JSON, `PRAGMA table_info`); integral `NUMERIC` sums returned as `int`. Pool returns connections rolled back and reset.
- Hardening: `REVOKE ALL` on Ledgerline schemas from `PUBLIC`, `anon`, `authenticated`; RLS enabled with no policies on every table. The server role owns the tables (bypasses RLS); tenant isolation is enforced in the application (session → membership → registry → that organization's schema).
- Payer-agent signing keys: table `agent_keys` per organization, AES-256-GCM, key from HKDF(`LEDGERLINE_SECRET_KEY`), associated data `schema:customer_id`. Keys are created only when a sample organization is seeded; the agent only loads them (missing or undecryptable → error, never a new identity). The stdio MCP child receives the organization's keys via its environment (not argv) and has no database access.
- Config refuses a remote database URL without `sslmode`, and PostgreSQL mode without a 32+ character `LEDGERLINE_SECRET_KEY`.

## Tests

| Run | Result |
|---|---|
| Local SQLite suite at `50a229a` | **195 passed, 8 skipped** (skips = live PostgreSQL tests needing a database URL) |
| PostgreSQL translation/encryption unit tests | pass locally |
| Real PostgreSQL 17 (GitHub Actions job `postgres`, service container), commit `8a079a7`, run 40520577449 | **PASS**: `tests/test_postgres.py` (walkthrough and restart continuity, tenant switching/isolation, privileges and RLS, concurrent refund execution, concurrent duplicate webhooks, concurrent FX execution, failed-transaction rollback and pool recovery, stdio MCP signing identity across restart and refusal with a wrong secret, random-company accuracy) **and the whole backend suite with every app on PostgreSQL** (`LEDGERLINE_TEST_ALL_ON_POSTGRES=1`). Earlier runs found and fixed: test-only bugs, a lazily created `agent_keys` table (now tenant migration v3), and one SQLite-only catalog query in a test. Same run: backend on Linux and Windows (SQLite), frontend build and Playwright e2e passed. |
| Neon direct endpoint | **not yet run** (needs `backend\.env.test`) |
| Deployed end-to-end, restart persistence | **not yet run** |

## Blockers needing the user

1. Neon (Codex is handling): project in an Asia-Pacific region, the DIRECT connection string (no `-pooler`) with `?sslmode=require` into Render `LEDGERLINE_DATABASE_URL` and `backend\.env.test` `LEDGERLINE_TEST_DATABASE_URL`; then set `LEDGERLINE_REQUIRE_DATABASE=1`.
2. Edge secret: generate `LEDGERLINE_EDGE_SECRET` in Render and paste the same value into Vercel (Production, Sensitive).
3. Optional integrations, server-side only: `AIRWALLEX_CLIENT_ID`, `AIRWALLEX_API_KEY`, `LEDGERLINE_SANDBOX_ORGS`, `ANTHROPIC_API_KEY`.

## Superseded

The Render Starter + disk configuration in `render.yaml` and the Oracle VM kit in `deploy/vm/` are kept as documented alternatives; neither is deployed.
