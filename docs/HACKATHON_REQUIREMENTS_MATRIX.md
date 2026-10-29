# Hackathon requirements matrix

Audit updated: 29 Oct 2026; historical evidence dated below. Initial audit: 27 Oct 2026 (build phase day 1; deadline 13 Nov 2026, 11:59 PM IST). Sources: HackerEarth event page (read in the browser), airwallexdev.com and /guide, docs/original-proposal.txt, BUILD_BRIEF, SAAS_REQUIREMENTS, PRODUCT_POLISH, CODEX_REVIEW_FINDINGS, INDEPENDENT_REVIEW, and the code at branch `deploy/vercel-render`.

Status key: **Done+tested** = implemented with automated tests passing locally · **Live** = verified against the real external service · **Partial** · **Missing** · **Blocked** = needs something only the user/organizer can provide.

Observed on 28 Oct 2026: deployment, Google sign-in and owner-only Airwallex read-only authentication/accounts/balances are connected. The approved deposit webhook is registered and its secret saved. Sandbox deposits (settled, reconciled) and one EUR→GBP FX conversion (settled) were executed live on 28 Oct; a refund awaits a second approver. Signed webhook delivery remains unverified. Anthropic key is set; the first real call was refused for missing account credit. Configuration is not execution evidence.

Final reviewed runtime `9f07166`: [CI40734890246](https://github.com/Lingu17/ledgerline/actions/runs/40734890246) all five jobs succeeded, including253/253 whole-backend PostgreSQL tests and13/13 PostgreSQL-specific tests. Final public smoke32/32; redeploy continuity8/8 after confirmed instance replacement; concurrent first-page API reads5/5. HackerEarth Build Phase still has0 submissions (read-only observation); detailed submission fields/rubric are not certified. No source-sharing permission or public repository visibility change was made.

## A. Event requirements (HackerEarth / Airwallex)

| # | Requirement (source) | Status | Evidence / gap |
|---|---|---|---|
| A1 | Build within the build phase, 27 Oct to 13 Nov 2026 IST (event page) | In progress | Shortlisted; build-phase submission is not to be saved or submitted by Claude |
| A2 | Submission content: tracks, judging criteria and submission fields (event page) | **Unknown** | The page's Tracks, Key Dates and Prizes sections render empty ("."); an admin says Claude credits arrive in the build phase. Check again before submitting |
| A3 | Sandbox only, no real money (guide) | Done+tested | Local simulated bank by default; Airwallex adapter is sandbox base URL only (`providers/airwallex.py`) |
| A4 | Credentials in environment variables, never committed (guide) | Done+tested | `config.py` reads named env keys only; `.env` gitignored; deploy docs put keys on the server |
| A5 | Demo shows goal, initial plan, new information, revised decision, resulting balance/status; ends with a money action or escalation (guide) | Done+tested | Plan versions, evidence and revised plans stored per deposit and shown in Payments; six-payment walkthrough; accuracy harness checks the walkthrough outcome 25 times |
| A6 | Amounts, limits, reserves and state transitions in code, not prompts (guide) | Done+tested | `matching.py`, policy in DB; Claude only proposes typed tools, validated (`typed_proposal`) and never authoritative |
| A7 | State which actions need human approval (guide) | Done+tested | Approvals page; refunds over the auto limit need a second person (four-eyes test) |
| A8 | Webhooks: verify signature on raw bytes, dedupe by event id, tolerate out-of-order (guide/docs) | Done+tested | HMAC-SHA256(x-timestamp + raw body) per official docs; `webhook_events` dedupe; deposits idempotent on provider id; envelope `data.object` now accepted (fixed 27 Oct after doc check) |
| A9 | Stable `request_id` reused on retries (guide) | Done+tested | UUIDv5 per operation; ambiguous results looked up by request_id |
| A10 | Amounts in major units (guide) | Done+tested | Exact decimal strings for transfers/conversions per API reference (fixed 27 Oct); integer minor units internally |
| A11 | Verify connection: list global accounts, simulate deposit, list balances (guide) | Partial | Real authentication/accounts/balances plus EUR deposits settled and reconciled on 28 Oct (`a4c9f2c`). Dedicated EUR receiving account configured. Receipt settlement verified by provider polling; signed delivery is separate and unverified. |
| A12 | Treasury & Ops track positioning (proposal) | Done | README/landing describe Treasury & Ops (Adaptive Treasury Controller); not a connected-account platform |

## B. Shortlisted proposal promises

| # | Promise | Status | Evidence / gap |
|---|---|---|---|
| B1 | Listen for `deposit.settled` webhooks | Tested locally; configured externally | Per-org webhook and secret saved. No verified external delivery yet. Nested envelopes now retain simulation payer/reference hints. |
| B2 | Fallback: poll deposits if webhooks unreliable | **Partial; live receipt sync** | Owner-triggered sync reads `GET /deposits/{id}` for receipts previously created by Ledgerline and checks actual settlement, amount, currency and account binding before idempotent ingestion. Used live on 28 Oct. General `GET /deposits` discovery and a scheduled poller are not implemented. |
| B3 | Clean match / bank-fee write-off / partial / duplicate / no reference / wrong currency | Done+tested | `test_matching.py`, accuracy harness (250 seeds, 64,215 checks, 0 mismatches) |
| B4 | Payment link for the exact balance; draft if links unavailable | Done+tested (local) · **Blocked** live | Sandbox `POST /pa/payment_links/create` payload matches the docs; local mode stores a labelled "Draft, not sent" note and never shows a URL |
| B5 | Payer agent over MCP, signed `explain_payment`, three checks | Done+tested | Real stdio MCP subprocess, Ed25519, replay/expiry/binding/records checks; malicious claim rejected (DEP-1004) |
| B6 | Claude reads emails/PDFs when no agent | Partial / blocked live | Pasted text extraction and strict tools/budgets are implemented. Direct PDF ingestion is missing; the key is now set, but a successful model call needs Anthropic account credit (first live call refused, nothing applied). A deterministic fixture is not Claude execution. |
| B7 | Apparent duplicate becomes advance credit after signed evidence | Done+tested | DEP-1005 → verified_advance_credit; plan v1, evidence, v2 and journal preserved |
| B8 | FX: quote and convert only the shortfall above reserve | **Live** (28 Oct, `a4c9f2c`) | OP-CBAA2582 settled: EUR1,811.36 → GBP1,501.00. EUR2,000 reserve kept, GBP1,500 reserve met, quote reuse refused with409, ledger balanced. See INTEGRATION_EVIDENCE. |
| B9 | Refund over limit approved by a person, duplicate lock, SENT not final | Done+tested | Partial unique index, UUIDv5 ids, scope hash, SENT keeps liability; status map updated for approval_rejected/recalled |
| B10 | Pause switch for all money-out | Done+tested | Operator pauses, owner resumes |
| B11 | Conservation to the cent; scorecard | Done+tested | Per-currency conservation; scorecard computed from state |
| B12 | Beneficiary creation (`/beneficiaries/schema`, `/beneficiaries/create`) | **Missing** | Refund destinations must be existing sandbox beneficiary ids |
| B13 | `GET /fx/rates/current` | **Missing display** | No current-rate endpoint/display. Executable sandbox quotes are used for conversion decisions; local mode uses explicitly synthetic rates. |
| B14 | Demo video (~4 min) | **Blocked** (user) | `docs/DEMO_SCRIPT.md` written and its figures checked against a fresh sample organization (28 Oct); recording is the user's |

## C. Deployment and SaaS (user briefs)

| # | Requirement | Status | Evidence / gap |
|---|---|---|---|
| C1 | Frontend on Vercel, same-origin `/api` proxy | Done (live) | https://ledgerline-black-iota.vercel.app (Vercel Hobby); `frontend/vercel.json` route, CSP, HSTS |
| C2 | Backend with persistent storage | Done (live, free) | Render Free + Neon Free PostgreSQL; `/api/health` `"storage":"postgresql"`; `LEDGERLINE_REQUIRE_DATABASE=1` refuses local fallback. No paid resources. Free-tier spin-down and Neon limits disclosed in `DEPLOYMENT.md` |
| C3 | Secure cookies, CSRF, origins through the public URL | Done+tested live | Codex public workflow 32/32 on `a528ca9` (28 Oct); valid edge proof, stable client identity under spoofed forwarding headers and direct-origin forged-proof refusal verified. |
| C4 | Judges cannot touch shared sandbox funds or other orgs | Done+tested | `LEDGERLINE_SANDBOX_ORGS` allow-list; readiness check hides shared account details; tenant isolation tests |
| C5 | Health check, migrations, persistence guard, restart persistence | Done+tested live | Redeploy continuity verified earlier; Codex independently confirmed an actual Render instance change on 28 Oct, then passed 8/8 account/data/ledger/refund/MCP signing-key checks. |
| C6 | Judge docs: JUDGE_QUICKSTART, DEMO_SCRIPT, INTEGRATION_EVIDENCE, SUBMISSION_DRAFT, DEPLOYMENT_HANDOFF | Partial | Docs distinguish observed sandbox deposits/FX from pending refund, signed webhook and credit-blocked Claude extraction; final release SHAs and judge source access remain to finish |

## D. Our own product improvements (not event requirements)

Product home page; Google sign-in (configured, user completed real login); Apple hidden from login by user choice; randomized reference-model harness; Playwright browser suite. VM backup scripts are alternatives, not deployed Neon backups.

## Exact settings still needed from the user

| Setting | Where | Unblocks |
|---|---|---|
| `AIRWALLEX_CLIENT_ID`, `AIRWALLEX_API_KEY` | Saved on Render | Live sandbox deposits and FX conversion executed and reconciled; transfer/refund pending a second approver |
| `LEDGERLINE_SANDBOX_ORGS` | Configured for the operator's one organization | Judges remain on isolated local simulations |
| Airwallex webhook secret + registered URL | Saved in owner settings and sandbox web app | Configuration complete; delivery proof pending |
| `ANTHROPIC_API_KEY` (optional `LEDGERLINE_CLAUDE_MODEL`, default `claude-opus-5-5`) | Set on Render (28 Oct) | B6 live extraction needs account credit |
| Vercel edge proof | Complete | Corrected production deployment verified valid, with spoof refusal; no email code is needed. |
| Google OAuth configuration | Saved; exact public callback verified | User completed Google login/onboarding. Testing-mode access remains controlled by the owner. |

## Sandbox input review — 28 October

Checked against [developer lab](https://airwallexdev.com/), [builder guide](https://airwallexdev.com/guide) and official [deposit simulation](https://www.airwallex.com/docs/api/simulation/deposits/create) / [webhook](https://www.airwallex.com/docs/developer-tools/webhooks/listen-for-webhook-events) references. REST is supported; Airwallex Developer MCP is not configured here. Payer-agent stdio MCP is a separate integration.

- Simulation amounts are positive integer minor units internally, converted to major-unit JSON numbers. Currency is not sent: the selected Global Account determines it. A pre-dispatch account lookup now refuses the wrong, unknown or ambiguous receiving currency.
- Sandbox simulation responses never manufacture settled receipts. The walkthrough waits for authenticated settled webhooks; retries retain a durable attempt marker and ambiguous submissions require reconciliation.
- Transfers/conversions use exact major-unit strings and stable request IDs; approval, reserve, pause and finality rules stay in code.
- New regressions cover nested webhook hints, invalid amounts, wrong/ambiguous account currencies and pending/ambiguous deposit simulations. Provider mocks prove code behavior, not live Airwallex acceptance.
- Full compliance is not certified: generic deposit discovery/background polling, beneficiary creation, direct PDF ingestion, current-rate display, successful model extraction, completed live refund and signed webhook delivery remain open. Known-receipt polling and sandbox deposits/FX have live evidence. The user records the demo video.
