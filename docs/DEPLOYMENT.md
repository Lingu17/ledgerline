# Deploying Ledgerline (Vercel + Render)

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
3. No environment variables are needed on Vercel: there are no browser-side secrets.

## Proxy-aware sign-in throttling

Requests reach the app via Vercel's edge and Render's proxy, so the socket peer is a proxy. `LEDGERLINE_TRUSTED_PROXY_HOPS=2` makes the app read the client from `X-Forwarded-For` counting from the trusted (right) end; entries a client prepends are ignored. Without this, five typos by one judge would lock every judge out for 15 minutes.

## Airwallex sandbox (optional, needs your credentials)

Following the Airwallex hackathon guide (airwallexdev.com): create a sandbox account at sandbox.airwallex.com, then Account → Developer → API keys. Put the Client ID and API key into the Render service's environment (never into Git or Vercel), redeploy, and in Ledgerline open Settings → Integrations → **Check connections**. The check is read-only: it signs in, lists global accounts and lists current balances, and reports the real response. To run an organization against the sandbox, an owner switches its bank mode in Settings, enters its global account ids and webhook secret, and registers the organization's webhook URL (`https://<vercel origin>/api/webhooks/airwallex/<org_id>`) in the sandbox web app.

## Verifying a deployment

```
backend\.venv\Scripts\python scripts\smoke_deploy.py https://<vercel origin> --save %TEMP%\ledgerline-smoke.json
# restart the Render service (Manual Deploy → Restart), then:
backend\.venv\Scripts\python scripts\smoke_deploy.py https://<vercel origin> --verify %TEMP%\ledgerline-smoke.json
```

The state file contains a throwaway test password; keep it outside the repository.
