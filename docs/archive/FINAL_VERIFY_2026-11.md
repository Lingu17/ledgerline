# Final verification of the 4 Nov fixes (5 Nov 2026)

- **Commit tested:** `main` at `b3ba221` ("Docs match the 5 Nov runs; keep the repository public until results are out"). `main` did not move during the session (checked at the start and again at the end).
- **Earlier reports re-tested:** `docs/archive/LOAD_TEST_2026-11.md` (branch `load-test-report`), `docs/archive/SECURITY_SCAN_2026-11.md` (`security-scan-report`) and `docs/archive/BROWSER_MATRIX_2026-11.md` (`browser-matrix-report`). All three were measured on `d22f232`.
- **Scope:** test and report only. No code was changed, nothing was deployed, and the live site was not touched. No Airwallex or Anthropic keys were used: everything ran on the simulated bank with the offline Claude fixture, on loopback only. This file is the only change on branch `final-verify-report`.

## Verdict

| Area | Result |
|---|---|
| Load | **FIXED.** 30, 50 and 100 judges all finished with **0 errors, 0 `database is locked` and 0 connection resets**. The slowest endpoint p95 was 0.25 s at 30 judges (was 1.67 s), 0.25 s at 50 (was 11.6 s) and 0.51 s at 100 (was 34 s, with 7 × 500). The 5-minute soak at 50 judges with the watcher on made 22,510 requests, all `200`, and had **no resets** (was 9). Memory peaked at 430 MB at 100 judges (was 1,932 MB). Every company had balanced books and a verified audit chain: 230/230. |
| Security | **M1 FIXED, L1 FIXED, I1 FIXED** (one gap with no impact, N2). The login burst is **FIXED**: exactly 5 attempts reach the password check and the rest get `429`. Cross-company isolation **held**. ZAP baseline: only the expected missing-CSP alert. **M2** (CSP) is still open for the two-tier topology only, which is not live (N3). |
| Phone | Of the 13 earlier issues: **7 FIXED**, **1 PARTLY FIXED**, **1 STILL OPEN**, **4 NOT TESTABLE** (they need Safari). The whole judge path passes on iPhone 14 and Pixel 7 emulation, and the repo's phone e2e subset passed 12/12. **WebKit is still not installable** here: the network policy returns 403 for `cdn.playwright.dev` and `playwright.download.prss.microsoft.com`. |
| New problems | 5 small ones (N1–N5) and 1 test gap (N6). None is above Low, and none blocks the judge path. |

## 1. Load

### Setup (same method as 4 Nov)

| Item | What was used |
|---|---|
| Server | `python -m ledgerline` from `backend/` (uvicorn, one process; its own defaults, now including `timeout_keep_alive=75`). Built frontend (`npm ci && npm run build`). Repository mounted read-only |
| Container | Docker 29.9.2, `--cpus=2 --memory=2g --memory-swap=2g`, `--network host`, cgroup v1. Image: `mirror.gcr.io/library/python:3.14-slim` plus `backend/requirements-lock.txt` |
| Environment | `LEDGERLINE_PROVIDER=local`, no `ANTHROPIC_API_KEY` (offline fixture), `LEDGERLINE_COOKIE_SECURE=0` (plain HTTP on loopback), `LEDGERLINE_TRUSTED_PROXY_HOPS` unset, a fresh empty `LEDGERLINE_DATA_DIR` per run. **`LEDGERLINE_PAYER_MCP_TRANSPORT` was not set**, so the production default `stdio` applies. Sign-up limits were raised to 100000 for the load runs, as before. `LEDGERLINE_WATCH_SECONDS=0` for the ramps and `120` (the production default) for the soak |
| Host | 4 vCPU and 16 GB cloud container. The load generator ran outside the container's 2-CPU limit |

**The judge script** follows the steps documented in the 4 Nov report. The original `load.py` lived in that session's scratch directory and no longer exists, so it was re-created (Python asyncio + httpx 0.28.1). It uses one cookie jar and CSRF token per judge, sends each screen's GETs in parallel, waits 0.5–2 s of think time between actions, and starts judges evenly over 60 s. Each judge:

1. Signs up a Practice company.
2. Opens Inbox, then Payments, then DEP-1005, then sends `ask-agent`.
3. Loops `GET /demo` and runs each `next` step. At the approve step it opens Approvals, approves with the scope hash, then sends `send-as-practice-teammate`, and continues to `bank_paid`.
4. Opens `/ledger` (the judge fails unless `all_balanced`) and `/ceo`.
5. Runs Why this plan, then Replay of every plan version.
6. Opens Activity, sends `POST /practice/tamper` (the judge fails unless verify reports the break), then restore (the judge fails unless the chain is OK again).

In the soak, a judge that has finished keeps opening random screens until 5 minutes are up.

The re-created script sends about 42 requests per walkthrough, against 51 in the original. The missing ones are extra re-fetches of `/status`, `/deposits/{dep}`, its explanation and `/practice/tamper`. The steps, the POSTs and their order are the same.

CPU and memory were sampled every second from the container's cgroup (`cpuacct.usage`, `memory.stat` `total_rss`, `memory.max_usage_in_bytes`, `pids.current`). After each run the server was stopped, and `ledger.conservation` and `audit.verify_chain` were run on every `orgs/*/ledgerline.sqlite3`.

### Results, compared with 4 Nov (`d22f232`)

| Run | Walkthroughs | Requests | Status counts | Slowest p95 (endpoint) | Overall p50 / p95 / p99 (s) | Peak CPU (of 200%) | Peak RSS / cgroup max | Books balance | Chain verifies |
|---|---|---|---|---|---|---|---|---|---|
| ramp 30, **now** | 30/30 | 1,260 | 200: 1,260 | 0.25 s (`POST /auth/signup`) | 0.014 / 0.042 / 0.164 | 45% | 200 MB / 215 MB | 30/30 | 30/30 |
| ramp 30, 4 Nov | 30/30 | 1,530 | 200: 1,530 | 1.67 s (`demo/step [agents]`) | 0.017 / 0.184 / 1.288 | 206% | 381 / 420 MB | 30/30 | 30/30 |
| ramp 50, **now** | 50/50 | 2,100 | 200: 2,100 | 0.25 s (`POST /auth/signup`) | 0.015 / 0.061 / 0.174 | 59% | 250 MB / 273 MB | 50/50 | 50/50 |
| ramp 50, 4 Nov | 50/50 | 2,550 | 200: 2,550 | 11.56 s (`demo/step [agents]`) | 0.075 / 0.769 / 8.313 | 207% | 990 / 1,068 MB | 50/50 | 50/50 |
| ramp 100, **now** | **100/100** | 4,200 | **200: 4,200** | 0.51 s (`POST /auth/signup`) | 0.019 / 0.130 / 0.319 | 188% | 388 MB / 430 MB | 100/100 | 100/100 |
| ramp 100, 4 Nov | 93/100 | 4,750 | 200: 4,743, **500: 7** | 33.69 s (`ask-agent`) | 1.090 / 6.834 / 23.604 | 206% | 1,821 / **1,932 MB** | 93/93 | 93/93 |
| soak 50, 5 min, watcher 120 s, **now** | 50/50 | 22,510 | **200: 22,510** | 1.38 s (`GET /ceo`, browsing) | 0.047 / 0.617 / 1.113 | 198% | 308 MB / 334 MB | 50/50 | 50/50 |
| soak 50, 4 Nov | 50/50 | 21,900 | 200: 21,891, **conn reset: 9** | 11.03 s (`ask-agent`) | 0.088 / 0.847 / 1.574 | 206% | 870 / 912 MB | 50/50 | 50/50 |

- **`database is locked`:** 0 in every run. The server logs have 0 `ERROR` lines and 0 tracebacks. Before, there were 7 × 500 at 100 judges. Sign-up p95 at 100 judges is 0.51 s, down from 13.1 s.
- **Connection resets:** 0 in all 29,570 requests. Before, there were 9 in the soak.
- **Payer agents:** every answer stored in the measured runs has transport `mcp/in-memory`: 300 evidence rows across the 100 companies of ramp 100, and 150 in the soak. No `mcp/stdio` subprocess was used for practice companies (`backend/ledgerline/payer_agents/client.py:96`). `ask-agent` p95 is now 0.06–0.24 s, down from 1.6–34 s.
- **Process and thread count:** the cgroup's `pids.current` peaked at 46 in the soak. That counts threads (uvicorn plus the 40-thread worker pool), not payer-agent processes.
- **CPU:** at 30 and 50 judges both CPUs were never saturated. At 100 judges, and in the soak's browsing phase (about 75 requests/s, much faster than people click), CPU reaches 190–200%. In the soak's browse phase, `/ceo` (1.38 s p95), `/overview` (1.13 s) and `/treasury` (0.96 s) are the heaviest reads. That is the same picture as problem 6 of the 4 Nov report, a little better than then (1.7 / 1.5 / 1.2 s).
- **Disk:** unchanged at 356,748 bytes per practice company. `control.sqlite3` was 172 KB after the soak.

### p95 per endpoint (seconds)

Sorted by p95 in the 100-judge run. For n, p50 and p99 see the method above. The 4 Nov values are in that report.

| Endpoint | ramp 30 | ramp 50 | ramp 100 | soak 50 |
|---|---|---|---|---|
| `POST /auth/signup` | 0.253 | 0.253 | 0.508 | 0.368 |
| `POST /demo/step [treasury]` | 0.045 | 0.084 | 0.324 | 0.188 |
| `GET /overview` | 0.065 | 0.098 | 0.322 | 1.130 |
| `GET /treasury` | 0.043 | 0.070 | 0.294 | 0.957 |
| `POST /demo/step [bank_sent]` | 0.040 | 0.050 | 0.228 | 0.315 |
| `POST /demo/step [agents]` | 0.124 | 0.092 | 0.215 | 0.210 |
| `POST /approvals/{apr}/send-as-practice-teammate` | 0.041 | 0.062 | 0.150 | 0.196 |
| `POST /practice/tamper` | 0.016 | 0.022 | 0.135 | 0.299 |
| `POST /deposits/{dep}/ask-agent` | 0.059 | 0.075 | 0.128 | 0.238 |
| `GET /ceo` | 0.027 | 0.058 | 0.120 | 1.382 |
| `GET /deposits` | 0.024 | 0.039 | 0.111 | 0.501 |
| `GET /setup` | 0.036 | 0.048 | 0.095 | 0.232 |
| `GET /ledger` | 0.027 | 0.019 | 0.094 | 0.873 |
| `POST /demo/step [bank_paid]` | 0.037 | 0.054 | 0.093 | 0.475 |
| `GET /invoices` | 0.024 | 0.034 | 0.092 | 0.411 |
| `GET /audit` | 0.030 | 0.036 | 0.067 | 0.359 |
| `POST /practice/tamper/restore` | 0.027 | 0.024 | 0.064 | 0.391 |
| `GET /practice/tamper` | 0.024 | 0.033 | 0.063 | 0.414 |
| `GET /deposits/{dep}` | 0.017 | 0.026 | 0.056 | 0.300 |
| `POST /deposits/{dep}/explanation` | 0.018 | 0.020 | 0.051 | 0.079 |
| `POST /approvals/{apr}/approve` | 0.019 | 0.026 | 0.051 | 0.065 |
| `GET /audit/verify` | 0.019 | 0.027 | 0.051 | 0.402 |
| `GET /customers` | 0.019 | 0.026 | 0.048 | 0.180 |
| `GET /status` | 0.029 | 0.033 | 0.048 | 0.140 |
| `GET /operations` | 0.016 | 0.023 | 0.035 | 0.169 |
| `GET /approvals` | 0.028 | 0.028 | 0.034 | 0.145 |
| `GET /deposits/{dep}/explanation` | 0.017 | 0.017 | 0.033 | 0.112 |
| `GET /deposits/{dep}/plans/{v}/replay` | 0.009 | 0.012 | 0.032 | 0.102 |
| `GET /auth/me` | 0.025 | 0.023 | 0.031 | 0.023 |
| `GET /treasury/bill-payments` | 0.021 | 0.022 | 0.031 | 0.106 |
| `GET /demo` | 0.013 | 0.017 | 0.027 | 0.042 |

### Not covered by the load runs

- **Real (non-practice) companies still use `stdio`.** They are capped at 3 concurrent payer-agent processes by `_STDIO_SLOTS` (`backend/ledgerline/payer_agents/client.py:50`). Judges only use practice companies, so that path was not load-tested.
- **No Caddy or TLS in the loop**, as on 4 Nov. The 75 s keep-alive fix was confirmed directly against uvicorn. The Caddy→uvicorn interaction was not exercised.
- **Best case.** `--cpus=2` is the best case for a shared-core e2-small.

## 2. Security re-test (local copy only)

The server ran from the host venv on `127.0.0.1:81xx`, with a fresh data directory per configuration, the simulated bank and no keys.

### M1: `X-Forwarded-For` spoofing: **FIXED**

Each configuration was tested with the request **as it reaches the app** when an attacker sends forged `X-Forwarded-For` entries:
- Hops 0: straight to uvicorn, nothing appended.
- Hops 1 and 2: through our own Caddy, which appends the attacker's real address (`198.51.100.7`).

The sign-up limit is the default 10 per address per hour. 14 sign-ups each carried a different forged address. The sign-in spray was 12 wrong passwords for 12 different emails, each with a different forged address.

| Config | `/api/health` client with forged `6.6.6.6, 7.7.7.7` | Same with a wrong `X-Ledgerline-Edge` | Sign-ups, rotating XFF | Sign-in spray, rotating XFF | Before (4 Nov) |
|---|---|---|---|---|---|
| hops 0, no edge secret | 127.0.0.1 | – | **10 × 200, 4 × 429** | **5 × 401, 7 × 429** | held |
| hops 0, edge secret | 127.0.0.1 | 127.0.0.1 | 10 × 200, 4 × 429 | 5 × 401, 7 × 429 | – |
| hops 1, no edge secret | 198.51.100.7 (real) | – | 10 × 200, 4 × 429 | 5 × 401, 7 × 429 | – |
| hops 1, edge secret | 198.51.100.7 | 198.51.100.7 | 10 × 200, 4 × 429 | 5 × 401, 7 × 429 | – |
| **hops 2, no edge secret** (the old M1 setup) | **198.51.100.7** (was the forged `7.7.7.7`) | – | **10 × 200, 4 × 429** (was 14/14 accepted) | **5 × 401, 7 × 429** | **bypassed** |
| hops 2, edge secret | 198.51.100.7 | 198.51.100.7 | 10 × 200, 4 × 429 | 5 × 401, 7 × 429 | – |

- **Hops 2 with the edge secret, from the real edge:** with the correct secret, the browser address the edge recorded is still used (`198.51.100.50`). So the fix does not break the two-tier topology when it is configured as documented.
- **How it works now:** `client_ip` (`backend/ledgerline/api/security.py:59-82`) caps trust at 1 hop when there is no edge secret. Without the secret header it falls back to the entry our own proxy appended.

### Login burst for one email: **FIXED**

Parallel wrong-password logins for one existing account, all sent at the same moment, with default settings:

| Burst | 401 (reached the password check) | 429 | `login_failures` rows afterwards | Correct password right after |
|---|---|---|---|---|
| 20 | **5** | 15 | `email:` 5, `ip:` 5 | 429 (locked out for the window, as designed) |
| 50 | **5** | 45 | `email:` 5, `ip:` 5 | 429 |

Each attempt reserves its failure row in one short `BEGIN IMMEDIATE` before scrypt runs (`backend/ledgerline/control.py:284-310`), so a burst cannot get more than 5 guesses in.

### L1: missing file-like paths: **FIXED**

| Path | Status | Body |
|---|---|---|
| `/robots.txt` | **200** | `text/plain` (`User-agent: *` …) |
| `/.hg`, `/.bzr`, `/._darcs`, `/.env`, `/x.php`, `/wp-login.php`, `/sitemap.xml` | **404** | `not found` (was 200 + SPA shell) |
| `/assets/nope.js` | 404 | JSON from the static mount |
| `/api/nope` | 404 | JSON |
| `/favicon.svg` | 200 | the file |
| `/payments`, `/nonexistent`, `/BitKeeper`, `/.git/config` | 200 | SPA shell (no dot in the last segment, so it is treated as an app route). No disclosure. See the note below |
| `/../../../../etc/passwd`, `/%2e%2e/%2e%2e/etc/passwd` (`curl --path-as-is`) | 200 | SPA shell, no file content |
| `/assets/..%2f..%2f..%2f..%2fetc%2fpasswd` | 404 | – |

Note on `/.git/config`: it still returns `200` with the app shell, because the rule in `backend/ledgerline/api/app.py:226` looks only at the last path segment. This is not a disclosure, but a scanner will still list it. Optional: also 404 any path with a segment that starts with a dot.

### I1: numeric host encodings at payer-agent registration: **FIXED** (one gap, N2)

Each URL was sent with `PUT /api/customers/CUST-ACME/payer-agent` as the owner of a practice company, with a valid Ed25519 public key.

| Host | Result |
|---|---|
| `2130706433`, `0177.0.0.1`, `0x7f.0.0.1`, `0x7f000001`, `127.1`, `017700000001`, `0251.0376.0251.0376`, `2852039166`, `0xa9.0xfe.0xa9.0xfe` | **422** "agent URL must use a host name or a plain dotted IP address" (were accepted on 4 Nov) |
| `127.0.0.1`, `[::1]`, `169.254.169.254` | 422 "points to a non-public address" (unchanged) |
| `agent.example.com` | 200 (a public name is accepted) |
| `2130706433.`, `0x7f.1.` (trailing dot) | **200: accepted.** See N2. They do not resolve (glibc `getaddrinfo` returns "Name or service not known"), and `ask_remote` fails with `AgentUnreachable`, so nothing is called |

### ZAP baseline

ZAP 2.16.1 in daemon mode ran a spider plus passive scan, unauthenticated, of `http://127.0.0.1:8120/`. The seed URLs were `/`, `/robots.txt`, `/sitemap.xml`, `/api/openapi.json`, `/.hg` and `/x.php`.

- **Medium:** `Content Security Policy (CSP) Header Not Set` on `/`. This is expected: the app itself sends no CSP, and on the live single-host server it comes from `deploy/vm/Caddyfile.single:10-11`. See N3.
- **Informational:** "Modern Web Application" and "Suspicious Comments" (the word `select` in the minified bundle). Both are noise.
- **Gone since 4 Nov:** the four `Hidden File Found` alerts (`.hg`, `.bzr`, `BitKeeper`, `._darcs`). Those were the L1 false positives.

### Cross-company isolation: **held**

Company A was a Practice company and company B a real one, each with its own owner. B's owner session was replayed against A's resources:

| Check | Result |
|---|---|
| `GET /deposits/DEP-1001..1006` | 404 × 6 |
| `GET /deposits/{A's}/plans/1/replay` | 404 × 6 |
| `POST /deposits/{A's}/ask-agent` | 409 × 6 (B has no such deposit) |
| `PUT /customers/{A's CUST-ACME, BRIGHTWAVE, CALDER}/payer-agent` | 422 × 3 ("unknown customer") |
| `POST /auth/switch-organization` to A's id | 403 |
| `GET /team` as B | only B's owner |
| `GET /export/csv` as B (new since 4 Nov) | no A data in the zip |
| `GET /audit/export` as B | no A data |
| `POST /practice/tamper` as B (real company) | 403 |
| `POST /demo/step` as B | 409 |
| Webhook to A's org with no signature | 401 |
| A's POST without a CSRF token | 403 |
| A's POST with a foreign `Origin` | 403 |
| An attacker-chosen session cookie | 401 |

### Earlier findings, status

| ID | Status | Evidence |
|---|---|---|
| M1 | **FIXED** | XFF table above |
| M2 | **STILL OPEN, two-tier topology only** (not live) | The app sends no CSP or Permissions-Policy. Only `Caddyfile.single` adds them. `deploy/vm/Caddyfile` (two-tier) still does not, and `docs/DEPLOYMENT.md:88` now tells anyone using that shape to add them at the edge. See N3 |
| L1 | **FIXED** | 404s above. `/.git/config` is a cosmetic leftover |
| I1 | **FIXED** | 422s above. Trailing-dot gap: N2 |
| I2 | Not re-run | Static analysis was out of scope for this pass |
| Login burst | **FIXED** | Exactly 5 attempts reach the password check |

## 3. Phone

### How it was run

- **Engine:** Chromium 153 from `/opt/pw-browsers/chromium`, with Playwright's `iPhone 14` (390×664 visible, DPR 3, touch, Safari UA) and `Pixel 7` (412×839, DPR 2.625, touch) descriptors, applied to the whole browser context.
- **Hand walk:** a script, touch only (`tap()`), against a local server with the simulated bank. It covered:
  1. Practice sign-up.
  2. Payments, then DEP-1005, then Ask payer's agent (reaching Verified), then Replay this decision ("Same plan…"), then Why this plan.
  3. The four practice steps, then Approvals: Approve, Approve this scope, Send as practice teammate. Then Bank SENT and PAID: **8/8 steps done on both devices**.
  4. Treasury and Treasury Replay.
  5. Show me, stops 1–7.
  6. Try to tamper ("Caught at event 34."), then Restore, then Verify ("Log intact.").
  7. The evidence download (`ledgerline-evidence-export.json`).
  8. Activity.

  It measured page sideways scroll, input font sizes, controls under 44 px, the sidebar's `inert` and whether its links can take focus, the tour panel position, toasts overlapping the panel, and the drawer content under the panel. No console errors on either device.
- **Repo suite, phone subset:** the same grep as on 4 Nov (`phone width|show me|practice walkthrough|privacy, terms`) from a temporary config outside the repository. Pixel 7: **6/6**. iPhone 14 on Chromium: **6/6**.
- **WebKit: still not installable.** `npx playwright install webkit` gives `403 request blocked: no rule or allowlist entry allows host "cdn.playwright.dev"`, and the same for the fallback host `playwright.download.prss.microsoft.com`. So the WebKit desktop suite and iPhone 14 on WebKit could not be run. To fix this, an admin can add those two hosts under the environment's Network access → Allowed domains. Alternatively, run `npx playwright install --with-deps webkit` on a Mac or in CI.

### The 13 earlier issues

| # | Issue (4 Nov) | Status | Evidence on `b3ba221` |
|---|---|---|---|
| 1 | Inputs at 14 px make iOS zoom on focus | **FIXED** | Every visible input and select measured **16 px** on sign-up, Payments filters, Activity search and in the tour, on both devices (`frontend/src/styles.css:382`) |
| 2 | Show me panel covers the bottom of the DEP-1005 drawer | **FIXED** | While the tour is open, `.content` and `.drawer-body` get `padding-bottom: 240px` (`styles.css:386`). With the drawer scrolled to the end at the "A suspected duplicate" stop, the last item ends above the panel (panel top 441 of 664 on iPhone, 616 of 839 on Pixel) |
| 3 | Toasts cover the Show me panel | **FIXED** | With the tour open, toasts move to `top: 12px` (`styles.css:387`). At no tour stop did a toast overlap the panel |
| 4 | Treasury Pay, Mark paid, Replay and the Credits column off screen | **PARTLY FIXED** | "What to pay first" and "Plan history" are now `stack-sm` cards, so Pay, Mark paid and Replay are on screen, and Treasury Replay was tapped successfully. Wallet position still scrolls sideways but now says "Swipe the table sideways to see every column." **Bills** (`Treasury.tsx:97`) and **Conversions** (`Treasury.tsx:147`) still scroll sideways with no hint. See N5 |
| 5 | Tap targets under 44 px | **FIXED** (as suggested) | `.btn` is now **44 px** and `.btn.small` **36 px** under `pointer: coarse` (`styles.css:383`), as the 4 Nov fix suggested. What is still under 44 px: `.btn.small` (Help, Show me, tour Back, Next and Close, at 36 px) and the toast's **× Dismiss at 21 px** (N4) |
| 6 | The hidden mobile menu can still be focused | **FIXED** | The closed sidebar has `inert` on every page (`App.tsx:184`), and 0 of its links can take focus. When open, `inert` is removed |
| 7 | "Copy message" gives no confirmation | **FIXED** | It now shows a "Message copied" toast, and the clipboard held the balance-request email (DEP-1003, both devices). The Team "Copy" also shows a toast now (`Team.tsx:163`). Safari's refusal path is not testable here |
| 8 | Menu footer under Safari's toolbar (`100vh`) | **FIXED in code; Safari NOT TESTABLE** | `.sidebar { height: 100dvh }` (`styles.css:59`), and the open sidebar measured exactly the visible height (664 and 839 px). On iPhone 14 the footer (Sign out) sits below the fold *inside* the sidebar, because there are more links than fit, but the sidebar scrolls (`overflow-y: auto`), so it is reachable. Still on `100vh`: `.modal { max-height: calc(100vh - 48px) }` (`styles.css:211`). The Approve dialog (169–495 of 664) fits anyway |
| 9 | Evidence download may fail on Safari | **NOT TESTABLE** (code unchanged) | It works on Chromium under both descriptors. `api.ts:96-97` still clicks a detached anchor and revokes the URL in the same tick |
| 10 | Dialog focus can escape on macOS Safari | **NOT TESTABLE** (code unchanged) | `components/ui.tsx:174-183` still wraps only when `activeElement === last` |
| 11 | Page behind the drawer scrolls on iOS before 16 | **NOT TESTABLE** (code unchanged) | `ui.tsx:198-202` still only sets `body.style.overflow` |
| 12 | Date-time separator may differ | **NOT TESTABLE** | Format changed to local time with a zone (`format.ts:36`). Chromium renders `05 Nov, 03:23 UTC`. It still uses `Intl.DateTimeFormat` without `formatToParts`, so WebKit's separator is unverified |
| 13 | Hover colours stick after a tap | **STILL OPEN** (measured on Chromium touch emulation) | After tapping "Copy message" the button still matches `:hover` and keeps the hover background (`rgb(250,251,252)` vs `rgb(255,255,255)`). `.btn:hover`, `tr.clickable:hover` and `.nav a:hover` (`styles.css:72, 113, 156`) are still not inside `@media (hover: hover)` |

Totals: **FIXED 7** (1, 2, 3, 5, 6, 7, 8), **PARTLY FIXED 1** (4), **STILL OPEN 1** (13), **NOT TESTABLE 4** (9, 10, 11, 12).

The judge path has no page-level sideways scroll at any of the 19 measured stops on either device.

## 4. New problems

None of these blocks the judge path.

### N1. Settings shows `mcp/stdio` for a practice company whose answers are now `mcp/in-memory` (Low, judge-facing accuracy)

- **Steps:**
  1. Sign up a Practice company.
  2. Ask DEP-1005's payer agent. The stored evidence says `transport: mcp/in-memory`.
  3. Open Settings, or `GET /api/status`. It says `payer_agents.transport: "mcp/stdio"`, labelled "Customer agents hosted on this server, real MCP protocol".
- **Why:** `backend/ledgerline/api/routes.py:68` reports the server setting (`payer_mcp_transport`), but since `b3ba221` practice companies always use `memory` (`backend/ledgerline/payer_agents/client.py:96`). It is shown at `frontend/src/views/Settings.tsx:199`. `docs/HACKATHON_REQUIREMENTS_MATRIX.md:33` also still says "Real stdio MCP" for B5. A judge who compares the Settings line with the evidence row sees two different answers.
- **Suggested fix:** in `/status`, report `mcp/in-memory` when `ctx.org.kind == "sample"` (the same rule as `client.py:96`). Update the matrix line to say practice companies use in-process MCP and real companies use stdio.

### N2. Trailing-dot numeric hosts pass payer-agent registration (Informational)

- **Steps:** as an owner, `PUT /api/customers/CUST-ACME/payer-agent` with `{"url": "https://2130706433./mcp", "public_key": <valid>}` returns `200`. So does `https://0x7f.1./`.
- **Why:** `backend/ledgerline/payer_agents/remote.py:76` splits on `.`, and the empty last label fails `fullmatch`, so the whole check is skipped.
- **Impact:** none found. glibc does not resolve these names, so `ask_remote` returns `AgentUnreachable` and nothing is called. The connect-time guard would refuse a loopback answer anyway.
- **Suggested fix:** `host = host.rstrip(".")` before the numeric check (and before the `localhost` comparison two lines later).

### N3. Docs say the app sends its own CSP; it does not (Low, documentation; M2 remains for the two-tier shape)

- **Steps:** `curl -si http://127.0.0.1:8000/ | grep -i -E 'content-security|permissions-policy'` returns nothing. ZAP reports "CSP Header Not Set" on `/`.
- **Why:** `docs/DEPLOYMENT.md:88` says the edge must "send the same Content-Security-Policy and Permissions-Policy headers from the edge that the app sends itself". But the app's header middleware (`backend/ledgerline/api/app.py:110-116`) sets only `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and `Cache-Control`. The live single-host server is covered by `deploy/vm/Caddyfile.single:10-11`, so this affects only a two-tier or non-Caddy deployment.
- **Suggested fix:** either set the same CSP and Permissions-Policy in the app middleware at `app.py:114` (then any topology is covered), or change the doc to say "that `Caddyfile.single` sends".

### N4. The toast's × Dismiss button is 21 px tall (Low, phone)

- **Steps:** on iPhone 14 or Pixel 7 emulation, trigger any toast (for example Copy message). Its × is 21 px tall and about 10 px wide.
- **Where:** `frontend/src/components/ui.tsx:70`, styled at `frontend/src/styles.css:269` (`.toast button`).
- **Suggested fix:** `.toast button { min-width: 44px; min-height: 44px; }` under `@media (pointer: coarse)`.

### N5. Bills and Conversions tables on Treasury still scroll sideways with no hint (Low, phone)

- **Steps:** at 390 px, open Treasury. The Status column of Bills and the Bought column of Conversions are past the right edge of their cards.
- **Where:** `frontend/src/views/Treasury.tsx:97` and `:147`. Wallet position (`:54`) already has a swipe hint.
- **Suggested fix:** `className="stack-sm"` on both tables, as for "What to pay first" (`:394`), or the same "Swipe the table sideways" hint.

### N6. Test gap still open: phone tests drop the device settings

- **Where:** `frontend/e2e/saas.spec.ts:150, 321, 359, 552` still create `browser.newContext({ viewport: { width: 375, height: 812 } })`, so the Pixel and iPhone projects lose touch, mobile UA and DPR in those tests. This is unchanged since 4 Nov.
- **Suggested fix:** `browser.newContext({ ...test.info().project.use, viewport: { width: 375, height: 812 } })`, or `test.use({ ...devices["iPhone 14"] })` in a phone `describe`.

## How to re-run

The scripts were kept outside the repository, as before:
- `load.py` (judge script), `run.sh` (container plus monitor plus verify), `monitor.sh`, `verify.py` and `analyze.py`.
- `sec_m1.py` (XFF matrix and login burst) and `sec_misc.py` (L1, I1, isolation).
- `walk/walk.mjs` and `walk/extra.mjs` (phone walk).

Their logic is fully described above. Commands, from the repository root, with `requirements-lock.txt` installed:

- Load: `docker run --cpus=2 --memory=2g --memory-swap=2g --network host -v $PWD:/app:ro -v <empty dir>:/data -w /app/backend -e LEDGERLINE_DATA_DIR=/data -e LEDGERLINE_PROVIDER=local -e LEDGERLINE_COOKIE_SECURE=0 -e LEDGERLINE_SIGNUP_PER_IP_HOUR=100000 -e LEDGERLINE_SIGNUP_PER_IP_DAY=100000 -e LEDGERLINE_SIGNUP_PER_DAY=100000 -e LEDGERLINE_WATCH_SECONDS=0 <image> python -m ledgerline`. Use `LEDGERLINE_WATCH_SECONDS=120` for the soak.
- Phone suite: a config outside the repository that imports `frontend/playwright.config.ts` and defines the `Pixel 7` and `iPhone 14` projects with the grep above.
