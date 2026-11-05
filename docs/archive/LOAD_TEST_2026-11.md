# Load test: many judges running the Practice company walkthrough at once (4 Nov 2026)

> **Since this report (5 Nov):** the problems it found were fixed. Practice companies now ask the simulated payer agents in-process (`aab8d3e`), passwords are hashed outside the database write lock (`6c4475c`, then `fcadcb9`), and the keep-alive timeout is 75 s. The in-process figures below (`PAYER_MCP_TRANSPORT=memory`) are the ones that now apply to practice companies.

Measured on commit `d22f23243d908fc02b28d3a835cf82b157f6d466` of `deploy/vercel-render` ("Account basics: change your name, an owner's reset link, leave, delete a company, delete your account"). This report only measures. No code was changed, nothing was deployed, the live site was not touched, and no Airwallex or Anthropic keys were used.

## Summary

- **Largest load with p95 under 2 s on every endpoint and no errors: 30 concurrent judges** (ramped over 1 minute). At 30 the slowest endpoint p95 was 1.67 s. At 35 and 40 there were still no errors, but the two payer-agent calls went over 2 s (p95 2.6 s).
- **The bottleneck is the payer-agent call.** `POST /deposits/DEP-1005/ask-agent` and the `agents` practice step each start a new Python process for the simulated payer agent's MCP server (`payer_agents/client.py:147-149`). That takes about 1 s of CPU and about 50 MB each. It runs inside a request worker thread, so many judges at once use up the 2 CPUs and the worker threads. Every other endpoint then has to wait.
  - 50 judges: payer-agent p95 was 11 s (max 14.7 s). Other endpoints stayed under 0.6 s p95.
  - 100 judges: payer-agent p95 was 34 s. Memory peaked at **1.93 GB of the 2 GB limit**, and **7 sign-ups failed with 500 `database is locked`**.
- **The same 50 and 100 judges with the existing setting `LEDGERLINE_PAYER_MCP_TRANSPORT=memory`** (no extra process, no code change) gave: 50 judges, slowest p95 0.28 s and peak CPU 65%; 100 judges, slowest p95 0.74 s, no errors and peak memory 497 MB.
- **5-minute soak, 50 judges, watcher on:** all 50 walkthroughs finished. There were no HTTP errors. 9 requests from 2 judges got **connection resets**, which points to uvicorn's 5 s keep-alive timeout (see problem 4). During the browsing phase, `/ceo` p95 was 1.7 s because the load script clicks much faster than a person (73 requests/s in total).
- **Integrity held in every run:** each of the 468 practice companies created in the measured runs had balanced books (`ledger.conservation`) and a verified audit chain (`audit.verify_chain`) at the end. Each had also tampered and restored its chain once. No company was left half-written, including the 7 whose sign-up failed (no company database was created for them).
- **Default sign-up limits:** from one address, the 11th sign-up in an hour gets **429** with the message *"too many new accounts or organizations from your network in the last hour; try again later or ask an owner for an invitation"* and `Retry-After: 3600`. That is what judges on one shared venue network would see after the first 10.
- **Disk:** 356,748 bytes (about 350 KB) per practice company after a full walkthrough, plus about 0.8 KB per sign-up in `control.sqlite3`.

## Setup

| Item | What was used |
|---|---|
| Code | `deploy/vercel-render` @ `d22f232`, repository mounted read-only into the container |
| Server | `python -m ledgerline` (uvicorn, one process, `proxy_headers=False`), the built frontend (`npm ci && npm run build` → `frontend/dist`, served by the API), `bank=local` (the simulated bank), `claude=offline-fixture` (no `ANTHROPIC_API_KEY`), payer agents on their default `stdio` transport |
| Limits | Docker 29.9.2 with `--cpus=2 --memory=2g --memory-swap=2g` (no swap), image `python:3.14-slim` (from `mirror.gcr.io`) with `requirements-lock.txt`, `--network host`, cgroup v1 |
| Host | 4 vCPU and 16 GB cloud container. The load generator ran on the host, outside the container's 2-CPU limit |
| Environment | `LEDGERLINE_DATA_DIR=/data` (a fresh empty directory for every run), `LEDGERLINE_TRUSTED_PROXY_HOPS` unset (0: no proxy, the client is the socket peer, 127.0.0.1). For the load runs the sign-up limits were raised to 100000 with `LEDGERLINE_SIGNUP_PER_IP_HOUR`, `LEDGERLINE_SIGNUP_PER_IP_DAY` and `LEDGERLINE_SIGNUP_PER_DAY`. The `defaults` run kept 10/40/500 |
| Watcher | `LEDGERLINE_WATCH_SECONDS=0` for the ramps, and the production default `120` for the 5-minute soak and the defaults run |
| Differences from production | `LEDGERLINE_COOKIE_SECURE=0`, because the test is plain HTTP on loopback with no Caddy (a secure cookie would not be sent back over http). There was no TLS and no Caddy, so the keep-alive behaviour between Caddy and uvicorn was not tested. The disk is the host's disk, not a GCE balanced persistent disk. An e2-small is a shared-core machine that only bursts to 2 vCPU, so `--cpus=2` is the **best case**. Expect the VM to be slower than this when it runs at full load for long. Caddy and the Ops Agent also use part of the VM's 2 GB, which leaves less memory headroom than measured here |

### The load script

The script is `load.py` (Python asyncio + httpx 0.28.1). Per the brief it is kept outside the repository, together with `run.sh`, `monitor.sh` and `verify.py`, in the session's scratch directory. Each simulated judge uses its own cookie jar and CSRF token. Each screen's GET requests are sent at the same time, as the SPA does. Between actions the judge waits a random 0.5–2 s ("think time"). Judges start evenly spread over 60 s. Each judge:

1. `POST /auth/signup` with `start_with: "sample"` (a Practice company), then `GET /auth/me` and `/status`.
2. Inbox: `/overview`, `/treasury`, `/status`, `/setup`, `/audit?limit=12`.
3. Payments: list (`/deposits`, `/customers`, `/invoices`), then DEP-1005 (`/deposits/DEP-1005`, `/explanation`), then `POST /deposits/DEP-1005/ask-agent`.
4. Practice steps: loops on `GET /demo` and runs each `next` step (`agents`, `treasury`). When the next step is approve, it opens Approvals (`/approvals`, `/operations`, `/treasury/bill-payments`), sends `POST /approvals/{id}/approve` with the scope hash, and then `POST /approvals/{id}/send-as-practice-teammate`. It finishes with `bank_sent` and `bank_paid`, until `next` is null. `seed`, `deposits` and `links` are done at sign-up.
5. `GET /ledger` (the judge fails if `all_balanced` is false) and `GET /ceo`.
6. Why this plan (`POST /deposits/DEP-1005/explanation`), then Replay of every plan version (`GET /deposits/DEP-1005/plans/{v}/replay`). Then Activity (`/practice/tamper`, `/audit/verify`, `/audit?limit=50`), `POST /practice/tamper` (the judge fails unless `verify` then reports the break), and `POST /practice/tamper/restore` (the judge fails unless the chain is OK again).

In the soak, a judge that has finished keeps opening random screens (Inbox, Payments and a deposit, Ledger, CEO, Replay, Activity, Approvals) with the same think time until 5 minutes are up. CPU and memory were sampled every second from the container's cgroup (`cpuacct.usage`, `memory.usage_in_bytes`, `total_rss`, `memory.max_usage_in_bytes`). 200% means both CPUs were fully busy. After each run the server was stopped, and `verify.py` opened every `orgs/*/ledgerline.sqlite3` and ran `ledgerline.ledger.conservation` and `ledgerline.audit.verify_chain` on it.

## Results by run

`n` counts requests. Times are client-measured wall time in seconds. "Conn reset" means the TCP connection closed without an HTTP response.

| Run | Judges | Requests | Walkthroughs | Status counts | Slowest endpoint (p95) | Overall p50 / p95 / p99 (s) | Peak CPU (of 200%) | Peak RSS / cgroup max | Books balance | Chain verifies |
|---|---|---|---|---|---|---|---|---|---|---|
| ramp 10 | 10 | 510 | 10/10 | 200: 510 | `POST /demo/step [agents]` 1.16 s | 0.017 / 0.154 / 1.088 | 115% | 236 MB / 269 MB | 10/10 | 10/10 |
| ramp 30 | 30 | 1,530 | 30/30 | 200: 1,530 | `POST /demo/step [agents]` 1.67 s | 0.017 / 0.184 / 1.288 | 206% | 381 MB / 420 MB | 30/30 | 30/30 |
| ramp 35 | 35 | 1,785 | 35/35 | 200: 1,785 | `POST /demo/step [agents]` 2.60 s | 0.020 / 0.182 / 1.711 | 205% | 431 MB / 492 MB | 35/35 | 35/35 |
| ramp 40 | 40 | 2,040 | 40/40 | 200: 2,040 | `POST /demo/step [agents]` 2.56 s | 0.020 / 0.240 / 1.819 | 206% | 417 MB / 475 MB | 40/40 | 40/40 |
| ramp 50 | 50 | 2,550 | 50/50 | 200: 2,550 | `POST /demo/step [agents]` 11.56 s | 0.075 / 0.769 / 8.313 | 207% | 990 MB / 1,068 MB | 50/50 | 50/50 |
| **soak 50, 5 min, watcher 120 s** | 50 | 21,900 | 50/50 (2 judges then hit a reset while browsing) | 200: 21,891, conn reset: 9 | `POST /deposits/{dep}/ask-agent` 11.03 s | 0.088 / 0.847 / 1.574 | 206% | 870 MB / 912 MB | 50/50 | 50/50 |
| ramp 100 (extra) | 100 | 4,750 | 93/100 | 200: 4,743, **500: 7** | `POST /deposits/{dep}/ask-agent` 33.69 s | 1.090 / 6.834 / 23.604 | 206% | 1,821 MB / **1,932 MB** | 93/93 | 93/93 |
| ramp 50, `PAYER_MCP_TRANSPORT=memory` (extra) | 50 | 2,550 | 50/50 | 200: 2,550 | `POST /auth/signup` 0.28 s | 0.018 / 0.057 / 0.184 | 65% | 267 MB / 317 MB | 50/50 | 50/50 |
| ramp 100, `PAYER_MCP_TRANSPORT=memory` (extra) | 100 | 5,100 | 100/100 | 200: 5,100 | `POST /auth/signup` 0.74 s | 0.024 / 0.156 / 0.360 | 193% | 455 MB / 497 MB | 100/100 | 100/100 |
| default limits, 15 judges, one address | 15 | 515 | 10/15 | 200: 510, **429: 5** | `POST /deposits/{dep}/ask-agent` 2.55 s | 0.018 / 0.179 / 2.152 | 203% | 308 MB / 334 MB | 10/10 | 10/10 |

The defaults run started its 15 judges within 15 s, so it is a burstier load than the 60 s ramps. That is why its payer-agent p95 was already 2.55 s. The memory runs are not a recommendation on their own. They isolate the cost of the extra process (see problem 1).

### CPU and memory over time (soak)

In the first ~90 s, while judges were still in the walkthrough, both CPUs were at 100% (about 200%) and up to 14 processes ran in the container (the server plus up to 13 payer-agent processes). RSS rose to 870 MB. Once every judge was only browsing, there was one process again and RSS settled at about 430 MB. The browsing load kept CPU at 100–200%. Python does not hand memory freed after the spike back to the system, so the server held about 430 MB until it was stopped. The watcher made no visible difference (see "Background watcher").

## Errors

| Run | Status | Count | Where | What |
|---|---|---|---|---|
| default limits | 429 | 5 | `POST /auth/signup` (the 11th to 15th from 127.0.0.1) | `{"detail":"too many new accounts or organizations from your network in the last hour; try again later or ask an owner for an invitation"}`, `Retry-After: 3600`. Expected behaviour (problem 5) |
| soak 50 | conn reset | 9 | One whole page of requests from each of 2 judges: Inbox at t=181 s (5 requests) and Payments at t=214 s (4) | httpx `ReadError` / `RemoteProtocolError: Server disconnected without sending a response`. Nothing in the server log (the requests never reached the app). See problem 4 |
| ramp 100 | 500 | 7 | `POST /auth/signup` | `sqlite3.OperationalError: database is locked` from the control database, each after 10.8–11.7 s (`busy_timeout` 10 s). See problem 2 |

The `database is locked` trace from the server log (ramp 100, the first of 7; the frames are the same for all):

```
2026-11-04 18:02:18,891 ERROR ledgerline POST /auth/signup failed after 10830ms: OperationalError org=- user=-
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
  File "/app/backend/ledgerline/api/app.py", line 82, in request_log
    response = await call_next(request)
  ...
  File "/app/backend/ledgerline/api/auth_routes.py", line 69, in signup
  File "/app/backend/ledgerline/control.py", line 260, in signup
    with self.conn() as c, db.transaction(c):
  ...
sqlite3.OperationalError: database is locked
```

There were no other tracebacks, `ERROR` lines or `database is locked` lines in any run: 0 in ramp 10/30/35/40/50, soak, both memory runs and the defaults run. No tenant (per-company) database ever reported a lock. Every lock was on the shared `control.sqlite3`.

## Disk used per practice company

Measured after a clean shutdown (WAL files written back into the main files), identical for every company in every run:

| File | Bytes |
|---|---|
| `orgs/<id>/ledgerline.sqlite3` | 315,392 |
| `orgs/<id>/local_bank.sqlite3` | 40,960 |
| `orgs/<id>/payer_agents/private_keys.json` | 396 |
| **Total per company** | **356,748 (about 348 KiB)** |
| `control.sqlite3` growth | about 0.8 KB per sign-up (172 KB after 50 sign-ups plus the soak's sessions) |

At the server's daily cap of 500 sign-ups that is at most about 175 MB a day. That is small next to the 12 GB free noted in DEPLOYMENT.md, but the nightly backups keep 7 copies of every company.

## Background watcher

With `LEDGERLINE_WATCH_SECONDS=120` the watcher ran twice during the 5-minute soak. It does no work for practice companies. `watcher.sweep` loops over `control.all_org_ids()` and skips every company whose `bank_mode` is not `airwallex_sandbox` (`backend/ledgerline/watcher.py:44-47`). Practice companies are on the simulated bank, so each round costs one control read per company. That cost could not be told apart from the browsing load. It did not cause any error or lock. A real company connected to Airwallex, which this test does not cover, would have the watcher calling Airwallex and its customers' agents at the same time as the judges.

## Problems and suggested fixes

Paths are relative to the repository root at `d22f232`. These are suggestions for the session that owns code changes. None of them was applied here.

### 1. Each payer-agent question starts a new Python process, and that limits capacity to about 30 judges

- **Seen:** `ask-agent` and `demo/step [agents]` take about 1.0 s with 10 judges, 1.6 s with 30, 2.6 s with 35–40, 11 s with 50 and 34 s with 100. The server log's own timings agree (ask-agent server-side p50 5.4 s and max 14.7 s at 50 judges), so the time is spent inside the server, not in the network. The container's process count followed the payer-agent calls: 16 processes at 50 judges and 40 at 100, each about 45–50 MB. With `LEDGERLINE_PAYER_MCP_TRANSPORT=memory` the same calls took 0.05–0.33 s at 50–100 judges.
- **Why:** `backend/ledgerline/payer_agents/client.py:147` builds `StdioServerParameters(command=sys.executable, args=["-m", "ledgerline.payer_agents.server", ...])`, and `:149` runs `anyio.run(_call_all, ...)`. So every question starts a new interpreter, imports `mcp`, `pydantic` and `cryptography`, and then exits. It runs inside a FastAPI sync worker thread (callers: `backend/ledgerline/api/routes.py:203`, `backend/ledgerline/demo.py:202`, `backend/ledgerline/agent_loop.py:29`). That thread is held for the whole call. Once the calls take tens of seconds they fill the default 40-thread pool, and every other sync endpoint has to wait behind them. That is why sign-up and `send-as-practice-teammate` reached 5–13 s at 100 judges.
- **Fix, best first:**
  1. Keep **one long-lived simulated payer-agent MCP server per data directory**, started once (or lazily) and reused, with a lock around its stdio session. Change `explain_payments` (`backend/ledgerline/payer_agents/client.py:126-149`) to use it. This keeps the visible `mcp/stdio` process boundary and removes about 1 s of CPU and 50 MB per question.
  2. If that is too large a change before judging, put a module-level `threading.BoundedSemaphore(3)` around the `anyio.run` at `backend/ledgerline/payer_agents/client.py:149`. This caps memory and keeps the thread pool free. Payer-agent calls still queue, but the rest of the app stays fast.
  3. Configuration only: set `LEDGERLINE_PAYER_MCP_TRANSPORT=memory` in `/etc/ledgerline/ledgerline.env` (read at `backend/ledgerline/config.py:86` / `load_settings`). This was measured: 100 judges with no errors and a slowest p95 of 0.74 s. Trade-off: the answers are then labelled `mcp/in-memory` rather than `mcp/stdio`, and README/JUDGE_QA text that says "over MCP" should still be true but no longer crosses a process boundary. That is the owner's call.

### 2. Sign-up hashes the password while holding the control database's write lock, which gives 500 `database is locked`

- **Seen:** 7 × 500 on `POST /auth/signup` at 100 judges, each after about 11 s. Sign-up p95 was 2.1 s at 50 judges and 13 s at 100.
- **Why:** `backend/ledgerline/control.py:260` opens `db.transaction(c)` (`BEGIN IMMEDIATE` on the shared `control.sqlite3`), and `:266` calls `hash_password(password)` inside it. scrypt n=2^14 (`backend/ledgerline/control.py:54`) takes about 50 ms of CPU when the machine is idle and much longer when both CPUs are busy. All sign-ups across the server queue on that one lock, along with the session `last_seen_at` write (`backend/ledgerline/control.py:327`). When the wait passes `busy_timeout` (10 s, `backend/ledgerline/db.py:277` and `:280`), the `OperationalError` is not caught and becomes a bare 500.
- **Fix:** compute `password_hash = hash_password(password)` before `with self.conn() as c, db.transaction(c):` at `backend/ledgerline/control.py:260`, and use that variable at `:266`. The same pattern (scrypt inside `BEGIN IMMEDIATE`) is also at `backend/ledgerline/control.py:287`→`:294` (sign-in), `:343`→`:345`/`:347` (change password), `:412`→`:419` and `:432`→`:439`/`:447` (invitation accept). Verify or hash before opening the transaction, then re-check the row inside it. Also convert `sqlite3.OperationalError("database is locked")` into a 503 with `Retry-After`, next to the `AuthError` handler at `backend/ledgerline/api/auth_routes.py:564`, so the judge sees "busy, try again" rather than a generic error.

### 3. Memory comes close to the 2 GB limit at about 100 judges

- **Seen:** cgroup peak 1,932 MB of 2,048 MB at 100 judges, with no swap. RSS was 1,821 MB. On the VM, Caddy, systemd and the Ops Agent share the same 2 GB, so the real margin is smaller, and the Linux OOM killer would stop the service (systemd then restarts it after 3 s).
- **Why:** the same per-question processes as problem 1, about 45–50 MB each.
- **Fix:** problem 1 (any of its options). With the in-memory transport, 100 judges peaked at 497 MB. As a backstop, add `MemoryMax=1400M` to `deploy/vm/ledgerline.service`, so that only the service, not Caddy or sshd, is killed under pressure.

### 4. Connection resets under load (uvicorn keep-alive timeout)

- **Seen:** in the soak, 9 requests made of two whole page bursts (5 and 4 parallel GETs from the same judge) failed at once without an HTTP response. The server log has no line for them. A separate quiet test (reusing a connection after 4.90–5.05 s idle) did not reproduce it. It happens only while the event loop is busy.
- **Why (likely):** `backend/ledgerline/__main__.py:32` calls `uvicorn.run(...)` without `timeout_keep_alive`, so uvicorn closes idle connections after 5 s. A judge's parallel connections go idle at the same moment, and if the next page is sent just as the timer fires on a busy loop, the server closes them anyway. In production the browser talks to Caddy, and Caddy keeps its own upstream connections to uvicorn idle for longer than 5 s by default. Caddy's Go transport retries a GET on a reused connection that was closed, but not a POST, so this race could show as an occasional **502 on a POST** (approve, ask-agent, a step). This was not tested through Caddy here.
- **Fix:** pass `timeout_keep_alive=75` (any value longer than Caddy's upstream idle time) at `backend/ledgerline/__main__.py:32`, or set `transport http { keepalive 4s }` on the `reverse_proxy 127.0.0.1:8000` at `deploy/vm/Caddyfile.single:14`. Either way, Caddy should never reuse a connection uvicorn is about to close.

### 5. Default sign-up limit: judges on one shared network are refused after 10 an hour

- **Seen:** with the defaults (10/hour, 40/day per address, 500/day per server), sign-ups 1–10 from 127.0.0.1 succeeded and the 11th got `429`, `Retry-After: 3600`, *"too many new accounts or organizations from your network in the last hour; try again later or ask an owner for an invitation"* (`backend/ledgerline/control.py:156`). The Sign-up screen shows the server's message for a sign-up 429 (`frontend/src/views/Auth.tsx:74-75`). Judges at a venue, or behind one corporate or university NAT, share one public address, so the 11th judge in that hour cannot create a Practice company.
- **Fix:** for judging day, raise `LEDGERLINE_SIGNUP_PER_IP_HOUR` and `LEDGERLINE_SIGNUP_PER_IP_DAY` (for example 60 and 200) in `/etc/ledgerline/ledgerline.env` (read at `backend/ledgerline/config.py:237`). Keep `LEDGERLINE_SIGNUP_PER_DAY=500`, which is well above any judging load measured here, as the overall cap. Also consider adding to the hourly message that a judge can sign in to a Practice company a teammate already created. Note that the 2 s / 30-judge capacity limit (problem 1) applies whatever the sign-up limit is.

### 6. Browsing-only load: `/ceo`, `/overview` and `/ledger` are the heaviest reads

- **Seen:** in the soak's browsing phase (73 requests/s from 50 judges clicking every 0.5–2 s, much faster than people), p95 was 1.7 s for `/ceo`, 1.5 s for `/overview` and 1.1 s for `/ledger`. Everything else was under 1 s. There were no errors. At real judge pace (a click every several seconds) this should be well under 1 s, but that pace was not measured.
- **Fix (only if problem 1 is fixed and the reads still matter):** these pages rebuild the whole conservation and journal on every request (`backend/ledgerline/api/routes.py:693-698` for `/ledger`, `:105` for `/ceo`, `:113` for `/overview`). A short per-company cache keyed on the audit head would remove most of that repeated work.

## Answer: the largest number of concurrent judges under 2 s p95 with no errors

**30**, on the code and settings as deployed (stdio payer agents, 2 vCPU / 2 GB, 60 s ramp). At 35 and 40 there were no errors, but the payer-agent p95 was 2.6 s. At 50 the payer-agent p95 was 11 s, still without HTTP errors. At 100 there were 500s and memory came within 120 MB of the limit. With the existing `LEDGERLINE_PAYER_MCP_TRANSPORT=memory` setting, 100 judges stayed under 0.75 s p95 with no errors. A real e2-small that has used up its CPU burst will do somewhat worse than this container.

## Per-endpoint latency

Sorted by p95 in the rightmost run. `n · p50 / p95 / p99`, in seconds.

### Ramps: 10, 30, 50 judges over 1 minute (watcher off)

| Endpoint | ramp10: n · p50 / p95 / p99 (s) | ramp30: n · p50 / p95 / p99 (s) | ramp50: n · p50 / p95 / p99 (s) |
|---|---|---|---|
| `POST /demo/step [agents]` | 10 · 1.032 / 1.160 / 1.186 | 30 · 1.134 / 1.669 / 1.698 | 50 · 5.415 / 11.559 / 13.216 |
| `POST /deposits/{dep}/ask-agent` | 10 · 0.994 / 1.128 / 1.132 | 30 · 1.161 / 1.631 / 1.682 | 50 · 5.502 / 10.842 / 14.231 |
| `POST /auth/signup` | 10 · 0.158 / 0.176 / 0.179 | 30 · 0.188 / 0.320 / 0.324 | 50 · 0.887 / 2.056 / 2.713 |
| `POST /demo/step [bank_paid]` | 10 · 0.022 / 0.028 / 0.029 | 30 · 0.027 / 0.064 / 0.070 | 50 · 0.124 / 0.549 / 0.732 |
| `POST /demo/step [treasury]` | 10 · 0.043 / 0.062 / 0.068 | 30 · 0.042 / 0.097 / 0.129 | 50 · 0.227 / 0.526 / 0.561 |
| `POST /demo/step [bank_sent]` | 10 · 0.025 / 0.040 / 0.049 | 30 · 0.024 / 0.044 / 0.078 | 50 · 0.138 / 0.430 / 0.581 |
| `GET /overview` | 10 · 0.040 / 0.053 / 0.056 | 30 · 0.040 / 0.067 / 0.132 | 50 · 0.160 / 0.414 / 0.596 |
| `GET /customers` | 10 · 0.021 / 0.024 / 0.026 | 30 · 0.022 / 0.060 / 0.071 | 50 · 0.086 / 0.413 / 0.539 |
| `GET /deposits` | 10 · 0.024 / 0.027 / 0.027 | 30 · 0.025 / 0.058 / 0.074 | 50 · 0.096 / 0.397 / 0.547 |
| `GET /invoices` | 10 · 0.024 / 0.028 / 0.028 | 30 · 0.022 / 0.070 / 0.070 | 50 · 0.076 / 0.396 / 0.535 |
| `POST /approvals/{apr}/send-as-practice-teammate` | 10 · 0.027 / 0.040 / 0.041 | 30 · 0.028 / 0.050 / 0.057 | 50 · 0.156 / 0.382 / 0.468 |
| `GET /audit` | 20 · 0.020 / 0.030 / 0.031 | 60 · 0.024 / 0.053 / 0.091 | 100 · 0.086 / 0.350 / 0.537 |
| `GET /treasury` | 10 · 0.034 / 0.046 / 0.050 | 30 · 0.033 / 0.062 / 0.127 | 50 · 0.119 / 0.339 / 0.480 |
| `GET /setup` | 10 · 0.028 / 0.039 / 0.041 | 30 · 0.031 / 0.060 / 0.115 | 50 · 0.127 / 0.331 / 0.519 |
| `POST /approvals/{apr}/approve` | 10 · 0.014 / 0.024 / 0.024 | 30 · 0.014 / 0.054 / 0.071 | 50 · 0.076 / 0.315 / 0.517 |
| `GET /operations` | 10 · 0.019 / 0.023 / 0.024 | 30 · 0.020 / 0.063 / 0.107 | 50 · 0.087 / 0.289 / 0.482 |
| `GET /treasury/bill-payments` | 10 · 0.020 / 0.024 / 0.024 | 30 · 0.019 / 0.064 / 0.111 | 50 · 0.082 / 0.266 / 0.481 |
| `GET /approvals` | 10 · 0.018 / 0.024 / 0.024 | 30 · 0.019 / 0.066 / 0.111 | 50 · 0.074 / 0.264 / 0.391 |
| `GET /practice/tamper` | 30 · 0.015 / 0.024 / 0.043 | 90 · 0.016 / 0.051 / 0.057 | 150 · 0.029 / 0.264 / 0.436 |
| `GET /status` | 50 · 0.017 / 0.029 / 0.053 | 150 · 0.019 / 0.058 / 0.109 | 250 · 0.074 / 0.264 / 0.522 |
| `POST /practice/tamper/restore` | 10 · 0.015 / 0.031 / 0.033 | 30 · 0.016 / 0.030 / 0.051 | 50 · 0.026 / 0.256 / 0.346 |
| `POST /practice/tamper` | 10 · 0.014 / 0.024 / 0.024 | 30 · 0.014 / 0.022 / 0.024 | 50 · 0.047 / 0.255 / 0.371 |
| `GET /deposits/{dep}` | 30 · 0.014 / 0.024 / 0.088 | 90 · 0.016 / 0.029 / 0.049 | 150 · 0.074 / 0.249 / 0.363 |
| `GET /ceo` | 10 · 0.016 / 0.021 / 0.021 | 30 · 0.018 / 0.067 / 0.074 | 50 · 0.097 / 0.249 / 0.340 |
| `GET /audit/verify` | 30 · 0.016 / 0.027 / 0.044 | 90 · 0.016 / 0.051 / 0.063 | 150 · 0.029 / 0.236 / 0.415 |
| `GET /deposits/{dep}/explanation` | 30 · 0.012 / 0.021 / 0.086 | 90 · 0.013 / 0.029 / 0.043 | 150 · 0.072 / 0.212 / 0.278 |
| `POST /deposits/{dep}/explanation` | 10 · 0.012 / 0.023 / 0.029 | 30 · 0.014 / 0.024 / 0.033 | 50 · 0.060 / 0.206 / 0.256 |
| `GET /demo` | 70 · 0.007 / 0.011 / 0.014 | 210 · 0.007 / 0.019 / 0.035 | 350 · 0.035 / 0.191 / 0.295 |
| `GET /deposits/{dep}/plans/{v}/replay` | 20 · 0.008 / 0.014 / 0.016 | 60 · 0.008 / 0.026 / 0.053 | 100 · 0.021 / 0.189 / 0.272 |
| `GET /ledger` | 10 · 0.010 / 0.016 / 0.018 | 30 · 0.011 / 0.037 / 0.057 | 50 · 0.043 / 0.176 / 0.215 |
| `GET /auth/me` | 10 · 0.009 / 0.043 / 0.063 | 30 · 0.010 / 0.054 / 0.073 | 50 · 0.023 / 0.131 / 0.191 |

### Soak: 50 judges, 5 minutes, watcher every 120 s

| Endpoint | soak50: n · p50 / p95 / p99 (s) |
|---|---|
| `POST /deposits/{dep}/ask-agent` | 50 · 5.238 / 11.028 / 11.204 |
| `POST /demo/step [agents]` | 50 · 5.477 / 10.963 / 11.518 |
| `POST /auth/signup` | 50 · 0.763 / 2.561 / 3.471 |
| `GET /ceo` | 913 · 0.322 / 1.735 / 2.079 |
| `GET /overview` | 936 · 0.446 / 1.460 / 1.745 ⚠ 1×conn reset |
| `POST /demo/step [treasury]` | 50 · 0.347 / 1.437 / 1.742 |
| `GET /treasury` | 936 · 0.299 / 1.159 / 1.444 ⚠ 1×conn reset |
| `GET /ledger` | 965 · 0.198 / 1.126 / 1.540 |
| `POST /approvals/{apr}/send-as-practice-teammate` | 50 · 0.225 / 1.004 / 1.218 |
| `POST /demo/step [bank_paid]` | 50 · 0.243 / 0.971 / 1.333 |
| `POST /demo/step [bank_sent]` | 50 · 0.183 / 0.946 / 1.308 |
| `POST /practice/tamper/restore` | 50 · 0.125 / 0.724 / 0.891 |
| `GET /deposits` | 960 · 0.173 / 0.676 / 0.985 ⚠ 1×conn reset |
| `POST /practice/tamper` | 50 · 0.176 / 0.671 / 0.731 |
| `GET /practice/tamper` | 987 · 0.107 / 0.579 / 0.842 |
| `GET /audit/verify` | 987 · 0.104 / 0.552 / 0.851 |
| `GET /invoices` | 960 · 0.140 / 0.550 / 0.876 ⚠ 1×conn reset |
| `POST /approvals/{apr}/approve` | 50 · 0.086 / 0.526 / 0.649 |
| `GET /audit` | 1823 · 0.096 / 0.514 / 0.837 ⚠ 1×conn reset |
| `GET /deposits/{dep}` | 1059 · 0.111 / 0.466 / 0.706 |
| `GET /setup` | 936 · 0.106 / 0.424 / 0.773 ⚠ 1×conn reset |
| `POST /deposits/{dep}/explanation` | 50 · 0.142 / 0.417 / 0.697 |
| `GET /demo` | 350 · 0.077 / 0.393 / 0.545 |
| `GET /operations` | 884 · 0.074 / 0.370 / 0.646 |
| `GET /approvals` | 884 · 0.069 / 0.355 / 0.652 |
| `GET /treasury/bill-payments` | 884 · 0.054 / 0.332 / 0.667 |
| `GET /customers` | 960 · 0.079 / 0.321 / 0.680 ⚠ 1×conn reset |
| `GET /status` | 3789 · 0.059 / 0.321 / 0.637 ⚠ 2×conn reset |
| `GET /deposits/{dep}/explanation` | 1059 · 0.057 / 0.291 / 0.592 |
| `GET /deposits/{dep}/plans/{v}/replay` | 1028 · 0.043 / 0.282 / 0.598 |
| `GET /auth/me` | 50 · 0.024 / 0.227 / 0.285 |

### Extra runs: 40 judges, 100 judges, and the in-memory transport at 50 and 100

| Endpoint | ramp40: n · p50 / p95 / p99 (s) | stdio100: n · p50 / p95 / p99 (s) | mem50: n · p50 / p95 / p99 (s) | memory100: n · p50 / p95 / p99 (s) |
|---|---|---|---|---|
| `POST /auth/signup` | 40 · 0.234 / 0.617 / 0.697 | 100 · 5.163 / 13.113 / 15.664 ⚠ 7×500 | 50 · 0.184 / 0.278 / 0.333 | 100 · 0.227 / 0.742 / 1.299 |
| `GET /overview` | 40 · 0.048 / 0.163 / 0.186 | 93 · 1.439 / 4.603 / 5.318 | 50 · 0.049 / 0.078 / 0.091 | 100 · 0.062 / 0.479 / 0.589 |
| `POST /demo/step [treasury]` | 40 · 0.046 / 0.196 / 0.278 | 93 · 3.094 / 6.043 / 7.287 | 50 · 0.040 / 0.085 / 0.105 | 100 · 0.070 / 0.364 / 0.660 |
| `POST /demo/step [agents]` | 40 · 1.378 / 2.560 / 2.867 | 93 · 18.997 / 29.194 / 32.704 | 50 · 0.046 / 0.135 / 0.146 | 100 · 0.078 / 0.332 / 0.593 |
| `GET /ledger` | 40 · 0.011 / 0.059 / 0.079 | 93 · 0.675 / 3.433 / 6.412 | 50 · 0.010 / 0.036 / 0.049 | 100 · 0.016 / 0.323 / 0.456 |
| `GET /ceo` | 40 · 0.024 / 0.120 / 0.141 | 93 · 0.874 / 2.891 / 4.464 | 50 · 0.019 / 0.047 / 0.075 | 100 · 0.031 / 0.243 / 0.504 |
| `POST /deposits/{dep}/ask-agent` | 40 · 1.358 / 2.211 / 2.332 | 93 · 19.301 / 33.690 / 34.665 | 50 · 0.029 / 0.064 / 0.151 | 100 · 0.049 / 0.219 / 0.277 |
| `GET /treasury` | 40 · 0.034 / 0.124 / 0.163 | 93 · 1.398 / 4.626 / 5.174 | 50 · 0.039 / 0.067 / 0.072 | 100 · 0.046 / 0.203 / 0.431 |
| `POST /practice/tamper/restore` | 40 · 0.017 / 0.068 / 0.079 | 93 · 0.019 / 2.541 / 3.891 | 50 · 0.016 / 0.035 / 0.053 | 100 · 0.017 / 0.192 / 0.404 |
| `POST /approvals/{apr}/send-as-practice-teammate` | 40 · 0.036 / 0.170 / 0.252 | 93 · 1.696 / 6.724 / 7.103 | 50 · 0.030 / 0.045 / 0.062 | 100 · 0.041 / 0.187 / 0.307 |
| `POST /demo/step [bank_paid]` | 40 · 0.031 / 0.097 / 0.157 | 93 · 0.706 / 4.546 / 6.067 | 50 · 0.025 / 0.065 / 0.078 | 100 · 0.040 / 0.173 / 0.248 |
| `POST /demo/step [bank_sent]` | 40 · 0.035 / 0.118 / 0.166 | 93 · 1.729 / 5.696 / 7.483 | 50 · 0.025 / 0.059 / 0.067 | 100 · 0.042 / 0.161 / 0.281 |
| `GET /deposits` | 40 · 0.025 / 0.074 / 0.102 | 93 · 1.487 / 4.459 / 4.741 | 50 · 0.026 / 0.044 / 0.069 | 100 · 0.037 / 0.150 / 0.221 |
| `GET /invoices` | 40 · 0.023 / 0.062 / 0.073 | 93 · 1.703 / 4.456 / 4.756 | 50 · 0.024 / 0.042 / 0.066 | 100 · 0.034 / 0.124 / 0.177 |
| `GET /audit/verify` | 120 · 0.017 / 0.063 / 0.074 | 279 · 0.025 / 2.469 / 3.720 | 150 · 0.018 / 0.035 / 0.048 | 300 · 0.020 / 0.116 / 0.187 |
| `GET /audit` | 80 · 0.025 / 0.074 / 0.112 | 186 · 0.381 / 4.465 / 4.824 | 100 · 0.023 / 0.047 / 0.057 | 200 · 0.027 / 0.115 / 0.186 |
| `GET /practice/tamper` | 120 · 0.017 / 0.063 / 0.072 | 279 · 0.026 / 2.420 / 3.542 | 150 · 0.017 / 0.039 / 0.053 | 300 · 0.020 / 0.113 / 0.186 |
| `POST /practice/tamper` | 40 · 0.015 / 0.070 / 0.132 | 93 · 0.026 / 2.381 / 3.949 | 50 · 0.014 / 0.023 / 0.034 | 100 · 0.020 / 0.110 / 0.331 |
| `GET /deposits/{dep}` | 120 · 0.019 / 0.065 / 0.082 | 279 · 1.576 / 5.430 / 6.741 | 150 · 0.016 / 0.036 / 0.047 | 300 · 0.024 / 0.104 / 0.152 |
| `GET /setup` | 40 · 0.036 / 0.127 / 0.166 | 93 · 1.845 / 4.773 / 5.330 | 50 · 0.033 / 0.051 / 0.061 | 100 · 0.037 / 0.098 / 0.160 |
| `POST /approvals/{apr}/approve` | 40 · 0.016 / 0.056 / 0.073 | 93 · 1.239 / 5.822 / 7.416 | 50 · 0.014 / 0.032 / 0.047 | 100 · 0.016 / 0.083 / 0.144 |
| `GET /approvals` | 40 · 0.022 / 0.076 / 0.102 | 93 · 1.808 / 5.706 / 6.927 | 50 · 0.022 / 0.037 / 0.055 | 100 · 0.029 / 0.072 / 0.093 |
| `GET /operations` | 40 · 0.025 / 0.072 / 0.087 | 93 · 1.919 / 5.806 / 7.071 | 50 · 0.018 / 0.028 / 0.040 | 100 · 0.028 / 0.065 / 0.088 |
| `GET /customers` | 40 · 0.021 / 0.070 / 0.082 | 93 · 1.733 / 4.515 / 4.736 | 50 · 0.022 / 0.030 / 0.038 | 100 · 0.028 / 0.063 / 0.094 |
| `GET /status` | 200 · 0.021 / 0.079 / 0.112 | 465 · 1.772 / 4.743 / 6.741 | 250 · 0.018 / 0.035 / 0.053 | 500 · 0.023 / 0.061 / 0.091 |
| `GET /treasury/bill-payments` | 40 · 0.023 / 0.083 / 0.101 | 93 · 1.990 / 5.856 / 7.200 | 50 · 0.019 / 0.033 / 0.053 | 100 · 0.028 / 0.061 / 0.074 |
| `POST /deposits/{dep}/explanation` | 40 · 0.015 / 0.081 / 0.103 | 93 · 0.025 / 2.693 / 5.591 | 50 · 0.014 / 0.042 / 0.069 | 100 · 0.017 / 0.059 / 0.090 |
| `GET /deposits/{dep}/explanation` | 120 · 0.015 / 0.063 / 0.081 | 279 · 1.625 / 5.413 / 6.684 | 150 · 0.013 / 0.025 / 0.039 | 300 · 0.018 / 0.058 / 0.106 |
| `GET /demo` | 280 · 0.008 / 0.035 / 0.071 | 651 · 1.295 / 5.067 / 6.508 | 350 · 0.008 / 0.018 / 0.027 | 700 · 0.010 / 0.044 / 0.073 |
| `GET /deposits/{dep}/plans/{v}/replay` | 80 · 0.009 / 0.053 / 0.068 | 186 · 0.019 / 2.350 / 5.927 | 100 · 0.009 / 0.019 / 0.022 | 200 · 0.011 / 0.043 / 0.083 |
| `GET /auth/me` | 40 · 0.012 / 0.062 / 0.100 | 93 · 0.693 / 2.670 / 3.582 | 50 · 0.011 / 0.021 / 0.084 | 100 · 0.011 / 0.035 / 0.069 |

