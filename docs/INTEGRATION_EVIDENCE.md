# Integration evidence

Only observed results are listed. Mocked or simulated calls are labelled as such and are not live verification.

## Live, observed (27 Oct 2026)

| What | Evidence |
|---|---|
| Public app | `GET https://ledgerline-black-iota.vercel.app/api/health` → `{"status":"ok", ...}` through Vercel's same-origin rewrite to Render (response header `x-vercel-id: bom1::...`); CSP, HSTS and `X-Frame-Options: DENY` present on the page |
| Render free backend | `https://ledgerline-api-4dt3.onrender.com/api/health` 200 |
| Session cookie over HTTPS | Sign-up response `Set-Cookie: ll_session=...; HttpOnly; Secure; SameSite=strict; Path=/api` |
| Real MCP subprocess on the free instance | `POST /api/deposits/DEP-1006/ask-agent` → verification `verified` (stdio transport, 8.6 s on 0.1 CPU) |
| Real PostgreSQL 17 | GitHub Actions job `postgres` (service container) runs `tests/test_postgres.py` and the whole suite on PostgreSQL; see the Actions run for the deployed commit |

## Not live yet (no credentials)

| Integration | State | Needed |
|---|---|---|
| Airwallex sandbox | Adapter implemented; payloads checked against airwallex.com/docs (transfers and conversions amounts as strings, deposit events at `data.object`, `global_account_id`, transfer statuses including approval states); read-only readiness check (login → global accounts → balances) unit-tested with a mock transport only | `AIRWALLEX_CLIENT_ID`, `AIRWALLEX_API_KEY` on Render; `LEDGERLINE_SANDBOX_ORGS` to allow one operator organization |
| Signed Airwallex webhooks | HMAC-SHA256 over `x-timestamp` + raw body per the docs, dedupe by event id; tested with locally signed events only | Webhook URL registered in the sandbox web app + secret in Settings |
| Claude API extraction | Strict tool schema, output validated (`typed_proposal`), per-organization daily cap; tested with a stubbed client only | `ANTHROPIC_API_KEY` on Render |
| Payment links | Sandbox `POST /pa/payment_links/create` payload matches docs; locally a labelled draft, never a fake URL | Airwallex credentials with payment links enabled |

When credentials are added, Settings → Integrations → **Check connections** performs the live calls and reports the provider's actual response; record those (with ids redacted) here.
