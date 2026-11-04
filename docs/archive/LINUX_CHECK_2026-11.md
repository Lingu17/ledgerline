# Linux check, November 2026 (commit 1668374)

Run on 2026-11-04 in a throwaway Linux container. Nothing in the application was changed. No live server was contacted.
Every result below comes from a command that was run here. Anything not run is listed at the end.

**Environment:** Ubuntu 24.04.5 LTS, kernel 6.18.44, x86_64, running as root (needed for `useradd`/`chown`). Python 3.13.18
(`/usr/local/bin/python3.13`), plus Python 3.14.6 (via `uv python install 3.14`) to match CI's postgres job. pytest 9.1.1,
psycopg 3.3.6, fastapi 0.162.0, cryptography 50.0.2 (all from `requirements-lock.txt`). PostgreSQL 17.11 (Docker image
`postgres:17`). Node v22.23.4, `@playwright/test` 1.64.1, Chrome for Testing 153.0.8010.12. bash 5.2.21, sudo 1.9.15p5.
No systemd (PID 1 is not systemd), so `systemctl`, `systemd-run` and `curl` were stubbed for check 4 only.

## Summary

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Backend, SQLite, Python 3.13, Linux | **PASS**: 550 passed, 9 skipped, 0 failed | All 9 skips are `test_postgres.py` DB tests (no `LEDGERLINE_TEST_DATABASE_URL`). The Unix-socket sender test **ran and passed**. |
| 2a | `tests/test_postgres.py` on PostgreSQL 17 | **PASS**: 13/13 (Py 3.13), 13/13 (Py 3.14) | |
| 2b | Whole suite on PostgreSQL 17, Py 3.14, CI's exact env | **FAIL**: 546 passed, 9 skipped, **4 failed** | All 4 are in `test_sender.py` and come from a test-fixture bug (Bug 3), not an app bug. With the fixture fixed, all 10 sender tests pass on PG. |
| 2c | Whole suite on PostgreSQL 17, Py 3.13, task's env (explicit `LEDGERLINE_DATABASE_URL`, random `LEDGERLINE_SECRET_KEY`) | 545 passed, 9 skipped, 4 failed, 1 error | Same 4 failures. The 1 error was caused by this check: `npm run build` emptied `frontend/dist` while the test ran. Rerun: passes. |
| 3 | Sender over a real Unix socket with SO_PEERCRED, 4 real users | **PASS** | Allowed uid gets an answer. Another uid in the socket's group is refused (closed with 0 bytes, warning logged). A uid outside the group gets EACCES. Socket mode is `0660`. |
| 4a | `harden.sh sender` (real users, files, sudo; real sender process) | **PASS** | All the requested post-conditions hold (details below). |
| 4b | ERR trap: failure forced at `systemctl enable --now ledgerline-send` (and at `daemon-reload`) | **PASS, with caveats** | Keys, key file, modes, socket line and unit are restored. Not byte-exact: key lines move to the end of the env file, and an empty `/var/lib/ledgerline-send` is left (Bug 4). |
| 4c | `harden.sh sender-off` run twice | **PASS** | No duplicate key lines. Key back at `600 ledgerline:ledgerline` with the same hash. The second run changes nothing. |
| 4d | `sender-off` after the sender left a file in the data dir | **FAIL** (Bug 1) | A crashed sender's hot `-journal`, owned by `ledgerline-send`, is chmodded 600. After that the app gets `unable to open database file` for that company. Fix verified. |
| 4e | `harden.sh files` while the sender is on | **FAIL** (Bug 2) | Locks the sender out of every company database, and its own checks still say "done". Guard verified. |
| 4f | `update.sh` sender guard | **PASS** | All 4 cases behave correctly: REF without `sender.py` refused and rolled back with no restart; running commit without `sender.py` refused up front; sender off allows the old REF; sender on and new REF restarts the sender first. |
| 5 | Browser suite (Chromium on Linux) | **PASS**: 27 passed, 2 skipped, 0 failed | The 2 skips are opt-in recorders (`DEMO_DIR`, `SCREENSHOTS`). `playwright install` was blocked by the network, so the pre-installed Chromium was used (details below). |
| 6 | `accuracy_run.py --seeds 50 --walkthroughs 5` | **PASS** | `Result: PASS · 14,849 individual checks · 2,127 payments · 1,006 invoices`, 89 s |

**Before step 7 (turning the sender on in production):** Bug 1 and Bug 2 are in the scripts the owner will run, so fix
them first. Bug 3 turns the CI postgres job red as soon as Actions runs again. It also hides real PG coverage of the
sender. Nothing found blocks the sender's core security behaviour on Linux: SO_PEERCRED, the 0660 socket, the
root-only `sender.env` and the unreadable moved key all worked with real users.

---

## 1. Backend on Linux, SQLite

```bash
cd backend && python3.13 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-lock.txt
.venv/bin/python -m pytest -q -rfEs -p no:cacheprovider
```

(`-rfEs` instead of `-rfE`, so that skips are listed too. `-p no:cacheprovider` only avoids writing `.pytest_cache`.)
The install succeeded with hashes (pip 26.2.2). No `LEDGERLINE_*` variables were set in the environment.

Result: **550 passed, 9 skipped, 0 failed in 123.48 s.**

Skips (all 9):

```
SKIPPED tests/test_postgres.py:65   LEDGERLINE_TEST_DATABASE_URL not set
SKIPPED tests/test_postgres.py:107  LEDGERLINE_TEST_DATABASE_URL not set
SKIPPED tests/test_postgres.py:133  LEDGERLINE_TEST_DATABASE_URL not set
SKIPPED tests/test_postgres.py:169  LEDGERLINE_TEST_DATABASE_URL not set
SKIPPED tests/test_postgres.py:199  LEDGERLINE_TEST_DATABASE_URL not set
SKIPPED tests/test_postgres.py:208  LEDGERLINE_TEST_DATABASE_URL not set
SKIPPED tests/test_postgres.py:234  LEDGERLINE_TEST_DATABASE_URL not set
SKIPPED tests/test_postgres.py:257  LEDGERLINE_TEST_DATABASE_URL not set
SKIPPED tests/test_postgres.py:291  LEDGERLINE_TEST_DATABASE_URL not set
```

The Unix-socket test ran, as confirmed separately:

```bash
.venv/bin/python -m pytest -v -p no:cacheprovider tests/test_sender.py
# tests/test_sender.py::test_over_a_unix_socket_only_the_owner_and_group_can_connect PASSED
# 10 passed in 5.03s
```

## 2. Backend on PostgreSQL 17

```bash
dockerd &                                   # the container had Docker but no running daemon
docker run -d --name pg17 -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:17
docker exec pg17 psql -U postgres -tAc "select version()"
#   PostgreSQL 17.11 (Debian 17.11-1.pgdg13+2) on x86_64-pc-linux-gnu
docker exec pg17 psql -U postgres -c "create database ledgerline_test"
```

The CI postgres job does **not** set `LEDGERLINE_DATABASE_URL` or `LEDGERLINE_SECRET_KEY` directly. It sets
`LEDGERLINE_TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres` and, for the whole-suite step,
`LEDGERLINE_TEST_ALL_ON_POSTGRES=1`. `tests/conftest.py` then copies the URL into `LEDGERLINE_DATABASE_URL`, sets
`LEDGERLINE_PG_SCHEMA_PREFIX=auto` and a default test `LEDGERLINE_SECRET_KEY`. CI uses Python 3.14. I ran it both ways.

### 2a. PostgreSQL-specific tests

```bash
LEDGERLINE_TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ledgerline_test \
  .venv/bin/python -m pytest -v -rfEs -p no:cacheprovider tests/test_postgres.py          # 13 passed in 22.21s (Py 3.13)
LEDGERLINE_TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres \
  /tmp/llcheck/venv314/bin/python -m pytest -v -rfEs -p no:cacheprovider tests/test_postgres.py   # 13 passed in 23.22s (Py 3.14)
```

All 13 passed both times: translation, pooler refusal, schema names, key binding, concurrent schema hardening,
end-to-end walkthrough and restart, tenant schemas and privileges, concurrent refund (money moves once), random
companies against the reference model, duplicate webhooks, concurrent FX, rollback and pool recovery, and the stdio
MCP signing identity across a restart.

### 2b. Whole suite, CI's exact environment, Python 3.14

```bash
/root/.local/share/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14 -m venv /tmp/llcheck/venv314
/tmp/llcheck/venv314/bin/pip install -q --require-hashes -r requirements-lock.txt      # OK on 3.14
LEDGERLINE_TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres LEDGERLINE_TEST_ALL_ON_POSTGRES=1 \
  /tmp/llcheck/venv314/bin/python -m pytest -q -rfEs -p no:cacheprovider tests
```

Result: **546 passed, 9 skipped, 4 failed in 385.62 s.**

- The 9 skips are all `tests/test_backup.py` (lines 43, 51, 61, 85, 92, 98, 107, 128, 164): "SQLite backup; this run
  stores data in PostgreSQL". That is expected.
- The 4 failures, each `KeyError: 'unknown organization'` raised at `ledgerline/sender.py:145` (in `SenderClient.call`,
  re-raising the service's reply):
  - `test_sender.py::test_the_app_holds_no_keys_and_cannot_unseal_or_send_by_itself`
  - `test_sender.py::test_money_out_is_asked_for_by_id_and_runs_inside_the_service`
  - `test_sender.py::test_errors_keep_their_type_across_the_socket`
  - `test_sender.py::test_a_company_not_connected_to_airwallex_never_reaches_the_service`

  Traceback summary: the `pair` fixture signs up a company through the app. The app sends `connect` and `seal` to the
  sender, which works because `seal` doesn't need the control plane. The next call that looks up the organization in
  the sender's `ControlPlane` fails. Cause: `LEDGERLINE_PG_SCHEMA_PREFIX=auto` gives **every** `load_settings()` call a
  fresh random schema prefix (`config.py:239-245`). The fixture builds `keys` and `app_settings` separately, so the
  sender and the app use different control-plane schemas. In production both read the same prefix (default `ll`), so
  this is a test bug, not an app bug (see Bug 3). Verified: a scratch copy of `test_sender.py` that passes
  `LEDGERLINE_PG_SCHEMA_PREFIX=keys.pg_schema_prefix` to the app settings passed all 10 tests on PostgreSQL. The copy
  was deleted afterwards.

`scripts/ci_annotate.py` exits 1 when a test failed, so the CI postgres job **will be red** on these 4 once Actions runs.

### 2c. Whole suite, task's environment, Python 3.13

```bash
export LEDGERLINE_TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ledgerline_test \
       LEDGERLINE_TEST_ALL_ON_POSTGRES=1 \
       LEDGERLINE_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ledgerline_test \
       LEDGERLINE_SECRET_KEY=<43 random base64 chars from /dev/urandom>
.venv/bin/python -m pytest -q -rfEs -p no:cacheprovider --junitxml=pg-report.xml
```

Result: 545 passed, 9 skipped, 4 failed, 1 error in 375.57 s. The 4 failures are the same as in 2b. The error was in
`test_two_person.py::test_a_different_operator_can_send_it` at setup: `RuntimeError: Directory
'/home/user/ledgerline/frontend/dist/assets' does not exist`. It happened because I ran `npm ci && npm run build` for
check 5 at the same time, and vite empties `dist/` while it builds. `test_two_person.py` (14 tests) passed when rerun
on PostgreSQL afterwards, and 2b (run with a complete `dist/`) has no error. So this error is not a project bug.

## 3. Sender over a real Unix socket with SO_PEERCRED

Users (created with `useradd`):

| user | uid | groups | role |
|------|-----|--------|------|
| `llsend` | 30033 | llsend, **llshare** | runs the sender (`sudo -u llsend -g llshare`, umask 0007) |
| `llapp` | 30034 | llapp, **llshare** | the allowed peer (`peer_uid=30034`) |
| `llother` | 30035 | llother, **llshare** | in the socket's group, so the filesystem lets it connect, but a different uid |
| `llstranger` | 30036 | llstranger | not in the group |

`llother` was put in the socket's group on purpose. Otherwise mode 0660 would stop it before SO_PEERCRED is ever
checked, and (b) would not test the uid check.

Scratch server (not committed, `/tmp/llcheck/sender_server.py`):

```python
import os, sys, logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
from ledgerline import sender
from ledgerline.config import load_settings
settings = load_settings({"LEDGERLINE_DATA_DIR": "/tmp/llsend-data", "LEDGERLINE_PAYER_MCP_TRANSPORT": "memory",
                          "ANTHROPIC_API_KEY": "", "AIRWALLEX_CLIENT_ID": "", "AIRWALLEX_API_KEY": ""})
server = sender.serve(settings, "unix:/tmp/s.sock", peer_uid=int(sys.argv[1]))
st = os.stat("/tmp/s.sock")
print(f"listening uid={os.getuid()} gid={os.getgid()} sock_mode={oct(st.st_mode & 0o777)} sock_owner={st.st_uid}:{st.st_gid}", flush=True)
server.serve_forever()
```

The scratch client (`/tmp/llcheck/sender_client.py`) sends one raw JSON line (`send_refund` for
`org_000000000000`) and prints the raw bytes it gets back. It then calls `SenderClient.call` for `send_refund` and
`server_readiness`.

```bash
sudo -u llsend -g llshare bash -c "umask 0007; export PYTHONPATH=/home/user/ledgerline/backend; exec .venv/bin/python /tmp/llcheck/sender_server.py 30034" &
for u in llapp llother llstranger; do sudo -u $u env PYTHONPATH=/home/user/ledgerline/backend .venv/bin/python /tmp/llcheck/sender_client.py; done
```

Output (verbatim, trimmed):

```
listening uid=30033 gid=30002 sock_mode=0o660 sock_owner=30033:30002
srw-rw---- 660 llsend:llshare /tmp/s.sock
=== as llapp     client uid=30034
raw reply: b'{"ok": false, "error": "KeyError", "message": "unknown organization", "status": null}\n'
send_refund -> KeyError 'unknown organization'
server_readiness -> result: {'configured': False}
=== as llother   client uid=30035
raw reply: <connection closed, 0 bytes>
send_refund -> SenderUnavailable the sending service is not reachable (ConnectionResetError); nothing was sent
server_readiness -> SenderUnavailable the sending service is not reachable (ConnectionResetError); nothing was sent
=== as llstranger client uid=30036
raw connect error: PermissionError [Errno 13] Permission denied
send_refund -> SenderUnavailable the sending service is not reachable (PermissionError); nothing was sent
=== server log
WARNING ledgerline.sender refused a connection from uid 30035   (x3)
```

- (a) The allowed uid gets an answer: **yes**. It got a typed error reply for an unknown org, and a real result for
  `server_readiness`.
- (b) A third uid is refused: **yes**. The server closes without replying. Because the client's request line is
  never read, the client sees `ConnectionResetError` rather than a clean EOF, which `SenderClient` reports as
  `SenderUnavailable … nothing was sent`. That outcome is correct. See Note N1 on the wording.
- (c) Socket mode is `0660`: **yes** (`srw-rw---- llsend:llshare`).
- Also: a user outside the group cannot even connect (EACCES).

## 4. `harden.sh sender` / `sender-off` and `update.sh`'s guard

### Setup

These were all **real**: users `ledgerline` (system, uid 996, gid 995) and `ledgerline-send` (created by `harden.sh`
itself, uid 995, primary group `ledgerline`). Also real: `/etc/ledgerline` (750 root:ledgerline) and
`/etc/ledgerline/ledgerline.env` (640 root:ledgerline, with the same lines `setup.sh` writes plus
`AIRWALLEX_CLIENT_ID=fake-client-id`, `AIRWALLEX_API_KEY=fake-key` and `LEDGERLINE_PAYER_MCP_TRANSPORT=memory`).

`/var/lib/ledgerline` was built as `ledgerline` with umask 077, to match the state after `harden.sh files`:

- `control.sqlite3`, `orgs/org_aaaaaaaaaaaa.sqlite3` and `orgs/org_bbbbbbbbbbbb.sqlite3` (real SQLite files)
- `payer_agents/agent.key`
- `backups/20261103-020000/control.sqlite3` and `backups/last_offsite`
- `connections.key` (fixed content, so hashes can be compared)
- the drop-in `/etc/systemd/system/ledgerline.service.d/umask.conf` with `UMask=0077`

`/opt/ledgerline/src` is a clone of `main` owned by `ledgerline`. Its `origin` is a local bare mirror, so no network is
used. `/opt/ledgerline/venv` is a symlink to `backend/.venv`. `chown`, `chmod`, `install`, `mv`, `find`, `sed`,
`useradd` and **`sudo -u ledgerline`** were all real.

Stubbed (exported bash functions, `/tmp/llcheck/stubs.sh`):

- `systemctl`: logs each call. `enable --now ledgerline-send` does what systemd would do: it creates
  `/run/ledgerline-send` (0750 ledgerline-send:ledgerline), reads both EnvironmentFiles **as root**, and starts the
  **real** `ledgerline.sender.main()` as `ledgerline-send:ledgerline` with umask 0007. `disable --now` stops it.
  `is-active ledgerline-send` checks the PID. `is-enabled ledgerline-send` follows `STUB_SEND_ENABLED`. Failures can
  be injected with `STUB_FAIL_ENABLE=1` / `STUB_FAIL_RELOAD=1`.
- `systemd-run`: prints `SANDBOX OK`, so the app sandbox check is **not** exercised.
- `curl`: succeeds, and prints `401` for `-w '%{http_code}'`.
- `sleep`: a no-op, to skip retry waits.
- A `uv` stub in `/usr/local/bin` (only for the `update.sh` test; it logs and exits 0, then was removed).

The sender wrapper (`/tmp/llcheck/run_sender.py`) replaces only `AirwallexSandbox.readiness`. With fake keys it would
otherwise call Airwallex. So `check_sender`'s `server_readiness` round trip ran over the real socket, as user
`ledgerline`, with real SO_PEERCRED (`LEDGERLINE_SENDER_PEER_UID` from `sender.env`).

Each scenario started from a fresh fixture (`/tmp/llcheck/fixture.sh`). The fixture was confirmed reproducible:
snapshots of two builds were identical. Snapshots list every path with its mode, owner and the sha256 of its contents.

### 4a. `harden.sh sender`: PASS

```bash
source /tmp/llcheck/stubs.sh && bash /opt/ledgerline/src/deploy/vm/harden.sh sender      # EXIT=0, "sender: on."
```

State afterwards (snapshot):

```
/etc/ledgerline/ledgerline.env  -rw-r----- root:ledgerline     (no AIRWALLEX_* lines; LEDGERLINE_SENDER_SOCKET=unix:/run/ledgerline-send/send.sock)
/etc/ledgerline/sender.env      -rw------- root:root           AIRWALLEX_CLIENT_ID, AIRWALLEX_API_KEY, LEDGERLINE_CONNECTIONS_KEY_PATH, LEDGERLINE_SENDER_PEER_UID=996
/var/lib/ledgerline             drwxrwx--- ledgerline:ledgerline
/var/lib/ledgerline/orgs, payer_agents                    drwxrwx---
/var/lib/ledgerline/*.sqlite3, orgs/*, payer_agents/*     -rw-rw----
/var/lib/ledgerline/backups (and below)                   drwx------ / -rw-------   (left owner-only, as intended)
/var/lib/ledgerline-send        drwx------ ledgerline-send:ledgerline
/var/lib/ledgerline-send/connections.key  -rw------- ledgerline-send:ledgerline   (same sha256 as the original key)
/run/ledgerline-send            drwxr-x--- ledgerline-send:ledgerline
/run/ledgerline-send/send.sock  srw-rw---- ledgerline-send:ledgerline
umask.conf                      UMask=0007
```

- `sudo -u ledgerline cat /etc/ledgerline/sender.env` gives `Permission denied` (rc=1).
- `sudo -u ledgerline cat /var/lib/ledgerline-send/connections.key` gives `Permission denied` (rc=1).
- `ledgerline-send` can read company databases and its own key, but **cannot** list `backups/`.
- The app user can still read `control.sqlite3`.
- `control.sqlite3` changed content because the real sender ran its control-plane migrations at startup. That is
  expected. It stays owned by `ledgerline`.

A first, accidental run also tested the post-start check path (`harden.sh:241`). My first stub sourced `sender.env` as
the unprivileged user, so the sender never started. `check_sender` then reported "the app's user could not ask the
sending service … FileNotFoundError", and the script ran `sender_off` and exited 1. Its restore matched 4b.

### 4b. ERR trap: PASS, with caveats

```bash
STUB_FAIL_ENABLE=1 bash harden.sh sender    # "Failed to start … (stub)" / "sender: a step failed; turning it back off" / "sender: off." EXIT=1
STUB_FAIL_RELOAD=1 bash harden.sh sender    # fails at the first daemon-reload (after the keys and key file moved and the unit was installed); EXIT=1
```

Diff of the snapshots, before vs after, identical for both injected failures:

```
< /etc/ledgerline/ledgerline.env -rw-r----- root:ledgerline 9956476c0883db69
> /etc/ledgerline/ledgerline.env -rw-r----- root:ledgerline fdf80f0e5ef3a8fe
< ABSENT /var/lib/ledgerline-send
> /var/lib/ledgerline-send drwx------ ledgerline-send:ledgerline
```

Restored exactly: `connections.key` (same path, hash, `600 ledgerline:ledgerline`), every data file and directory
mode, `umask.conf`, no `sender.env`, no `ledgerline-send.service`, no `LEDGERLINE_SENDER_SOCKET`.

Not exact:

- `ledgerline.env` has the same set of lines (`diff <(sort before) <(sort after)` is empty), but `AIRWALLEX_CLIENT_ID`
  and `AIRWALLEX_API_KEY` now come after `ANTHROPIC_API_KEY`. That is harmless.
- An empty `/var/lib/ledgerline-send` and the `ledgerline-send` user are left (the user is left by design).

Scenario B: the baseline is **without** the `files` step (no `umask.conf`, files 644, directories 755). After the same
forced failure, `sender_off` leaves files 600, directories 700 and `UMask=0077`. That is tighter than before, not a
leak, but not a restore (Bug 4).

### 4c. `sender-off` twice: PASS

After a successful `sender`, I ran `harden.sh sender-off` twice. Both exited 0. The two snapshots were identical. Each
of `AIRWALLEX_CLIENT_ID=` and `AIRWALLEX_API_KEY=` appears exactly once. `connections.key` is back at
`/var/lib/ledgerline/connections.key`, `600 ledgerline:ledgerline`, with the original hash. No sender process is
left. The only differences from the original baseline are the same as in 4b (line order, empty directory), plus the
migrated `control.sqlite3`.

Scenario C: there is no `connections.key` at the start (no company connected yet). `sender` and then `sender-off`
both exit 0, and no key file is invented.

### 4d. `sender-off` after the sender left a file behind: FAIL (Bug 1)

With the sender on, I made the `ledgerline-send` user crash during a write transaction on
`orgs/org_aaaaaaaaaaaa.sqlite3` (`BEGIN IMMEDIATE`, a large insert, then `kill -9`). That leaves a hot rollback
journal, `org_aaaaaaaaaaaa.sqlite3-journal`, `-rw-rw---- ledgerline-send:ledgerline`. While the sender is on, the
app user can open the database, because the group can write.

After `harden.sh sender-off`:

```
-rw------- 1 ledgerline      ledgerline 2048000 org_aaaaaaaaaaaa.sqlite3
-rw------- 1 ledgerline-send ledgerline    9728 org_aaaaaaaaaaaa.sqlite3-journal
$ sudo -u ledgerline python3 -c "import sqlite3; sqlite3.connect('…/org_aaaaaaaaaaaa.sqlite3').execute('select count(*) from t')"
sqlite3.OperationalError: unable to open database file
```

That company is unusable until someone runs `chown` by hand. The same applies to any file the sender creates under
`/var/lib/ledgerline`. With the patch in Bug 1, the same sequence ends with the journal owned by `ledgerline`, and the
app opens the database and rolls the journal back (`(0,)`).

### 4e. `harden.sh files` while the sender is on: FAIL (Bug 2)

With the sender on, `harden.sh files` printed `files: done. Readable by group or others now: 0` and exited 0. After
that, `umask.conf` holds `UMask=0077`, company databases are `600`, directories are `700`, and
`sudo -u ledgerline-send cat orgs/org_aaaaaaaaaaaa.sqlite3` gives `Permission denied`. Every money-out through the
sender would then fail. `check_app` does not check the sender, so the step reports success. With the patch in Bug 2,
`files` refuses while the sender is active, and still runs normally once it is off.

### 4f. `update.sh` sender guard: PASS

I ran a copy of `update.sh` from `main` (`/tmp/llcheck/update.sh`), because the checkout rewrites the file in `SRC`.
`SRC=/opt/ledgerline/src` was at 1668374. `ff10cfa` has no `backend/ledgerline/sender.py` (`git cat-file -e` fails).

| case | command | result |
|------|---------|--------|
| U1: sender enabled, running 1668374, deploy `ff10cfa` | `STUB_SEND_ENABLED=1 bash update.sh ff10cfa` | "the sending service is on and ff10cfa predates it; run harden.sh sender-off first". It rolled back to 1668374 ("restored …"), **EXIT=1**, HEAD 1668374, **no restart** of either service. |
| U2: sender enabled, already running `ff10cfa`, deploy `main` | `STUB_SEND_ENABLED=1 bash update.sh main` | "the running commit ff10cfa… predates it". Refused before checkout, **EXIT=1**, HEAD unchanged, no restart. |
| U3: sender not enabled, deploy `ff10cfa` | `STUB_SEND_ENABLED=0 bash update.sh ff10cfa` | Deployed, EXIT=0, only `systemctl restart ledgerline` |
| U4: sender enabled, deploy `main` | `STUB_SEND_ENABLED=1 bash update.sh main` | Deployed, EXIT=0, `restart ledgerline-send` then `restart ledgerline` |

The health-failure rollback path with the sender on (new version unhealthy, previous version restored) was not
exercised separately. U2's up-front guard is what ensures the commit restored there also has `sender.py`.

## 5. Browser suite on Linux

```bash
cd frontend && npm ci            # OK
npm run build                    # OK (tsc -b && vite build)
npx playwright install --with-deps chromium
#   Error: Failed to download Chrome for Testing 156.0.8078.4 (playwright chromium v1248) … Download failure
#   (the container's egress proxy refused cdn.playwright.dev)
```

`playwright.config.ts` already supports `E2E_CHANNEL=chromium`, as CI's e2e job uses. That needs the downloaded
build, which wasn't available. So I ran a **scratch copy** of the config (deleted, not committed) that replaces only
`channel: …` with `launchOptions: { executablePath: "/opt/pw-browsers/chromium" }`. That is the container's
pre-installed Chrome for Testing 153.0.8010.12 (Playwright build 1243), against `@playwright/test` 1.64.1, which
expects build 1248. The webServer setup is unchanged: the real API serving `dist/`, and the reference payer agent.

```bash
node -e "require('fs').rmSync('e2e/.data',{recursive:true,force:true})" && npx playwright test -c playwright.linuxcheck.config.ts
```

Result: **27 passed, 2 skipped, 0 failed (1.5 min).**

| # | test | result |
|---|------|--------|
| 1 | demo-video.spec.ts:13 record the demo video | skipped ("set DEMO_DIR to record the demo video") |
| 2 | journey.spec.ts:43 full journey as two people | passed (30.5 s) |
| 3 | saas:25 sign up with sample data, sign out, sign back in | passed |
| 4 | saas:43 home page explains the product and leads to sign-up | passed |
| 5 | saas:56 Google sign-in explains missing credentials and Apple is absent from the login form | passed |
| 6 | saas:70 settings lists sign-in methods | passed |
| 7 | saas:80 wrong password is refused without revealing whether the account exists | passed |
| 8 | saas:88 empty workspace: record a manual payment through the form | passed |
| 9 | saas:102 invited viewer is read-only in the UI and refused by the API | passed |
| 10 | saas:135 a second organization cannot see the first organization's payments | passed |
| 11 | saas:149 phone width: no page-level horizontal overflow | passed |
| 12 | saas:162 sign-up says which field is missing | passed |
| 13 | saas:173 a real company sees setup steps and short-cash decisions | passed |
| 14 | saas:191 practice company shows all four cash decisions | passed |
| 15 | saas:215 wrong-currency payment converts only what the invoice needs; balance request has an email draft | passed |
| 16 | saas:234 CEO view answers the four questions and its numbers lead to the detail | passed |
| 17 | saas:250 first-visit guide leads to the agent's decision, and can be hidden | passed |
| 18 | saas:264 the approver of an agent-proposed refund is told why they cannot send it | passed |
| 19 | saas:276 one person finishes the practice walkthrough with the practice teammate sending the refund | passed |
| 20 | saas:315 phone width: a judge can do the whole three-step path at 375 px | passed |
| 21 | saas:350 show me: the guided tour runs the practice story, and a tampered audit row is caught and restored | passed |
| 22 | saas:383 own agent: an owner points a practice customer at its own payer agent, and the answer says where it came from | passed |
| 23 | saas:408 refund held by the pause returns to a second person when the limit is lowered | passed |
| 24 | saas:426 pressing Execute on a refund now over the limit explains that it needs a second person | passed |
| 25 | saas:445 phone width: bill payments read as cards with nothing to scroll sideways | passed |
| 26 | saas:461 dialogs opened from the sidebar are readable and keep focus while typing | passed |
| 27 | saas:476 amounts typed with thousands separators are accepted | passed |
| 28 | saas:489 payment detail shows the decision path and accounts for every cent | passed |
| 29 | screenshots.spec.ts:24 capture README screenshots | skipped ("set SCREENSHOTS=1 to regenerate README screenshots") |

## 6. Accuracy run

```bash
backend/.venv/bin/python scripts/accuracy_run.py --seeds 50 --walkthroughs 5 --report /tmp/acc.md     # rc=0
```

> Seeds 1–50 (50 synthetic companies) and 5 sample-company walkthroughs, in 89 s.
> **Result: PASS** · 14,849 individual checks · 2,127 payments · 1,006 invoices

---

## Bugs found (most severe first)

### Bug 1 (medium-high, availability; only after the sender has been on): `sender-off` makes files the sender created unreadable by the app

`deploy/vm/harden.sh:277-278` (`sender_off`): `find /var/lib/ledgerline -type f -exec chmod 600` runs, but files
owned by `ledgerline-send` are never given back to `ledgerline`. A hot SQLite journal left by a sender crash or kill
(reproduced in 4d), or any file the sender created under `/var/lib/ledgerline`, becomes `600 ledgerline-send`. The
app then gets `sqlite3.OperationalError: unable to open database file` for that company. The same happens when
`sender_off` runs from the ERR trap or from the failed-check path. Verified fix:

```diff
--- a/deploy/vm/harden.sh
+++ b/deploy/vm/harden.sh
@@ -274,6 +274,7 @@
   elif [[ -f $KEY_SEND ]]; then echo "WARNING: both $KEY_SEND and $KEY_APP exist; left both in place, compare them by hand" >&2; fi
   if [[ -f $KEY_APP ]]; then chown ledgerline:ledgerline "$KEY_APP" || true; chmod 600 "$KEY_APP" || true; fi
   mkdir -p "$DROPIN"; printf '[Service]\nUMask=0077\n' > "$DROPIN/umask.conf"
+  chown -R ledgerline:ledgerline /var/lib/ledgerline || true  # files the sending service created (a journal, a database)
   find /var/lib/ledgerline -type f -exec chmod 600 {} + || true
   find /var/lib/ledgerline -type d -exec chmod 700 {} + || true
   rm -f /etc/systemd/system/ledgerline-send.service
```

### Bug 2 (medium, only if the owner runs `files` after `sender`): `harden.sh files` silently breaks a running sender

`deploy/vm/harden.sh:119-128` (`files`): it sets `UMask=0077` and makes every file 600 and every directory 700, so the
sender (group `ledgerline`) loses access to every company database. `check_app` doesn't check the sender, so the step
reports `files: done`. Reproduced in 4e. `undo-files` doesn't put the 660/770 modes back either. Verified fix (refuse;
the alternative would be to apply the sender's 660/770 when it is on):

```diff
--- a/deploy/vm/harden.sh
+++ b/deploy/vm/harden.sh
@@ -117,6 +117,9 @@
 }
 
 files() {
+  if systemctl is-active --quiet ledgerline-send; then
+    echo "the sending service is on; owner-only files would lock it out of the databases. Run harden.sh sender-off first" >&2; exit 1
+  fi
   mkdir -p "$DROPIN"
   printf '[Service]\nUMask=0077\n' > "$DROPIN/umask.conf"
   install -m 644 "$SRC/deploy/vm/ledgerline-backup.service" /etc/systemd/system/ledgerline-backup.service
```

### Bug 3 (medium, CI; test-only): 4 `test_sender.py` tests fail in the whole-suite-on-PostgreSQL job

`backend/tests/test_sender.py:31` (`pair` fixture, `app_settings`): under `LEDGERLINE_TEST_ALL_ON_POSTGRES=1`, conftest sets
`LEDGERLINE_PG_SCHEMA_PREFIX=auto`, and `config.py:240-244` gives each `load_settings()` its own prefix. The sender
(`keys`) and the app (`app_settings`) therefore use different control-plane schemas, and the sender answers
`KeyError: unknown organization`. Production shares one prefix, so the app is fine. But the CI postgres job will be
red, and these tests currently give no PG coverage of the sender. Verified fix (all 10 pass on PG 17, and the change
has no effect on SQLite):

```diff
--- a/backend/tests/test_sender.py
+++ b/backend/tests/test_sender.py
@@ -29,6 +29,7 @@ def pair(tmp_path, monkeypatch):
     threading.Thread(target=server.serve_forever, daemon=True).start()
     address = f"tcp:127.0.0.1:{server.server_address[1]}"
     app_settings = load_settings({**BASE, "LEDGERLINE_DATA_DIR": str(tmp_path), "LEDGERLINE_SENDER_SOCKET": address,
+                                  "LEDGERLINE_PG_SCHEMA_PREFIX": keys.pg_schema_prefix,  # same database for both, as in production
                                   "AIRWALLEX_CLIENT_ID": "", "AIRWALLEX_API_KEY": ""})
     app = create_app(app_settings)
     c = TestClient(app)
```

### Bug 4 (low): the ERR-trap and `sender-off` restore is not exact

`deploy/vm/harden.sh:262-282`:

- (a) The Airwallex key lines are appended to the end of `ledgerline.env` instead of going back to where they were.
  That is harmless, but `SERVER_STEPS.md` / the comment at `:216` say it "puts everything back as it was".
- (b) `/var/lib/ledgerline-send` (empty after the key moves back) is left behind.
- (c) `sender_off` always writes `UMask=0077` and 600/700 modes, whatever they were before. If the owner never ran
  `files`, this is a tightening, not a restore (scenario B). That is safe, but the wording should say so.

Proposed (b) plus a wording fix:

```diff
--- a/deploy/vm/harden.sh
+++ b/deploy/vm/harden.sh
@@ -215,3 +215,3 @@
   if systemctl is-active --quiet ledgerline-send; then echo "the sending service is already on"; check_sender; return; fi
-  # Any failure part-way puts everything back as it was, so the app never restarts without its keys.
+  # Any failure part-way turns it back off (sender_off), so the app never restarts without its keys.
   trap 'trap - ERR; echo "sender: a step failed; turning it back off" >&2; sender_off; exit 1' ERR
@@ -275,2 +275,3 @@
   if [[ -f $KEY_APP ]]; then chown ledgerline:ledgerline "$KEY_APP" || true; chmod 600 "$KEY_APP" || true; fi
+  rmdir /var/lib/ledgerline-send 2>/dev/null || true  # only if empty: a key left there (the WARNING above) stays
   mkdir -p "$DROPIN"; printf '[Service]\nUMask=0077\n' > "$DROPIN/umask.conf"
```

### Bug 5 (low or informational; does not affect the VM, which uses SQLite): no separation under PostgreSQL

With `LEDGERLINE_DATABASE_URL` and `LEDGERLINE_SECRET_KEY` set, `connections._root_secret` (`connections.py:31-32`)
seals companies' credentials with `LEDGERLINE_SECRET_KEY`, not with `connections.key`. The app must keep that secret
(payer-agent keys, `payer_agents/keys.py:56`), so a compromised app could unseal the credentials itself.
`harden.sh sender` neither moves the secret nor detects this case, so on a PostgreSQL VM it would report "sender: on"
without the separation it promises. Proposed guard:

```diff
--- a/deploy/vm/harden.sh
+++ b/deploy/vm/harden.sh
@@ -215,2 +215,3 @@
   if systemctl is-active --quiet ledgerline-send; then echo "the sending service is already on"; check_sender; return; fi
+  if grep -qE '^LEDGERLINE_DATABASE_URL=.+' "$ENVF"; then echo "the sending service separates keys only with local storage (SQLite); this server uses PostgreSQL" >&2; exit 2; fi
   # Any failure part-way puts everything back as it was, so the app never restarts without its keys.
```

### Notes (no change needed)

- **N1:** A peer refused by SO_PEERCRED sees `ConnectionResetError`, because the server closes without reading the
  request. The client reports this as "the sending service is not reachable … nothing was sent", which is correct
  but could send someone looking for a down service. The server logs `refused a connection from uid N`.
- **N2:** `sender.serve` binds the socket and then calls `chmod 0660` (`sender.py:277-278`), so for a moment its mode
  depends on the process umask. Under the unit's `UMask=0007` it is never wider than 0660, so this is fine. Only
  under umask 0 would there be a window.
- **N3:** `ledgerline-send`'s primary group is `ledgerline`, so it can also read anything group-readable by
  `ledgerline`, for example `/etc/ledgerline/backup.env` (the bucket name only). `backup.key` is `600 ledgerline`
  and stays unreadable to it.

## Not run and why

- **Real systemd:** none in the container. These were not exercised:
  - the units themselves (`ledgerline-send.service`'s `RuntimeDirectory`/`StateDirectory`, `ProtectSystem=strict`,
    `SystemCallFilter`, `RestrictAddressFamilies`, `EnvironmentFile` parsing by systemd)
  - `daemon-reload`, `systemctl enable` ordering (`Before=ledgerline.service`)
  - `check_app`'s sandbox check (`systemd-run` stubbed) and the health/401 checks (`curl` stubbed)
  - `systemd-analyze`, `journalctl` and therefore `harden.sh status`

  My stub reproduced what the unit asks for (runtime directory 0750 owned by the service user, both env files read as
  root, umask 0007), but it is not systemd. Before step 7, check on the VM, after `harden.sh sender`:
  `systemctl status ledgerline-send` and `ls -l /run/ledgerline-send/`.
- **The app process with the sender on:** the API was not started as `ledgerline` against the socket in check 4,
  because `restart ledgerline` was stubbed. The app's use of the sender is covered by `test_sender.py` (over TCP on
  SQLite, and on PostgreSQL with the fixture fix). The socket round trip as user `ledgerline` with SO_PEERCRED was
  covered by `check_sender`.
- **Real Airwallex readiness through the sender:** replaced in the stubbed service because the keys are fake. No
  network calls to Airwallex were made.
- **`update.sh` health-failure rollback with the sender on, and the real `uv pip install` / frontend build in
  `update.sh`:** not exercised (`uv` stubbed, no `/etc/ledgerline/mode`).
- **The playwright-pinned Chromium (build 1248):** the download was blocked by the network policy, so the
  pre-installed build 1243 was used instead.
- **`demo-video` and `screenshots` e2e specs:** opt-in recorders, skipped by design.
- **Full 200-seed accuracy run:** not requested (already passed).
- **Anything against 35.207.220.110 / sslip.io:** not contacted, as instructed.
