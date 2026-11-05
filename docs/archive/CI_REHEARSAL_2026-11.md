# CI rehearsal: November 2026

Every job in `.github/workflows/ci.yml` reproduced on Ubuntu, because GitHub Actions has been blocked by a billing hold since run #163. The target is `main` at **`b3ba221`**. `main` had not moved when checked on 5 Nov 2026.

## Verdict

| Job | At `b3ba221` | On `ci-rehearsal-fixes` |
|---|---|---|
| backend (ubuntu-latest, Python 3.13) | **PASS**: 589 passed, 10 skipped | **PASS**: 589 passed, 10 skipped |
| backend (windows-latest, Python 3.13) | not reproducible here (Linux container); see notes | not run |
| frontend (Node 22) | **PASS**: `npm ci` + `npm run build` (tsc + vite), no warnings | unchanged (no frontend changes) |
| e2e (Python 3.13, Node 22, Chromium) | **PASS**: 30 passed, 2 skipped | **PASS**: 30 passed, 2 skipped |
| postgres › PostgreSQL-specific tests (Python 3.14) | **FAIL**: 1 failed, 12 passed | **PASS**: 13 passed |
| postgres › Whole suite on PostgreSQL (Python 3.14) | **FAIL**: 3 failed, 586 passed, 10 skipped | **PASS**: 589 passed, 10 skipped |

**At `b3ba221` the postgres job would go red on GitHub.** The three failures come from two app bugs and one test bug. All three are fixed in two commits on `ci-rehearsal-fixes`. Every job was then rerun from a clean checkout of that branch, and all pass.

## How it was run

- **Checkouts:** a separate clean `git worktree` at the commit for each job, standing in for `actions/checkout`.
- **Python:** 3.13.18 (preinstalled) for backend and e2e. 3.14.6 via `uv python install 3.14` for postgres. Each job got a fresh venv, then the job's own command: `python -m pip install --require-hashes -r backend/requirements-lock.txt`.
- **Node:** 22.23.4, npm 10.9.9.
- **Postgres service:** `docker run postgres:17` with `POSTGRES_PASSWORD=postgres`, `-p 5432:5432` and the workflow's `pg_isready` health check (healthy before the steps ran). Job env: `LEDGERLINE_TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres`. The second step also sets `LEDGERLINE_TEST_ALL_ON_POSTGRES=1`.
- **Exact step commands:** each step ran exactly as written, in `backend/`, including the `|| python ../scripts/ci_annotate.py <xml>` fallback, whose exit code decides the step. The `::error` lines below are what CI would print as annotations.
- **e2e:** `E2E_CHANNEL=chromium` was set, and the step ran exactly as written: `npm ci && npm run build && npx playwright install --with-deps chromium && npm run e2e`. Two deviations, both forced by this environment:
  - **Browser download blocked.** `npx playwright install` for the pinned `@playwright/test` **1.64.1** failed with a proxy 403: *no rule allows host `cdn.playwright.dev`*. On GitHub's runners this host is reachable. Instead, the **preinstalled Chromium build 1243 (Chrome for Testing 153.0.8010.12)** was used, exposed through a scratch `PLAYWRIGHT_BROWSERS_PATH` under build 1248's directory names. Playwright 1.64.1 normally drives build 1248 (CfT 156.0.8078.4). The repository's config was not changed.
  - **`npm run e2e` ran separately.** The `--with-deps` OS-package part is not exercised when the download fails. `npm run e2e` therefore ran as its own command, with the same env and working directory.
- **Env check:** no `ANTHROPIC_*` / `AIRWALLEX_*` / `LEDGERLINE_*` keys were in the environment, and no real keys were used. `ANTHROPIC_BASE_URL` was set by the container. The app never reads it, and the test fixtures blank `ANTHROPIC_API_KEY`.

### Skips (all expected)
- **backend (SQLite):** 10 skips. Nine are `test_postgres.py` (no `LEDGERLINE_TEST_DATABASE_URL`, as in CI's backend job). One is `test_public_pages.py:90`, because the frontend is not built in that job.
- **Whole suite on PostgreSQL:** 10 skips. Nine are `test_backup` (SQLite backup; data is in PostgreSQL). One is the same frontend-not-built skip.
- **e2e:** 2 skips, both opt-in only: `demo-video.spec.ts` needs `DEMO_DIR`, and `screenshots.spec.ts` needs `SCREENSHOTS=1`.

## Failures, root causes and fixes

### 1. `test_postgres_stdio_mcp_signing_identity_survives_restart`: app bug (regression from `aab8d3e`)

Fails in **both** postgres steps: `KeyError: 'verification'` at `backend/tests/test_postgres.py:328`.

**What happens:**
1. Commit `aab8d3e` (5 Nov) made practice companies always use the in-process MCP transport, at `backend/ledgerline/payer_agents/client.py:96`.
2. With that transport on PostgreSQL, the signing keys were decrypted *inside the MCP tool call* (`payer_agents/server.py:42` → `keys.py:110`).
3. The test's app3 starts with a wrong `LEDGERLINE_SECRET_KEY`. Decryption raised `KeyStoreError`.
4. The MCP SDK turned that error into a tool error, which came back as an *answer*.
5. `routes.py:206` recorded it as a rejected payer answer and escalated `DEP-1004` to a person.
6. When app4 asks about `DEP-1004` with the right secret, the deposit is no longer waiting: `409 deposit is not awaiting a payer agent answer`. The response has no `verification`.

**Why it is an app bug, not a test bug:**
- `ask_agents` documents "Errors from the simulated agents propagate", and the route's contract is "The payment stays waiting".
- The stdio path decrypts in the parent (`client.py:147`) and keeps that contract.
- A server-side misconfiguration was being written into a company's books as the *payer's* agent failing verification. It also escalated a payment.

**Fix (commit `b44469d`, `payer_agents/client.py`):** in the in-process transport, decrypt PostgreSQL-stored keys in the caller and hand them over as `EnvKeys`, exactly as the stdio path does. A key that cannot be decrypted now raises before anything is recorded. SQLite key files are unchanged.

### 2. `test_a_context_held_during_deletion_never_recreates_the_database`: app bug (PostgreSQL half of `245da67`)

Fails in "Whole suite on PostgreSQL": `Failed: DID NOT RAISE RuntimeError` at `backend/tests/test_account.py:77`.

**What happens:**
- Commit `245da67` made a context held during deletion refuse to recreate the deleted company's database, but the guard covers SQLite only (`context.py:89-91`).
- On PostgreSQL, every connection runs `CREATE SCHEMA IF NOT EXISTS` (`pg.py:312`).
- So the held context **silently recreated an empty schema for the deleted company**. A probe confirmed it: the schema count went 0 after the delete, then 1 after one `held.conn()`, and nothing raised.

**Why it matters:** this is the bug the test exists for, on the backend the live deployment uses.

**Fix (commit `d8580d0`):**
- `PgConnection(..., create=False)` and `db.connect(..., create=False)` skip `CREATE SCHEMA`. They raise `pg.SchemaMissing` when `current_schema()` is NULL, which is what PostgreSQL returns when the pinned schema does not exist. That costs no extra query.
- `OrgContext.connect` uses `create=False` after its first migration and raises the same `"this organization's data no longer exists"` as on SQLite.
- First-time initialisation still creates the schema.

### 3. `test_deleting_an_organization_needs_its_exact_name_and_removes_its_data`: test bug

Fails in "Whole suite on PostgreSQL": `assert data.exists()` at `backend/tests/test_account.py:47`.

**Why it is a test bug:**
- The test asserts that `data_dir/orgs/<org_id>` exists before deletion and is gone after.
- On PostgreSQL a company's books are the schemas `<prefix>_t_<org>` and `<prefix>_b_<org>` (`tenancy.py:80-90`). That folder never exists there, whatever the app does.
- So the assertion was always false on PostgreSQL: it tested the storage layout, not the behaviour.

**Fix (commit `d8580d0`):** a helper `_org_storage(app, org_id)` reports the storage the backend actually uses: the folder on SQLite, the two schemas on PostgreSQL.
- Both deletion tests now assert that the storage exists before and is gone after.
- Nothing was weakened. On SQLite the checks are identical to before. On PostgreSQL they are stronger, since test 2 now also proves the schema was not recreated.

## Other checks

- **`workflow_dispatch`:** present (`on: push, pull_request, workflow_dispatch`).
- **README CI badge** (`README.md:18`): `https://github.com/Lingu17/ledgerline/actions/workflows/ci.yml/badge.svg`.
  - Correct owner, repo and workflow file name. With no `?branch=`, it shows the latest run on the default branch.
  - While the repo is private the image does not load for visitors.
  - After going public, it will show the last *recorded* run on `main`, i.e. the billing-blocked failure, until a new run completes. Push to `main` or use **Run workflow** (`workflow_dispatch`) once the repo is public.
  - It is a bare `<img>` with no link to the Actions page (cosmetic).
- **Secrets:** none.
  - The workflow references no `secrets.*` or `vars.*`.
  - Actions used: `actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`, all public. The `postgres:17` image comes from Docker Hub with a throwaway password set inline.
  - Playwright downloads Chromium from its public CDN.
  - The tests run with every API key blanked, and `backend/.env.test` is optional and gitignored.
  - A fresh public repo has everything this workflow needs.

## Not covered here

- **windows-latest backend leg.** It cannot run in a Linux container. The two fixes are OS-neutral, and the SQLite branch of `OrgContext.connect` behaves exactly as before. Windows was last checked locally by the owner, at `b3ba221`.
- **e2e browser build.** e2e ran on Chromium 153 instead of the pinned Playwright's Chromium 156 (download blocked; see above).
- **Follow-ups found in passing, not changed:**
  - Since `aab8d3e`, `test_postgres_stdio_mcp_signing_identity_survives_restart` signs up a *practice* company, so despite its name it runs the in-process transport. **PostgreSQL + stdio has no test coverage now.** Covering it would need a real company with deposits awaiting an agent.
  - The payer-key store (`keys._pg_conn`) and the simulated bank (`providers/local.py:79`) still connect with schema creation. A held context reaches them only after `OrgContext.connect`, which now refuses first.

## Full output of every failure at `b3ba221`

<details><summary>postgres › PostgreSQL-specific tests: <code>pytest -v tests/test_postgres.py</code> (1 failed, 12 passed; step exit 1)</summary>

```
=================================== FAILURES ===================================
__________ test_postgres_stdio_mcp_signing_identity_survives_restart ___________

    @needs_pg
    def test_postgres_stdio_mcp_signing_identity_survives_restart():
        app = _pg_app(LEDGERLINE_PAYER_MCP_TRANSPORT="stdio")
        prefix = app.state.settings.pg_schema_prefix
        c = _signup(app, "mcp@pg.test")
        first = c.post("/api/deposits/DEP-1006/ask-agent").json()
        assert first["transport"] == "mcp/stdio" if "transport" in first else True
        assert first["verification"]["verdict"] == "verified"
        def registry(client):
            return sorted((x["id"], x["agent_key_id"], x["agent_public_key"]) for x in client.get("/api/customers").json())
    
        key_id = registry(c)
        pg.close_all()
        app2 = _pg_app(prefix=prefix, LEDGERLINE_PAYER_MCP_TRANSPORT="stdio")
        from .conftest import PASSWORD
    
        c2 = TestClient(app2)
        r = c2.post("/api/auth/login", json={"email": "mcp@pg.test", "password": PASSWORD})
        c2.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        assert registry(c2) == key_id  # same registered public keys
        v = c2.post("/api/deposits/DEP-1005/ask-agent").json()["verification"]
        assert v["verdict"] == "verified"  # signed after restart by the same, decrypted identity
        # A different server secret cannot decrypt the stored keys: refused, never a silently new identity.
        pg.close_all()
        app3 = _pg_app(prefix=prefix, LEDGERLINE_SECRET_KEY="another-secret-" + "z" * 32, LEDGERLINE_PAYER_MCP_TRANSPORT="stdio")
        c3 = TestClient(app3, raise_server_exceptions=False)
        r = c3.post("/api/auth/login", json={"email": "mcp@pg.test", "password": PASSWORD})
        c3.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        bad = c3.post("/api/deposits/DEP-1004/ask-agent")
        assert bad.status_code >= 500 or bad.json().get("verification", {}).get("verdict") != "verified"
        # ...and the stored identity is untouched: with the right secret the agent still signs verifiable answers.
        pg.close_all()
        app4 = _pg_app(prefix=prefix, LEDGERLINE_PAYER_MCP_TRANSPORT="stdio")
        c4 = TestClient(app4)
        r = c4.post("/api/auth/login", json={"email": "mcp@pg.test", "password": PASSWORD})
        c4.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        assert registry(c4) == key_id
>       v = c4.post("/api/deposits/DEP-1004/ask-agent").json()["verification"]
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'verification'

tests/test_postgres.py:328: KeyError
------------------------------ Captured log call -------------------------------
ERROR    mcp.server.mcpserver.server:server.py:455 Tool 'explain_payment' raised an unexpected exception
Traceback (most recent call last):
  File "<checkout>/backend/ledgerline/payer_agents/keys.py", line 84, in decrypt
    return _aead(secret).decrypt(raw[:12], raw[12:], _aad(target, customer_id)).decode()
           ~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
cryptography.exceptions.InvalidTag

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "<venv>/lib/python3.14/site-packages/mcp/server/mcpserver/tools/base.py", line 179, in run
    result = await self.fn_metadata.call_fn(self.fn, self.is_async, validated, pass_directly)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<venv>/lib/python3.14/site-packages/mcp/server/mcpserver/utilities/func_metadata.py", line 164, in call_fn
    return await anyio.to_thread.run_sync(functools.partial(fn, **kwargs))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<venv>/lib/python3.14/site-packages/anyio/to_thread.py", line 65, in run_sync
    return await get_async_backend().run_sync_in_worker_thread(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        func, args, abandon_on_cancel=abandon_on_cancel, limiter=limiter
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "<venv>/lib/python3.14/site-packages/anyio/_backends/_asyncio.py", line 2706, in run_sync_in_worker_thread
    return await future
           ^^^^^^^^^^^^
  File "<venv>/lib/python3.14/site-packages/anyio/_backends/_asyncio.py", line 1100, in run
    result = context.run(func, *args)
  File "<checkout>/backend/ledgerline/payer_agents/server.py", line 42, in explain_payment
    keys = load_keys(data_dir)  # never creates: a missing key means no agent, not a new identity
  File "<checkout>/backend/ledgerline/payer_agents/keys.py", line 110, in load_keys
    return {r["customer_id"]: decrypt(loc.secret, loc.target, r["customer_id"], r["private_key_enc"]) for r in rows}
                              ~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<checkout>/backend/ledgerline/payer_agents/keys.py", line 86, in decrypt
    raise KeyStoreError(f"cannot decrypt the signing key for {customer_id}: wrong LEDGERLINE_SECRET_KEY or tampered row") from exc
ledgerline.payer_agents.keys.KeyStoreError: cannot decrypt the signing key for CUST-ACME: wrong LEDGERLINE_SECRET_KEY or tampered row

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "<venv>/lib/python3.14/site-packages/mcp/server/mcpserver/server.py", line 442, in _handle_call_tool
    return await self.call_tool(params.name, params.arguments or {}, context)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<venv>/lib/python3.14/site-packages/mcp/server/mcpserver/server.py", line 548, in call_tool
    return await self._tool_manager.call_tool(name, arguments, context, convert_result=True)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<venv>/lib/python3.14/site-packages/mcp/server/mcpserver/tools/tool_manager.py", line 87, in call_tool
    return await tool.run(arguments, context, convert_result=convert_result)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<venv>/lib/python3.14/site-packages/mcp/server/mcpserver/tools/base.py", line 213, in run
    raise UnexpectedToolError(f"Error executing tool {self.name}") from exc
mcp.server.mcpserver.exceptions.UnexpectedToolError: Error executing tool explain_payment
- generated xml file: <checkout>/backend/pg-specific.xml -
=========================== short test summary info ============================
FAILED tests/test_postgres.py::test_postgres_stdio_mcp_signing_identity_survives_restart
======================== 1 failed, 12 passed in 10.92s =========================
::error title=tests.test_postgres.test_postgres_stdio_mcp_signing_identity_survives_restart::KeyError: 'verification'
1 failing tests
```
</details>

<details><summary>postgres › Whole suite on PostgreSQL (3 failed, 586 passed, 10 skipped; step exit 1). The third failure's output is the same as above.</summary>

```
=================================== FAILURES ===================================
___ test_deleting_an_organization_needs_its_exact_name_and_removes_its_data ____

client = <starlette.testclient.TestClient object at 0x7fd64c37c770>
app = <fastapi.applications.FastAPI object at 0x7fd64c335400>

    def test_deleting_an_organization_needs_its_exact_name_and_removes_its_data(client, app):
        org_id, name = client.org_id, client.get("/api/organization").json()["name"]
        data = app.state.settings.data_dir / "orgs" / org_id
>       assert data.exists()
E       AssertionError: assert False
E        +  where False = exists()
E        +    where exists = PosixPath('/tmp/pytest-of-root/pytest-4/test_deleting_an_organization_0/orgs/org_14961ea039ba').exists

tests/test_account.py:47: AssertionError
_______ test_a_context_held_during_deletion_never_recreates_the_database _______

client = <starlette.testclient.TestClient object at 0x7fd64d7a6780>
app = <fastapi.applications.FastAPI object at 0x7fd64bfe7cb0>

    def test_a_context_held_during_deletion_never_recreates_the_database(client, app):
        import pytest
    
        held = app.state.orgs.get(client.org_id)  # as a background round would hold it
        name = client.get("/api/organization").json()["name"]
        assert client.post("/api/organization/delete", json={"confirm": name}).status_code == 200
>       with pytest.raises(RuntimeError, match="no longer exists"):
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       Failed: DID NOT RAISE RuntimeError

tests/test_account.py:77: Failed
=========================== short test summary info ============================
FAILED tests/test_account.py::test_deleting_an_organization_needs_its_exact_name_and_removes_its_data
FAILED tests/test_account.py::test_a_context_held_during_deletion_never_recreates_the_database
FAILED tests/test_postgres.py::test_postgres_stdio_mcp_signing_identity_survives_restart
3 failed, 586 passed, 10 skipped in 242.49s (0:04:02)
::error title=tests.test_account.test_deleting_an_organization_needs_its_exact_name_and_removes_its_data::AssertionError: assert False  +  where False = exists()  +    where exists = PosixPath('/tmp/pytest-of-root/pytest-4/test_deleting_an_organization_0/orgs/org_14961ea039ba').exists
::error title=tests.test_account.test_a_context_held_during_deletion_never_recreates_the_database::Failed: DID NOT RAISE RuntimeError
::error title=tests.test_postgres.test_postgres_stdio_mcp_signing_identity_survives_restart::KeyError: 'verification'
3 failing tests
```
</details>
