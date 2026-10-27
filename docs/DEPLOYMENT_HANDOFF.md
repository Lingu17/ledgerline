# Deployment handoff (Claude → Codex)

Hosting feasibility (27 Oct 2026, observed): Oracle Always Free and alwaysdata free both require card verification at sign-up; PythonAnywhere free (account `Lingu10`) blocks outbound HTTPS to `api.sandbox.airwallex.com` (curl from its console: no connection), reaches `api.anthropic.com` (HTTP 401 without key) and PyPI, and needs an account API token before an ASGI site can be created. Render with a disk ($7.25/month) is the only checked option that meets every requirement. Codex review findings 1, 2, 3 and 5 are fixed in `d64722a`; finding 4 is this section; finding 6 (live evidence) waits for a deployment.

Status: **prepared, not yet deployed.** The user chose the free option: Oracle Cloud Always Free VM for the backend (`deploy/vm/`), Vercel Hobby for the frontend; Render (`render.yaml`, $7.25/month) is kept only as a documented paid alternative and was not purchased. Waiting for the user to create the Oracle account and sign in to Oracle and Vercel (Claude does not create accounts or enter passwords). Branch `deploy/vercel-render` at `6442442` adds the VM kit (setup.sh, hardened systemd unit, Caddy auto-HTTPS on sslip.io, nightly SQLite backups, update.sh). A deploy SSH key pair was generated locally at `~/.ssh/ledgerline_oracle` (private key never leaves this machine).

## Done

- Branch `deploy/vercel-render`, commit `ae2dad1`, pushed to `Lingu17/ledgerline` (not yet merged to `main`).
- `render.yaml`: `ledgerline-api`, Python 3.14.8, Starter plan, Singapore, 1 GB disk `ledgerline-data` at `/var/data`, `LEDGERLINE_DATA_DIR=/var/data/ledgerline`, `LEDGERLINE_REQUIRE_PERSISTENT_MOUNT=/var/data` (the app refuses to start otherwise), health check `/api/health`, `LEDGERLINE_COOKIE_SECURE=1`, `LEDGERLINE_TRUSTED_PROXY_HOPS=2`; origin, public URL and API keys are `sync: false` (set in the dashboard, never in Git).
- `frontend/vercel.json`: Vite build from `frontend/`, same-origin rewrite `/api/:path*` → `https://ledgerline-api.onrender.com/api/:path*`, HSTS/CSP/frame/referrer headers.
- Backend: `/api/health`, `PORT` support, persistent-mount guard, proxy-aware client address for sign-in throttling, read-only Airwallex readiness check (login, global accounts, balances) per airwallexdev.com.
- Frontend: readable "server not reachable" message for gateway errors and network failures.
- `scripts/smoke_deploy.py` (deployed probe + `--verify` after restart), `docs/DEPLOYMENT.md`.

## Verified locally (27 Oct 2026)

- Backend `pytest`: **180 passed**. Frontend build OK. Browser suite `npm run e2e`: **9 passed**.
- Production-settings simulation: backend with `LEDGERLINE_COOKIE_SECURE=1`, origin allow-list and trusted proxy hops, behind a same-origin `/api` proxy (Vite preview standing in for Vercel). In the browser: sample sign-up → Inbox, session survives reload, cookie not readable by JavaScript, MCP payer-agent evidence **verified** through the proxy, mutation without CSRF token **403**.

## Cost to approve

Render Hobby workspace $0 + Starter web service $7.00/month + 1 GB disk $0.25/month = **$7.25/month** (prorated by the second; render.com/pricing, checked 27 Oct 2026). Vercel Hobby $0.

## Not yet done

Deployment, deployed tests, restart persistence check, merge to `main`, final URLs. Airwallex sandbox and Claude API remain unconfigured and untested (no credentials).
