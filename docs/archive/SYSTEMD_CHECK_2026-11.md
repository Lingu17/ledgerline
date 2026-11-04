# systemd check of the sending-service steps (November 2026)

Tested commit: `f5a3b8e` (branch `review/linux-fixes`). Checked again against `main` at `53ede14`: the files involved in
the problems below are the same there, except `config.py`, which has the same problem plus one more name (see P1).

Only fake values were used (fake `AIRWALLEX_CLIENT_ID` and `AIRWALLEX_API_KEY`, a made-up
`connections.key`). Nothing was deployed, the live site was not contacted and no real Airwallex or Anthropic endpoint
was called.

## Verdict

The systemd side works under real systemd. That covers the unit, RuntimeDirectory, StateDirectory, the sandbox,
EnvironmentFile, ordering, the `systemd-run` sandbox check, the ERR trap, `files` refusing while the sender is on, and
both on/off cycles. **But the sender does not actually take effect in the app.** `config.py` drops
`LEDGERLINE_SENDER_SOCKET` and `LEDGERLINE_CONNECTIONS_KEY_PATH` from the environment (P1). With the sender "on", the
app keeps using its own key and creates a new one when the moved key is missing. Companies connected to Airwallex
before the switch then get HTTP 500, and stay broken after `sender-off` until someone swaps the keys back by hand.
`harden.sh` reports success throughout. **Do not run `harden.sh sender` on the live VM until P1 is fixed.**

| Step | Result |
|---|---|
| 1. systemd as PID 1 | OK: `systemctl is-system-running` = `running` (systemd 255.4-1ubuntu8.18) |
| 2. `setup.sh` (`LEDGERLINE_LOCAL_ONLY=1`), fake keys | OK: `ledgerline.service` active, `/api/health` ok, signed-out `/api/deposits` 401 |
| 3a. `harden.sh status` | OK |
| 3b. `harden.sh files` | OK: everything under `/var/lib/ledgerline` 600/700, `UMask=0077` |
| 3c. `harden.sh systemd` | OK: all 5 groups kept; score **8.3 EXPOSED → 1.7 OK**; 0 service errors in the 130 s round |
| 3d. `harden.sh sender`, fake keys, Airwallex unreachable | **PROBLEM P2**: `check_sender` needs a working Airwallex login, so the step always turns itself off with fake keys |
| 3d. `harden.sh sender`, fake keys, local fake Airwallex | OK as far as `harden.sh` can see: unit, socket, modes, owners, `check_app`, `check_sender`, the sandbox check |
| 3e. App with the sender on | **PROBLEM P1**: the app ignores the socket; it creates and uses its own `connections.key` |
| 3f. Practice walkthrough (refund, simulated bank) | OK: all 8 steps, refund `paid` (the practice company never uses the sender) |
| 4. `sender-off`, then `sender` and `sender-off` again | OK for systemd, files and health; **P1 knock-on**: "both keys exist" WARNING, and a connected company stays broken |
| 5. Forced failure | OK: the ERR trap restores everything. **PROBLEM P3**: `systemctl enable --now` exits 0 when the start fails, so the trap never sees a failed start (`check_sender` catches it instead) |
| 6. `files` while the sender is on | OK: refuses with exit 1 and changes nothing |
| Extra: reboot with the sender on | OK: the sender starts before the app, `/run/ledgerline-send/send.sock` is recreated, the app is healthy |

## Problems and suggested fixes

### P1 (serious): the app and the sender ignore `LEDGERLINE_SENDER_SOCKET` and `LEDGERLINE_CONNECTIONS_KEY_PATH`

`load_settings()` copies only the names in `_ENV_KEYS` from the environment (`backend/ledgerline/config.py:15-56` and
`:188-190`). It later reads `LEDGERLINE_SENDER_SOCKET` (`config.py:247`) and `LEDGERLINE_CONNECTIONS_KEY_PATH`
(`config.py:248`), but neither name is in the list. So the line `harden.sh` writes to `ledgerline.env`, and the line it
writes to `sender.env`, never take effect. `main` has a third name with the same gap: `LEDGERLINE_SECURITY_CONTACT`
(the security.txt contact) is read but not listed, so it is always empty on a server.

Evidence from the running app process, which had `LEDGERLINE_SENDER_SOCKET` in `/proc/<pid>/environ`:

```
# load_settings() in the app's environment (ledgerline.env), sender on
sender_socket set: False
bank_mode: airwallex_sandbox sealed: True
provider: AirwallexSandbox sender: NoneType          # should be SenderProxy (tenancy.py:44-52)

# the sending service's environment
sender process sees connections_key_path = None      # should be /var/lib/ledgerline-send/connections.key
```

What this does on a server with the sender on:

1. **A company connects to Airwallex.** The app seals its credentials itself (`api/auth_routes.py:271` takes the
   non-sender branch). `connections.py:33-40` finds no key at `/var/lib/ledgerline/connections.key`, because
   `harden.sh` moved it, and **creates a new one**, owned by the app's user, mode 600. Observed:
   `-rw------- ledgerline:ledgerline 17:13:43 /var/lib/ledgerline/connections.key` while the sender was on. The
   separation `harden.sh` reports ("readable only by the sending service and root") is not in effect.
2. **A company that connected before the sender was turned on**: every bank page returns 500.
   ```
   login 200
   treasury 500 Internal Server Error
   rates 500 Internal Server Error
     File "/opt/ledgerline/src/backend/ledgerline/tenancy.py", line 61, in build_org_context
       client_id, api_key = unseal(settings, org["id"], org["airwallex_credentials_enc"])
   ledgerline.connections.ConnectionError_: saved Airwallex credentials cannot be decrypted; connect the account again
   ```
3. **After `sender-off`** both keys exist, so the step leaves both in place:
   ```
   WARNING: both /var/lib/ledgerline-send/connections.key and /var/lib/ledgerline/connections.key exist; left both in place, compare them by hand
   sender: off. The app holds the Airwallex keys again, as before. (The ledgerline-send user is left in place.)
   ```
   The app keeps the new key, so the company from point 2 **still gets 500**. It worked again only after a manual
   swap: delete the new key, then move `/var/lib/ledgerline-send/connections.key` back to `/var/lib/ledgerline/`.
4. From reading the code (not run here): companies on the server's shared sandbox keys (`LEDGERLINE_SANDBOX_ORGS`)
   lose access while the sender is on. The app no longer has the server keys, and it does not know about the socket,
   so `sandbox_allowed()` (`config.py:147-149`) is false.

Why it was missed: `backend/tests/test_sender.py:27,31` passes these names through `load_settings(overrides)`, which
skips the `_ENV_KEYS` filter. `check_sender` talks to a hard-coded socket path (`deploy/vm/harden.sh:261`), so it never
asks whether the app itself uses the socket.

Fix:
- Add `LEDGERLINE_SENDER_SOCKET` and `LEDGERLINE_CONNECTIONS_KEY_PATH` to `_ENV_KEYS` (on `main` also
  `LEDGERLINE_SECURITY_CONTACT`). Consider a unit test that fails when a name read with `env.get(...)` in
  `load_settings` is missing from `_ENV_KEYS`.
- Add a test that sets these with `monkeypatch.setenv` rather than `overrides`.
- In `check_sender`, check what the app sees under its own environment, and check that the app has not created a key
  of its own:
  ```bash
  systemd-run --quiet --wait --collect --pipe --uid=ledgerline --gid=ledgerline -p WorkingDirectory="$SRC/backend" \
    -p EnvironmentFile=/etc/ledgerline/ledgerline.env /opt/ledgerline/venv/bin/python -c \
    'from ledgerline.config import load_settings; assert load_settings().sender_socket; print("APP USES SENDER")'
  [[ ! -e $KEY_APP ]] || echo "  CHECK FAILED: the app has its own $KEY_APP while the sender is on"
  ```
  Do the same for the sender (`-p EnvironmentFile=` both files, `--uid=ledgerline-send`, assert
  `connections_key_path == /var/lib/ledgerline-send/connections.key`).
- In `sender_off`, print "off, but two keys need comparing" instead of "as before" when the WARNING fired, and exit
  non-zero.
- Before the fix is deployed, a server where someone already ran `sender` needs a by-hand check of which key seals
  the stored credentials (`organizations.airwallex_credentials_enc` in the control database).

### P2: `harden.sh sender` cannot succeed unless Airwallex accepts the server keys

`check_sender` asks the sender for `server_readiness` (`deploy/vm/harden.sh:261`). With server keys present, that is a
live Airwallex login plus two reads (`sender.py:230-235`, `providers/airwallex.py:122-127`). With fake keys, an
Airwallex outage or a DNS failure, the call raises, the check fails, and the step turns itself back off. The message
blames the socket, which did answer:

```
  CHECK FAILED: the app's user could not ask the sending service: ledgerline.sender.SenderRefused: [Errno -2] Name or service not known
sender: a check failed; turning it back off
```

`journalctl -u ledgerline-send` gets a full traceback for each attempt (`httpx.ConnectError` is not in `_errors()`, so
`sender.py:267` logs it with `log.exception`):

```
File "/opt/ledgerline/src/backend/ledgerline/providers/airwallex.py", line 125, in readiness
  self._bearer()
File "/opt/ledgerline/src/backend/ledgerline/providers/airwallex.py", line 87, in _bearer
  resp = self._http.post(
httpx.ConnectError: [Errno -2] Name or service not known
ledgerline-send.service: Deactivated successfully.
```

(In this environment Airwallex was unreachable. With fake keys and Airwallex reachable, `_bearer` would raise
`ProviderError: authentication failed: HTTP 401` and the check would fail the same way.)

Fix: check the socket with a request that never leaves the machine, for example a new `ping` method in
`Service.handle`. Any well-formed reply means the socket works, while `SenderUnavailable` means it does not. Then run
`server_readiness` separately and print its result as a warning, without turning the sender off. That keeps a bank
outage from undoing the step.

### P3 (minor): the ERR trap cannot catch a sender that fails to start

`deploy/vm/harden.sh:244` runs `systemctl enable --now ledgerline-send`. On systemd 255 that exits **0** even when the
start job fails; plain `systemctl start` exits 1:

```
enable --now rc=0
start rc=1
```

With a `Type=exec` drop-in pointing at a missing binary, the script went on to restart the app with the socket
configured. Only `check_sender` noticed and turned the sender off ("a check failed", not "a step failed"). The
shipped unit is `Type=simple`, so even `start` succeeds there and only the check catches a bad ExecStart. That was
tested too (203/EXEC, reverted correctly).

Fix: `systemctl enable ledgerline-send && systemctl start ledgerline-send`, then wait for the socket, so a failed start
reaches the ERR trap before the app is restarted. Optionally use `Type=notify` or `Type=exec` in the unit, so
`start` waits until the service is really up.

### Cosmetic

- `check_app` (`deploy/vm/harden.sh:50`) prints `curl: (7) Failed to connect to 127.0.0.1 port 8000` 1-2 times after
  every restart while the app is still starting. Use `curl -fs` (no `-S`) inside the wait loop.
- `harden.sh status` prints `Failed to add filter for units: No data available` (from `journalctl -u
  'google-cloud-ops-agent*'`) on a server without the Ops Agent; add `2>/dev/null`. When the drop-in folder exists but
  is empty, `== drop-ins` prints nothing instead of "none".

## What was verified under real systemd

- **Sandbox applied for real.** In the app: `CapBnd: 0000000000000000`, `NoNewPrivs: 1`, `Seccomp: 2`. In the
  `systemd-run` sandbox check, built from the unit and drop-ins (46 `-p` arguments), `AF_NETLINK` gave `[Errno 97]
  Address family not supported by protocol` and writing under `/etc` gave `Read-only file system`, so the check runs
  under the same restrictions. The stdio payer agent, Ed25519, AES-GCM and outbound HTTPS all passed under
  `SystemCallFilter=@system-service` and `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`.
- **The sender unit.** `systemd-analyze security ledgerline-send`: 1.7 OK. Process: uid `ledgerline-send`, gid
  `ledgerline`, `Seccomp: 2`, no capabilities. Both EnvironmentFiles were read (the server keys reached it from
  root-only `sender.env`). RuntimeDirectory and StateDirectory:
  ```
  drwxr-x---  ledgerline-send ledgerline  /run/ledgerline-send/
  srw-rw----  ledgerline-send ledgerline  /run/ledgerline-send/send.sock
  drwx------  ledgerline-send:ledgerline  /var/lib/ledgerline-send
  ```
- **Peer check on the socket.** As `ledgerline`: answered. As root: `ConnectionResetError`, with the journal line
  `WARNING ledgerline.sender refused a connection from uid 0`. As `nobody`: `PermissionError`, because the socket is
  660.
- **Files with the sender on** (values never printed):
  ```
  -rw-r----- root:ledgerline            /etc/ledgerline/ledgerline.env   LEDGERLINE_SENDER_SOCKET only, no Airwallex lines
  -rw------- root:root                  /etc/ledgerline/sender.env       AIRWALLEX_CLIENT_ID, AIRWALLEX_API_KEY, KEY_PATH, PEER_UID
  -rw------- ledgerline-send:ledgerline /var/lib/ledgerline-send/connections.key
  drwxrwx--- / -rw-rw---- ledgerline:ledgerline  /var/lib/ledgerline and its databases
  ledgerline cannot read /etc/ledgerline/sender.env
  ledgerline cannot read /var/lib/ledgerline-send/connections.key
  ledgerline.service.d/umask.conf: UMask=0007
  ```
- **Files after `sender-off`** (all three times): `sender.env` gone, both Airwallex lines back in `ledgerline.env`
  (640 root:ledgerline), `connections.key` back as 600 `ledgerline:ledgerline`, everything 600/700 and owned by
  `ledgerline`, `/var/lib/ledgerline-send` removed (except when the P1 WARNING fired), `/run/ledgerline-send` gone,
  `UMask=0077`, the unit file removed. `/api/health` 200 and signed-out `/api/deposits` 401 after every step.
- **The ERR trap.** With a plain file at `/var/lib/ledgerline-send`: `install: cannot create directory
  '/var/lib/ledgerline-send': File exists`, then `sender: a step failed; turning it back off`. Everything was restored
  and the app stayed healthy.
- **Through the socket.** Sealing a newly connected company's credentials (`seal`) and bank reads (`provider` ops)
  are the paths that should use the socket. Because of P1 the app never took them; it used its own key and called the
  bank itself. With the sender on, a practice company (simulated bank) works: signup, all 8 walkthrough steps, the
  refund approved, sent by the practice teammate, simulated SENT and then PAID. The practice company never touches the
  sender: `Service.context` refuses orgs not connected to Airwallex, and the practice company's bank is local.

## Environment and what differs from the VM

- Docker 29.9.2 on the session sandbox. `jrei/systemd-ubuntu:24.04` run with `--privileged --cgroupns=host
  --network host`, systemd as PID 1. **The host uses cgroup v1 (hybrid)**; the GCP VM uses cgroup v2. Settings that
  depend on cgroups (none of the sandbox groups here) may behave differently there.
- Edge mode (`setup.sh ledgerline.internal http://localhost:5173 review/linux-fixes`), because the frontend build
  needs Node 22 from deb.nodesource.com, which is blocked here. The units are the same in both modes.
- The sandbox's network blocks dl.cloudsmith.io and astral.sh. Caddy 2.10.2 came from its GitHub release (Ubuntu's
  2.6.2 rejects `trusted_proxies` in `deploy/vm/Caddyfile`) and uv from PyPI, so `setup.sh` skipped those two
  installs. The sandbox also intercepts TLS, so its CA was added to the container's trust store.
- `swapon` was a no-op shim, so a privileged container would not change the host's swap. `openssh-server` was added
  so that `status` reaches its ssh section (it stops there under `pipefail` if `sshd` is missing; the VM has sshd).
- **Fake Airwallex, test only.** Caddy served `api.sandbox.airwallex.com` (in `/etc/hosts` → 127.0.0.1, `tls
  internal`) and answered login, `global_accounts` and `balances/current` with empty data. Drop-ins
  `ledgerline-send.service.d/test-ca.conf` and `ledgerline.service.d/zz-test-ca.conf` set `SSL_CERT_FILE` so httpx
  trusted it. Forced failures used `ledgerline-send.service.d/zz-fail.conf`. None of this touched the repository
  checkout; `/opt/ledgerline/src` stayed clean at `f5a3b8e`.
- `docker exec` runs with umask 0000, so every command used `umask 022` (as sudo does). Before that,
  `/etc/ledgerline/mode` came out 666; it was reset to 644. That came from the container, not from the script.
