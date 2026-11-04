# Recovery drill rehearsal (server step 6), 4 Nov 2026

A test-only rehearsal of `docs/SERVER_STEPS.md` step 6, run end to end in two local containers, without Google Cloud.
Nothing was deployed. The live site and Google Cloud were not touched, and every key and password was a throwaway.
No code was changed: this file is the only change.

**Result: the drill passes.** The restore check printed `PASS` for all three organizations, health was ok, both STOP
conditions held, and the restored app made no outbound connection. `restore_check.py` refused a wrong key, a renamed
object and a flipped byte. The run turned up 15 places where step 6 would fail or confuse the owner on Google Cloud.
Four of them matter most: (1) the docs bundle `main`, not the code the live VM runs, (2) `$BUCKET` is never set in
step 6, (3) a wrong key or renamed file shows only a Python traceback, (4) Caddy on the drill VM keeps requesting a
public certificate. All 15 are listed below.

## Setup

| | |
|---|---|
| Machines | Two privileged `jrei/systemd-ubuntu:24.04` containers (pulled through `mirror.gcr.io` because Docker Hub returned 429), `--privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw`. `systemctl is-system-running` printed `running` in both, with `systemd` as PID 1. |
| "source" code | `deploy/vercel-render` at **ebd32f2** ("Help page, page-not-found, ..."). This branch moved during the session: when the session started it was at d22f232. Installed with `LEDGERLINE_LOCAL_ONLY=1 LEDGERLINE_REPO=/srv/ledgerline.bundle setup.sh 172-17-0-2.sslip.io self deploy/vercel-render`. Health returned `"commit":"ebd32f2a6435"`. |
| "fresh" code | **d22f232** (`main`), because step 6 bundles and runs `main`. See finding 1. |
| Files `deploy/vm/{setup.sh,restore_drill.sh,restore_check.py,backup.py}` | Identical on `main` and `deploy/vercel-render`. |

**Test-only changes to the machines (not repository changes).** Each is needed only because of the container or this
sandbox's network, not because of Ledgerline:

- The containers could reach the internet only through the session's HTTPS proxy. I forwarded it onto the docker
  bridge, added its CA to each container's trust store, and set `https_proxy` in `/etc/environment`.
- The sandbox blocks `dl.cloudsmith.io`, `astral.sh` and `deb.nodesource.com`, so caddy (Ubuntu's 2.6.2 package), uv
  0.13.7 and Node 22 were installed before the run. `setup.sh` skips those downloads when the tools already exist.
  apt, Python 3.14.8, all pip wheels and all npm packages were still downloaded live by `setup.sh`.
- A `swapon` shim, because swap cannot be turned on in a container on overlayfs. `setup.sh` failed at
  `swapon: /swapfile: swapon failed: Invalid argument` without it.
- In "fresh" only: a one-shot fake metadata endpoint. `/etc/hosts` pointed `metadata.google.internal` at 127.0.0.2,
  where a server answered `external-ip` with the TEST-NET address `203.0.113.10` and then exited. Without it the drill
  stops at once (finding 5).

## Data in "source"

The data was created through the API (`/api/auth/signup`, `/api/organizations`, `/api/demo/step`, `/api/approvals`,
`/api/customers`, `/api/invoices`, `/api/payments`). The account and password were fake.

- **Practice company** `org_683b0279562e` (sample): all 8 walkthrough steps are done (`seed, deposits, links, agents,
  treasury, approve, bank_sent, bank_paid`). The over-limit refund APR-88F630FC was approved by the owner and sent by
  the practice teammate. Audit chain: ok, 42 events.
- **My company** `org_f55a3300d342` (workspace): 3 customers (GB, DE, SG), 3 invoices (INV-2301 GBP 1,200.00,
  INV-2302 EUR 880.50, INV-2303 USD 2,500.00) and 3 manual payments (GBP 1,200.00, EUR 400.00 part payment,
  USD 2,500.00). Audit chain: ok, 19 events.
- `org_87462c60d17b` is an empty "My company". My first driver run created it and then stopped at a validation error
  (`refund_beneficiary` is required). I left it in, so the backup has 3 organizations.

**Backup.** `systemctl start ledgerline-backup.service` ran `backup.py` and wrote `backups/20261104-174309` (it also
printed "no off-server copy: LEDGERLINE_BACKUP_BUCKET is not set"). A small script outside the repository then
generated a random 32-byte key (base64, mode 600, never displayed) and wrote
`backup.encrypt(backup.pack(snapshot), key, "ledgerline/20261104-174309.tar.gz.enc")`. That object name is the one
`offsite()` uses. The result was **`20261104-174309.tar.gz.enc`**, 52,105 bytes, sha256 `20abf211…b869`.

**Copy to "fresh".** `git bundle create ledgerline.bundle --all` was run in a full (not shallow) clone that holds
`main` and `deploy/vercel-render`. The bundle, `restore_drill.sh` (from `main`), the `.enc` file and `backup.key` were
copied into `/home/owner` on "fresh" with `docker cp`, the way `gcloud compute scp … ledgerline-drill:~` would. The
drill then ran as that user, exactly as step 6 runs it:

```
sudo bash restore_drill.sh ledgerline.bundle 20261104-174309.tar.gz.enc backup.key main
```

## Results in "fresh"

### STOP checks

Both checks passed. The drill prints nothing when they pass (finding 8), so I checked each one afterwards:

| Check (`restore_drill.sh`) | Result |
|---|---|
| `:10` "this machine already has Ledgerline data" | Not triggered: `/var/lib/ledgerline` did not exist |
| `:19` backup timer | `systemctl is-enabled ledgerline-backup.timer` → `disabled`, `is-active` → `inactive`, and `list-timers --all` lists no Ledgerline timer. No `backups/` folder exists on "fresh". |
| `:20` background checks | `/etc/ledgerline/ledgerline.env:14` contains `LEDGERLINE_WATCH_SECONDS=0`. The restored process has `LEDGERLINE_WATCH_SECONDS=0` in its environment and no `ledgerline-watcher` thread (its threads are `python`, 4 `libuv-worker` and an `AnyIO worker`). |

### Health

Health was ok, both after the install and after the restore:

```
{"status":"ok","version":"0.2.0","control_schema":6,"storage":"persistent mount","bank":"local","claude":"not configured","client":"127.0.0.1","forwarded_entries":0,"trusted_hops":1,"edge_proof":"not configured"}
```

There is no `commit` field because `main` (d22f232) is older than the commit that added it. See finding 1.

### `restore_check.py` output, from the drill

```
== restore the backup
restored ['.health', 'control.sqlite3', 'orgs']
== verify the restored books
ledgerline/20261104-174309.tar.gz.enc: control database opens: 3 organizations, 1 accounts, 3 sets of books
  org_683b0279562e: books balanced=True, audit chain ok=True (42 events)
  org_87462c60d17b: books balanced=True, audit chain ok=True (0 events)
  org_f55a3300d342: books balanced=True, audit chain ok=True (19 events)
restore check: PASS (temporary copy deleted)
```

- **Practice company** (`org_683b0279562e`): books balanced, audit chain ok, 42 events. That matches the 42 events in
  "source" after the walkthrough.
- **My company** (`org_f55a3300d342`): books balanced, audit chain ok, 19 events. That matches the 19 in "source".
- **No missing books**: the `MISSING books` line was not printed. 3 organizations had 3 sets of books.

### RECOVERY TIME

```
RECOVERY TIME: 1 minutes from a fresh VM to a healthy, verified Ledgerline
real	0m33.378s
```

This time is **not representative**. Caddy, uv and Node were installed beforehand, and the containers had fast
networking. On an e2-small, expect several more minutes for the Caddy and Node repositories and the frontend build.
The clock also starts only after the VM exists and the files have been copied (finding 13).

### Outbound connections

The restored app made no outbound connection to a payer agent, Airwallex or any other host. Three independent
monitors covered "fresh" for the whole drill and for about 3 minutes afterwards:

1. A packet logger on the host's `docker0` recorded every TCP SYN and UDP flow from 172.17.0.3.
2. The proxy forwarder logged the `CONNECT host:port` line of every HTTPS connection from "fresh".
3. `ss -tunp` ran every 0.5 s inside "fresh" to name the process behind each non-loopback connection.

What they recorded:

- **During install** (17:44:44–17:44:58): only `apt` to the Ubuntu archive (185.125.190.81:80, 91.189.92.23:80) and,
  through the proxy, `pypi.org` (50), `files.pythonhosted.org` (42), `registry.npmjs.org` (15), `github.com`,
  `release-assets.githubusercontent.com` and `releases.astral.sh` (Python 3.14.8). The processes were `http` (apt),
  `uv` and `npm ci`.
- **After the restore** (the service restarted at about 17:45:10 and was still running at 17:47:59, 166 s later):
  **0 TCP SYNs, 0 proxy CONNECTs, and 0 socket rows from `python` or `caddy`.** The ledgerline journal has 24 lines,
  all uvicorn start-up messages; none mention an agent, Airwallex or an HTTP client.
- The only post-restore traffic was 2 DNS lookups (17:45:08, 17:46:08). They came from **Caddy** trying to obtain a
  certificate for `203-0-113-10.sslip.io` from Let's Encrypt and ZeroSSL (`tls.obtain … will retry`). The lookups
  failed in this sandbox. On a real GCE VM they would succeed and Caddy would connect out (finding 7).
- **Limitation.** None of the restored customers has a remote payer-agent URL (`agent_url` is empty in all three
  ledgers), and no organization uses Airwallex. So the only background code that calls out, `watcher.py` (which
  sweeps `airwallex_sandbox` organizations), had nothing to call even before `WATCH_SECONDS=0` turned it off. The
  zero-outbound result is consistent with the code: `watcher.start()` returns early when `seconds <= 0`, and
  `agent_loop.on_arrival` runs only after a person records a payment. But this data did not exercise a configured
  remote agent.

## `restore_check.py` refusals (run on its own in "fresh")

`env PYTHONPATH=/opt/ledgerline/src/backend /opt/ledgerline/venv/bin/python /opt/ledgerline/src/deploy/vm/restore_check.py …`

| Case | Last line | Exit |
|---|---|---|
| Control: right key, right name | `restore check: PASS (temporary copy deleted)` | 0 |
| Wrong key (another random 32-byte key) | `cryptography.exceptions.InvalidTag` | 1 |
| Renamed object: file copied to `20261103-031500.tar.gz.enc`, default name | `cryptography.exceptions.InvalidTag` | 1 |
| Renamed object: original file, name argument `ledgerline/20261103-031500.tar.gz.enc` | `cryptography.exceptions.InvalidTag` | 1 |
| Tampered byte (1 bit flipped at byte 26,052 of 52,105) | `cryptography.exceptions.InvalidTag` | 1 |
| Extra: truncated to 30,000 bytes | `cryptography.exceptions.InvalidTag` | 1 |
| Extra: first 5 bytes changed | `ValueError: not a Ledgerline backup` | 1 |
| Extra: 16-byte key | `ValueError: backup key must be 32 bytes, base64-encoded` | 1 |
| Extra: key file not base64 | `binascii.Error: Only base64 data is allowed` | 1 |

Every case was refused before anything was unpacked. The message is a raw Python traceback that does not say what
to do (finding 11).

## Where step 6 would fail or confuse the owner on Google Cloud

Line numbers are for `main` d22f232. These four files are identical on `deploy/vercel-render` ebd32f2.

1. **The drill restores onto different code than the live site runs.** `docs/SERVER_STEPS.md:163` bundles `main`, and
   `:173` passes `main`. The live VM runs `deploy/vercel-render`, which was 3 commits ahead of `main` during this
   session (ebd32f2 vs d22f232). Data from newer code is then opened by older code. This time it worked because no
   schema change was involved. A migration on the deploy branch would make the drill fail, or prove the wrong thing.
   **Fix:** bundle the commit the live VM runs and pass that commit:
   ```bash
   git fetch origin
   git branch -f drill-src origin/deploy/vercel-render
   git bundle create ledgerline.bundle HEAD drill-src
   ```
   Then pass `drill-src` as the drill's last argument. Compare its commit with the `commit` field of
   `https://35-207-220-110.sslip.io/api/health`, or with `git -C /opt/ledgerline/src log --oneline -1` on the VM.

2. **The bundle has no `HEAD`, so the clone checks out no files.** Running `git bundle create ledgerline.bundle main`
   exactly as `docs/SERVER_STEPS.md:163` says gives a bundle that clones with
   `warning: remote HEAD refers to nonexistent ref, unable to checkout` and 0 files. I reproduced this; with `HEAD main`
   the clone has its files. The warning appears twice in the drill. Inside `setup.sh`, `$APP/src/deploy/vm/checkout.sh`
   then does not exist, its error is hidden by `2>/dev/null` (`deploy/vm/setup.sh:58`), and the fallback fetch
   silently does the job. It works by luck, and the owner sees an alarming warning. **Fix:** add `HEAD` to the bundle
   (as in finding 1). Optionally, `restore_drill.sh:15` could warn when `git -C "$SETUP/src" ls-files | head -1` is
   empty.

3. **`$BUCKET` is never set in step 6.** `docs/SERVER_STEPS.md:171` uses `gs://$BUCKET/…`, but `BUCKET` was set in
   step 1's Cloud Shell session, days earlier, and also included random hex. In a new session `gcloud storage ls
   gs:///ledgerline/` fails, `LATEST` is empty, `gcloud storage cp "" .` fails, and the next lines still run: scp
   without a backup, then the drill dies on `realpath`. **Fix:** at the top of the block, add:
   ```bash
   BUCKET=$(gcloud storage buckets list --format='value(name)' --filter='name~^ledgerline-backups-')
   echo "Bucket: ${BUCKET:-NOT FOUND}"
   ```
   After line 171, add `[ -n "$LATEST" ] || { echo "STOP: no backup found in gs://$BUCKET/ledgerline/"; exit 1; }`.
   `gcloud config set project …` could also be repeated in case Cloud Shell's project changed.

4. **The block keeps going after a failure, then deletes the evidence.** `docs/SERVER_STEPS.md:169-175` is pasted as
   separate commands. If `instances create`, the download, `scp` or the drill fails, the next line still runs. Line 174
   then deletes the VM, so the failed drill's output survives only in scrollback. **Fix:** run the block as a script
   with `set -euo pipefail`, or chain the commands with `&&`. Change the ssh line to
   `… --command "sudo bash restore_drill.sh … 2>&1 | tee drill.log"` and copy `drill.log` back with
   `gcloud compute scp ledgerline-drill:~/drill.log .` before the delete.

5. **No external IP means the drill exits silently.** `deploy/vm/restore_drill.sh:12` runs `curl -s` against the
   metadata server under `set -e`. When that fails, the drill exits with code 6 and prints nothing; I observed this in
   "fresh" before adding the fake metadata endpoint. If the VM has no external IP (for example someone adds
   `--no-address` to `:170` for extra isolation), the metadata URL returns 404 and `curl -s` without `-f` puts the 404
   page into `HOST`. **Fix:**
   `IP=$(curl -fsS -H "Metadata-Flavor: Google" …/external-ip) || { echo "STOP: cannot read this VM's external IP from the metadata server (is it a GCE VM with an external address?)" >&2; exit 2; }`.
   Since `LEDGERLINE_LOCAL_ONLY=1` never serves that hostname, `HOST=drill.invalid` would also work and removes the
   lookup. The external IP is still needed for apt, uv and npm, because there is no Cloud NAT. Step 6 could say so
   next to `:170`, so nobody adds `--no-address`.

6. **A wrong key is found only after the full install.** `deploy/vm/restore_drill.sh:17` installs everything (about
   5–15 minutes on e2-small). Only then does `:26-32` try the key, with a traceback and the app stopped. **Fix:** check
   the key and object name in Cloud Shell before creating the VM. For example, run
   `python3 deploy/vm/restore_check.py "$(basename "$LATEST")" backup.key` from a repository checkout in Cloud Shell,
   with `pip install --user cryptography` and `PYTHONPATH=backend`. That runs the step-1 restore test and catches a
   wrong key in seconds.

7. **Caddy on the drill VM keeps asking Let's Encrypt and ZeroSSL for a certificate.** With `LEDGERLINE_LOCAL_ONLY=1`,
   `deploy/vm/setup.sh:103-109` still writes `Caddyfile.single` for `<drill-ip>.sslip.io` and reloads or restarts
   Caddy. `:49` still opens ports 80 and 443 in iptables. Caddy immediately starts `obtaining certificate` and retries
   for as long as the VM lives (observed: `tls.obtain … will retry`). This is not a payer agent or a provider, but it
   is outbound traffic from a VM that step 6 describes as having "no web access". It also asks a public CA for a
   certificate for an address that is not ours. **Fix:** in `setup.sh`, when `LOCAL_ONLY == 1`, skip the Caddyfile,
   run `systemctl disable --now caddy`, and skip the iptables lines `:48-51`. Then update
   `docs/SERVER_STEPS.md:158` to say Caddy is off.

8. **Passed STOP checks print nothing.** At `deploy/vm/restore_drill.sh:19-20` the owner cannot see that the timer and
   watcher checks ran. **Fix:** after line 20, add
   `echo "ok: backup timer disabled; background checks off (LEDGERLINE_WATCH_SECONDS=0)"`.

9. **Health-check noise looks like a failure.** Each health wait prints `curl: (7) Failed to connect to 127.0.0.1 port
   8000` twice before `{"status":"ok"…}` (`deploy/vm/setup.sh:114`, `deploy/vm/restore_drill.sh:46`). **Fix:** use
   `curl -fs` (without `-S`) inside the loops. The final `curl -fsS` at `restore_drill.sh:47` already reports a real
   failure.

10. **The restore check names organizations only by id.** At `deploy/vm/restore_check.py:57`, `org_683b0279562e`
    tells the owner nothing; here two organizations were both called "My company". **Fix:** read
    `SELECT id, name, kind FROM organizations` at `:34` and print `{name} ({kind}, {id})`.

11. **Refusals show a bare traceback.** A wrong key, renamed file, damaged copy or truncated download all end in
    `cryptography.exceptions.InvalidTag` (`deploy/vm/backup.py:82`, reached from `restore_check.py:27` and
    `restore_drill.sh:32`). A bad key file ends in `binascii.Error`. AES-GCM cannot tell these cases apart, but the
    message can list them. **Fix:** in `decrypt()`, catch `InvalidTag` and raise
    `ValueError(f"cannot decrypt {name}: wrong backup key, the file was renamed (the object name is checked; pass the original name ledgerline/<date>.tar.gz.enc as the 3rd argument), or the copy is damaged or incomplete")`.
    In `restore_check.py`'s `__main__`, print that message without a traceback and exit 1. Do the same for
    `read_key()`'s base64 error.

12. **The key and backup stay behind if the block stops early.** The key is written into Cloud Shell's persistent
    `$HOME` (`docs/SERVER_STEPS.md:166`, "put the backup key … in `backup.key`") and removed only by `:175`, the last
    line. If anything stops the block earlier, the key and the backup stay on Cloud Shell's persistent disk. On the
    drill VM, `restore_drill.sh:50` deletes only its working copy; `~/backup.key` and the `.enc` file remain until the
    VM is deleted, and `:174` might fail. **Fix:** tell the owner to create the file with
    `umask 077; cat > backup.key` (paste, Enter, Ctrl-D), and add
    `trap 'rm -f backup.key "$(basename "${LATEST:-x}")" ledgerline.bundle' EXIT` when the block runs as a script.
    In the drill, `rm -f "$3" "$2"` after the check, or tell the owner to pass `--command "… ; rm -f ~/backup.key ~/*.tar.gz.enc"`.

13. **The recovery time leaves out most of a real recovery.** `deploy/vm/restore_drill.sh:11` starts the clock after
    the VM exists, the backup has been downloaded and the files have been copied. It also leaves out moving the
    reserved address, Caddy's certificate and reconnecting Airwallex. Yet `:51` says "from a fresh VM", and
    `docs/SERVER_STEPS.md:155` says "how long a full restore takes". The output also says "1 minutes". **Fix:** print
    `RECOVERY TIME: N minute(s) from files on a new VM to a healthy, verified Ledgerline (not counting VM creation,
    download, address move, certificate or Airwallex)`. In step 6, also record `date` before `:170` and after `:173`,
    so the owner can report the end-to-end time too.

14. **The first `scp` to a new VM often fails.** `docs/SERVER_STEPS.md:172` runs `gcloud compute scp` right after
    `instances create` returns, while sshd and the guest agent are still starting. On first use, Cloud Shell also asks
    for an SSH key passphrase. A failure there is then hidden by the next lines (finding 4). **Fix:** before line 172,
    add `until gcloud compute ssh ledgerline-drill --zone=$ZONE --command true; do sleep 10; done`.

15. **A long ssh session may be cut off.** The ssh command at `:173` runs for about 5–15 minutes. If Cloud Shell
    disconnects or goes idle, the drill is cut off. **Fix:** run it under
    `nohup sudo bash restore_drill.sh … > drill.log 2>&1 &` and poll `tail drill.log`, or use `tmux`, together with the
    `tee` and copy-back from finding 4.

Not a problem, checked: the drill disables the backup timer and sets `WATCH_SECONDS=0` before any restored data
exists (`setup.sh:89,106`). `--no-service-account --no-scopes` (`:170`) still lets the metadata server return the
external IP. `gcloud storage cp` keeps the object's file name, so the name check in finding 11 passes on the normal
path.
