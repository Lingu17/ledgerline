# Deploying Ledgerline

**Deployed setup (27 Oct 2026): Vercel Hobby (frontend) + Render Free (API) + Neon Free (PostgreSQL).** No card, no paid resources. Observed results are in `DEPLOYMENT_HANDOFF.md`.

```
Browser ──https──> Vercel (static React app, frontend/)
                     │  /api/*  same-origin route (frontend/vercel.json) + x-ledgerline-edge header from LEDGERLINE_EDGE_SECRET
                     ▼
                   Render Free web service "ledgerline-api" (backend/, Singapore)
                     │  psycopg pool, TLS (sslmode=require), direct endpoint (no pooler)
                     ▼
                   Neon Free PostgreSQL (ap-southeast-1): one schema per logical database
```

Free-tier behaviour: Render Free spins down when idle (first request can take 50 s or more); Neon Free suspends compute after 5 idle minutes and has 100 CU-hours per project per month. Nothing here is promised to stay free or always on.

## Setup (Vercel + Render Free + Neon)

1. **Neon:** create a project in AWS Asia Pacific (Singapore). In *Connect*, turn **Connection pooling off** so the hostname has no `-pooler` (the app refuses pooler endpoints because they drop the per-connection `search_path`). The string must keep `sslmode=require` (or `verify-ca`/`verify-full`; the app refuses weaker modes for remote hosts).
2. **Render:** a Python web service from this repository, root `backend`, build `pip install --no-cache-dir -r requirements-lock.txt`, start `python -m ledgerline`, health check `/api/health`. Environment:
   - `LEDGERLINE_HOST=0.0.0.0`, `LEDGERLINE_COOKIE_SECURE=1`, `LEDGERLINE_LOG_LEVEL=INFO`, `PYTHON_VERSION=3.14.8`
   - `LEDGERLINE_ALLOWED_ORIGINS` and `LEDGERLINE_PUBLIC_URL` = the Vercel origin (no trailing slash)
   - `LEDGERLINE_TRUSTED_PROXY_HOPS=4` (measured: Vercel adds 1 entry, Render's proxy 3)
   - `LEDGERLINE_SECRET_KEY`: Render's *Generate* (32+ characters). It derives the key that encrypts payer-agent signing keys in the database: **never change or copy it**, or the stored identities become undecryptable.
   - `LEDGERLINE_DATABASE_URL`: the Neon direct string, pasted by the account owner (never into chat or Git).
   - `LEDGERLINE_REQUIRE_DATABASE=1`: refuse to start without a database instead of falling back to local SQLite.
   - `LEDGERLINE_EDGE_SECRET`: Render's *Generate*.
   Render redeploys automatically only for commits that change files under `backend/`.
3. **Vercel:** import the repository with **Root Directory `frontend`**; `frontend/vercel.json` sets install/build/output, security headers and the `/api` route to the Render URL. Add **one** environment variable: `LEDGERLINE_EDGE_SECRET` (Production, Secret) = exactly the Render value, then redeploy production. There are no browser-side secrets.
4. **Check:** `GET https://<vercel origin>/api/health` must show `"storage":"postgresql"`, `"edge_proof":"valid"` and your own public address as `client`. `edge_proof` is `missing`, `invalid`, `invalid: length differs` or `invalid: unsubstituted placeholder` otherwise; it never shows the value.

The two sections below are documented alternatives that are **not deployed**.

## Alternative (not deployed): Oracle Cloud Always Free VM

1. Create an Oracle Cloud account (card verification; Always Free resources are not charged) and sign in.
2. Compute → Instances → Create: image **Canonical Ubuntu 24.04**, shape **VM.Standard.E2.1.Micro** (Always Free-eligible; or Ampere A1 if available), public IPv4, and paste the deploy SSH **public** key.
3. Networking → the instance's subnet → Security List → add ingress rules for TCP **80** and **443** from `0.0.0.0/0`.
4. With the public IP `A.B.C.D`, the hostname is `A-B-C-D.sslip.io` (resolves to the IP; Let's Encrypt works on it). Then:
   ```
   ssh ubuntu@A.B.C.D
   curl -fsSLO https://raw.githubusercontent.com/Lingu17/ledgerline/<tested-commit>/deploy/vm/setup.sh
   sudo bash setup.sh A-B-C-D.sslip.io https://<vercel-origin> <tested-commit>
   ```
5. Set the rewrite destination in `frontend/vercel.json` to `https://A-B-C-D.sslip.io/api/:path*`, push, and import the repo into Vercel with **Root Directory `frontend`**.
6. Updates: `sudo bash /opt/ledgerline/src/deploy/vm/update.sh <tested-commit>`. Optional API keys: edit `/etc/ledgerline/ledgerline.env` (root-owned, mode 640) and `sudo systemctl restart ledgerline`.

Data: `/var/lib/ledgerline` (mode 700, owned by the service user) on the boot volume, which persists across reboots and service restarts. Backups: `ledgerline-backup.timer` runs `deploy/vm/backup.py` daily at 03:15, 7 kept, under `/var/lib/ledgerline/backups`. These protect against bad writes, not against losing the volume.

Proxy note: Caddy appends the Vercel edge address to `X-Forwarded-For`, and the app (`LEDGERLINE_TRUSTED_PROXY_HOPS=2`) uses the browser address Vercel recorded. `GET /api/health` returns `client` so this can be checked. A client calling the VM hostname directly (bypassing Vercel) can influence the address used for the per-IP sign-in budget. The per-account budget (5 failures per email per 15 minutes) still applies.

## Paid alternative (not deployed): Render Starter with a disk

```
Browser ──https──> Vercel (static React app, frontend/)
                     │  /api/*  same-origin rewrite (frontend/vercel.json)
                     ▼
                   Render web service "ledgerline-api" (backend/, render.yaml)
                     │
                     ▼
                   Render persistent disk mounted at /var/data
                     └─ ledgerline/control.sqlite3, orgs/<org_id>/{ledgerline.sqlite3, local_bank.sqlite3, payer_agents/*.key}
```

Browsers only ever talk to the Vercel origin. The session cookie (`ll_session`: HttpOnly, Secure, SameSite=Strict, Path=/api) is therefore first-party, CSRF tokens and the Origin allow-list work unchanged, and no CORS is needed.

## Cost

| Item | Plan | Price |
|---|---|---|
| Render workspace | Hobby | $0 |
| Render web service | Starter (0.5 CPU, 512 MB) | $7.00 / month, prorated by the second |
| Render persistent disk | 1 GB SSD | $0.25 / month |
| Vercel | Hobby | $0 |
| **Total** | | **$7.25 / month** (Render pricing page, checked 27 Oct 2026) |

A disk is mandatory: Render's free instances have ephemeral storage, which would lose every account, organization and signing key on each restart or deploy. A service with a disk runs as one instance and restarts without zero-downtime deploys (a few seconds of 502 during deploys; the UI shows "server is not reachable right now").

## Backend on Render

1. Render dashboard → **New → Blueprint** → repository `Lingu17/ledgerline` → it reads `render.yaml` (service `ledgerline-api`, Starter, Singapore, disk `ledgerline-data` 1 GB at `/var/data`, health check `/api/health`).
2. Fill the variables marked `sync: false`:
   - `LEDGERLINE_ALLOWED_ORIGINS` = the Vercel production origin, e.g. `https://ledgerline.vercel.app` (no trailing slash)
   - `LEDGERLINE_PUBLIC_URL` = the same origin (used for OAuth redirect URIs)
   - `AIRWALLEX_CLIENT_ID`, `AIRWALLEX_API_KEY`, `ANTHROPIC_API_KEY`: leave empty until you have real credentials. They are server-side only and never reach the browser or Git.
3. Deploy. Startup refuses to run unless `/var/data` is a real mount (`LEDGERLINE_REQUIRE_PERSISTENT_MOUNT`), so data can never silently land on ephemeral disk. Migrations run at startup (Render disks are not attached during build or pre-deploy). `GET /api/health` reports `storage: "persistent mount"`.

## Frontend on Vercel

1. Vercel → **Add New → Project** → import `Lingu17/ledgerline`, **Root Directory `frontend`** (framework Vite; `frontend/vercel.json` sets install/build/output).
2. If the Render service URL is not `https://ledgerline-api.onrender.com`, change the rewrite destination in `frontend/vercel.json` and push.
3. Set `LEDGERLINE_EDGE_SECRET` (Production, Secret) to the same value as on the backend and redeploy; it is the only Vercel variable and never reaches the browser.

## Proxy-aware sign-in throttling

Requests reach the app via Vercel's edge and Render's proxy, so the socket peer is a proxy. The app reads the client from `X-Forwarded-For`, counting `LEDGERLINE_TRUSTED_PROXY_HOPS` entries from the trusted (right) end; entries a client prepends are ignored. On the deployed Vercel → Render path the measured value is **4**. With `LEDGERLINE_EDGE_SECRET` set, the header is trusted only on requests carrying the matching `x-ledgerline-edge` proof (added by Vercel), so a client calling the Render URL directly cannot choose its throttling identity; a missing, malformed or wrong proof falls back to the nearest address. If Vercel's value does not match, every user is throttled as one address (check `edge_proof` in `/api/health`).

## Airwallex sandbox (optional, needs your credentials)

Following the Airwallex hackathon guide (airwallexdev.com): create a sandbox account at sandbox.airwallex.com, then Account → Developer → API keys. Put the Client ID and API key into the Render service's environment (never into Git or Vercel), redeploy, and in Ledgerline open Settings → Integrations → **Check connections**. The check is read-only: it signs in, lists global accounts and lists current balances, and reports the real response. To run an organization against the sandbox, an owner switches its bank mode in Settings, enters its global account ids and webhook secret, and registers the organization's webhook URL (`https://<vercel origin>/api/webhooks/airwallex/<org_id>`) in the sandbox web app.

## Verifying a deployment

```
backend\.venv\Scripts\python scripts\smoke_deploy.py https://<vercel origin> --save %TEMP%\ledgerline-smoke.json
# replace the backend process (a redeploy, or Restart service and wait until the instance id in the Render logs changes), then:
backend\.venv\Scripts\python scripts\smoke_deploy.py https://<vercel origin> --verify %TEMP%\ledgerline-smoke.json
```

The state file contains a throwaway test password; keep it outside the repository.

## Google Cloud single host (used for the live app)

1. Create a VM (e2-small, Ubuntu 24.04, 20 GB balanced disk, allow HTTP/HTTPS, reserve a static IP, add the deploy public SSH key).
2. Private repository: `git bundle create ledgerline.bundle HEAD <branch>`; `scp` it and `deploy/vm/setup.sh` to the VM; `sudo install -m 644 ledgerline.bundle /srv/ledgerline.bundle`.
3. `sudo LEDGERLINE_REPO=/srv/ledgerline.bundle bash setup.sh <A-B-C-D>.sslip.io self <commit>`: builds the site, serves site + API from one origin over HTTPS, stores data on the VM disk.
4. Updates: copy a new bundle to `/srv/ledgerline.bundle`, then `sudo bash /opt/ledgerline/src/deploy/vm/update.sh <commit>`.
5. Keys: `sudo nano /etc/ledgerline/ledgerline.env` (AIRWALLEX_CLIENT_ID, AIRWALLEX_API_KEY, ANTHROPIC_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, LEDGERLINE_SANDBOX_ORGS), then `sudo systemctl restart ledgerline`.
