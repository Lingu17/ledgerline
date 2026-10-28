# Integration evidence

Only observed results are listed. Mocked or simulated calls are labelled as such and are not live verification.

## Live, observed (27 Oct 2026)

Update independently verified by Codex on 28 Oct at code `a528ca9`: public synthetic workflow **32/32**; authenticated edge proof valid with forwarding/proof spoof refusal; actual Render restart confirmed by instance `b9fnc` → `djx6n`, followed by **8/8** saved-account/data/ledger/refund/signing-key checks. GitHub Actions run [40569405112](https://github.com/Lingu17/ledgerline/actions/runs/40569405112) passed all five jobs, including PostgreSQL. Isolated Neon full walkthrough/new-app continuity passed in 217.73 seconds. This does not constitute Airwallex or Anthropic integration verification.

| What | Evidence |
|---|---|
| Public app | `GET https://ledgerline-black-iota.vercel.app/api/health` → `{"status":"ok", ...}` through Vercel's same-origin rewrite to Render (response header `x-vercel-id: bom1::...`); CSP, HSTS and `X-Frame-Options: DENY` present on the page |
| Render free backend | `https://ledgerline-api-4dt3.onrender.com/api/health` 200 |
| Session cookie over HTTPS | Sign-up response `Set-Cookie: ll_session=...; HttpOnly; Secure; SameSite=strict; Path=/api` |
| Real MCP subprocess on the free instance | `POST /api/deposits/DEP-1006/ask-agent` → verification `verified` (stdio transport; completed calls took 8.4-9.3 s on Render Free). One call in a Codex smoke run (`DEP-1004`) ended in a connection reset with no server log line; cause not established (see `DEPLOYMENT_HANDOFF.md`); Codex's stable rerun passed 32/32 |
| Neon PostgreSQL storage | `/api/health` → `"storage":"postgresql"`, `control_schema` 3; `scripts/smoke_deploy.py` through the Vercel URL 32/32 (Claude; Codex rerun 32/32 as reported); data created on one Render instance read back 8/8 on another after a redeploy |
| Edge proof (Vercel → Render) | **Verified valid on 28 Oct** after corrected deployment; public forwarding-header identity stable under spoofing, direct-origin forged proof refused. No signing-encryption key change. |
| Real PostgreSQL 17 | GitHub Actions job `postgres` (service container) runs `tests/test_postgres.py` and the whole suite on PostgreSQL; see the Actions run for the deployed commit |

## External integration state — observed 28 October 2026

| Integration | State | Needed |
|---|---|---|
| Airwallex sandbox | **Real read-only connection observed.** Owner readiness returned authentication success, two global accounts (ids redacted) and wallet balances. Dedicated EUR account created in Germany; only the approved operator organization is allowlisted. **One simulated deposit settled and reconciled (28 Oct, code `a0fe23a`, CI run 40737882028 all five jobs passed):** owner form sent EUR 1.23, reference `INV-2301`; Airwallex returned PENDING; its sandbox notice email then reported the deposit settled to the EUR global account (deposit id begins `ac4ef9a6`). The receipt sync ingested it once as `DEP-E38811649D` (source `airwallex_sandbox_poll`, provider id matches), exact-matched by rule to INV-2301 (remaining 0, shown as Paid); per-currency ledger checks balanced for EUR, GBP and USD; one deposit, zero escalations, zero duplicate payouts. | FX and transfer/refund execution still need real response evidence. Settlement reached Ledgerline by polling, not by a signed webhook. |
| Signed Airwallex webhooks | Approved deposit.settled subscription registered. After saving, Ledgerline displays **organization Airwallex secret**, the Set hint, and an empty write-only secret input. HMAC over raw bytes and event-id dedupe tested locally. | Actual external delivery unverified. A Send test event attempt produced no observed receipt; it is not a pass. Test-event signatures may use a separate secret per official docs; never trust a caller-supplied secret header as authority. |
| Claude API extraction | Strict tool schema, output validated (`typed_proposal`); each call reserved in the database before dispatch against a per-organization and a server-wide daily cap (failed calls count); tested with a stubbed client only, including 6 simultaneous requests at a cap of 1 | `ANTHROPIC_API_KEY` on Render |
| Payment links | Adapter implemented; locally a labelled draft, never a fake URL | Scoped key/API capability and a real call remain unverified. |

Google sign-in: configured provider and exact public callback verified; the user completed real Google login and organization onboarding. Google OAuth Testing mode may restrict judge accounts; email/password remains available. Apple is hidden from login by user choice and no paid membership was purchased.

## Independent sandbox input regressions

Reviewed against https://airwallexdev.com/ and official https://www.airwallex.com/docs/api/simulation/deposits/create plus https://www.airwallex.com/docs/developer-tools/webhooks/listen-for-webhook-events . The developer lab is guidance, not the field-level API authority.

- Before simulation, read the Global Account and require a dedicated matching receiving currency; refuse unknown/multi-currency ambiguity. Never send a fictitious currency parameter.
- Positive integer minor-unit inputs become major-unit JSON numbers; booleans, zero, negatives and fractional minor units are rejected before network dispatch.
- Preserve payer/reference hints for both flat and nested webhook deposit envelopes.
- Keep sandbox simulation PENDING until authenticated settled receipt. Preserve durable attempt markers so ambiguous retries cannot create another simulation automatically.
- Reject malformed/oversized timestamp and non-hex signature headers with controlled 401 responses.

These regression tests use simulated providers. They do not prove a successful live sandbox money action.
