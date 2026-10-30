# Deploying Ledgerline

**Production (since 29 Oct 2026): one Google Cloud VM serves the website, the API and the data.** Live at https://35-207-220-110.sslip.io. The current deployment record (commit, checks, persistence) is in [DEPLOYMENT_HANDOFF](DEPLOYMENT_HANDOFF.md).

```
Browser ──HTTPS──> Caddy on the VM (35-207-220-110.sslip.io, Let's Encrypt, HSTS, CSP)
                     │  reverse_proxy 127.0.0.1:8000 (Caddy replaces any client X-Forwarded-For)
                     ▼
                   ledgerline.service (FastAPI, unprivileged user, serves /api and the built React app)
                     │
                     ▼
                   /var/lib/ledgerline (mode 700): control.sqlite3, orgs/<org_id>/{ledgerline.sqlite3, local_bank.sqlite3, payer_agents/}
                     └─ backups/<timestamp>/ nightly at 03:15 UTC, 7 kept
```

There is no runtime dependency on Vercel, Render, Neon or any tunnel. Outbound calls go only to Airwallex (sandbox), Anthropic and Google sign-in, and only when their keys are configured.

## The VM

| Item | Value |
|---|---|
| Project / zone | `project-0b143378-307b-4214-818`, asia-south1-a (Mumbai) |
| Machine | e2-small (2 vCPU shared, 2 GB), Ubuntu 24.04 LTS, 20 GB balanced persistent disk, Standard network tier |
| Address | static external IP `ledgerline-ip` = 35.207.220.110; hostname `35-207-220-110.sslip.io` (resolves to the IP; Let's Encrypt works on it) |
| Open ports | 22 (SSH), 80 (redirects to HTTPS), 443. The app port 8000, Caddy admin 2019 and the Ops Agent ports are not reachable from outside (checked 29 Oct) |
| Cost | console estimate about USD 17/month plus the static IP, paid from the Free Trial credit (₹28,797, ends 28 Jan 2027). Billing showed ₹0.00 used on 29 Oct (usage appears with a delay). Budget alert ₹2,000/month at 50/90/100/150% |

When the Free Trial ends the VM is stopped unless the billing account is upgraded. Nothing here upgrades it.

## First install

1. Create the VM (as above), allow HTTP/HTTPS, reserve a static IP and add the deploy **public** SSH key.
2. The repository is private, so ship a git bundle instead of cloning:
   ```
   git bundle create ledgerline.bundle HEAD <branch>
   scp ledgerline.bundle deploy/vm/setup.sh <user>@<ip>:/tmp/
   sudo install -m 644 /tmp/ledgerline.bundle /srv/ledgerline.bundle
   sudo LEDGERLINE_REPO=/srv/ledgerline.bundle bash /tmp/setup.sh <A-B-C-D>.sslip.io self <commit>
   ```
   `self` selects single-host mode: the frontend is built on the VM with Node 22 and served by the API from the same origin; Caddy uses `deploy/vm/Caddyfile.single`, trusts no upstream proxy and `LEDGERLINE_TRUSTED_PROXY_HOPS=1`. The script installs Python 3.14 with the locked requirements, creates the `ledgerline` service user, the systemd units and the backup timer, opens 80/443 in the host firewall, and exits non-zero unless both the local health check and public HTTPS succeed.
3. Keys (the account owner types them; never into chat or Git):
   ```
   sudo nano /etc/ledgerline/ledgerline.env   # AIRWALLEX_CLIENT_ID, AIRWALLEX_API_KEY, ANTHROPIC_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
   sudo systemctl restart ledgerline
   ```
   `LEDGERLINE_SANDBOX_ORGS` lists the only organization ids that may use the Airwallex credentials (the operator's own organization). The file is root-owned, mode 640, group `ledgerline`.
4. Google sign-in: add `https://<host>` as an authorized JavaScript origin and `https://<host>/api/auth/oauth/google/callback` as a redirect URI on the OAuth client.

## Updates

```
git bundle create ledgerline.bundle HEAD <branch>      # then copy to /srv/ledgerline.bundle as above
sudo bash /opt/ledgerline/src/deploy/vm/update.sh <commit>
```

`update.sh` checks out exactly that commit (refusing if the checkout has local changes), installs the locked requirements, rebuilds the frontend, restarts the service and waits for health. Data and keys are untouched.

## Verifying a deployment

```
backend\.venv\Scripts\python scripts\smoke_deploy.py https://<host> --save %TEMP%\ledgerline-smoke.json
# restart the service, reboot the VM or redeploy, then:
backend\.venv\Scripts\python scripts\smoke_deploy.py https://<host> --verify %TEMP%\ledgerline-smoke.json
```

The save run performs 32 checks with throwaway accounts; the verify run checks that the accounts, data, ledger, the refund lifecycle and payer-agent signing keys survived. The state file holds a throwaway password; keep it outside the repository. Also check `GET /api/health`: `storage` is `persistent mount` and `client` is your real address even if you send a forged `X-Forwarded-For`.

## Backups and restore

`ledgerline-backup.timer` runs `deploy/vm/backup.py` daily at 03:15 UTC as the service user. It uses SQLite's online backup API (consistent while the service runs) for every database and copies the payer-agent key files, into `/var/lib/ledgerline/backups/<timestamp>/`, keeping 7.

Restore: `sudo systemctl stop ledgerline`, copy the snapshot's files over `/var/lib/ledgerline/` (keep owner `ledgerline`), `sudo systemctl start ledgerline`. An isolated restore test on 29 Oct copied the newest snapshot to a scratch directory, passed `PRAGMA integrity_check` on all 7 databases with row counts equal to live, restored the payer key file and served health and authentication from a second instance on the copy.

Limitation: backups live on the same persistent disk, so they protect against bad writes and mistakes, not against losing the disk or the project. A Compute Engine snapshot schedule or an off-VM copy would cover that (it would use trial credit and has not been set up).

## Proxy and client addresses

In single-host mode the browser connects to Caddy directly. Caddy overwrites `X-Forwarded-For` with the real peer, and the app trusts exactly one hop, so a client cannot choose the address used for the per-IP sign-in budget (verified: a forged header was ignored). The per-account budget (5 failures per email per 15 minutes) applies as well.

## Earlier hosting (retired)

From 27 to 29 Oct 2026 the app ran on Vercel Hobby (frontend and `/api` proxy) + Render Free (API) + Neon Free (PostgreSQL). On 30 Oct, after the Google Cloud host was verified independent of it, the owner approved retirement: the Vercel project, the Render service and the Neon project were deleted, their Vercel URLs were removed from the Google OAuth client, and their configuration files (`frontend/vercel.json`, `render.yaml`) were removed from the repository. The Airwallex sandbox has a single webhook, pointing at the Google Cloud host.

The PostgreSQL storage mode stays in the code and is tested in CI on PostgreSQL 17 (`LEDGERLINE_DATABASE_URL`, direct non-pooler endpoint, `sslmode=require`; `LEDGERLINE_SECRET_KEY` encrypts payer keys in the database and must never change for an existing database). It is not used in production.
