# Hackathon requirements matrix

Audit date: 27 Oct 2026 (build phase day 1; deadline 13 Nov 2026, 11:59 PM IST). Sources: HackerEarth event page (read in the browser), airwallexdev.com and /guide, docs/original-proposal.txt, BUILD_BRIEF, SAAS_REQUIREMENTS, PRODUCT_POLISH, CODEX_REVIEW_FINDINGS, INDEPENDENT_REVIEW, and the code at branch `deploy/vercel-render`.

Status key: **Done+tested** = implemented with automated tests passing locally · **Live** = verified against the real external service · **Partial** · **Missing** · **Blocked** = needs something only the user/organizer can provide.

Nothing below is "Live" yet: no Airwallex sandbox credentials or Anthropic API key exist on this machine or any server.

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
| A11 | Verify connection: list global accounts, simulate deposit, list balances (guide) | Partial / **Blocked** | Read-only readiness check (login, global accounts, balances) implemented and unit-tested; simulate-deposit implemented; not run live: needs `AIRWALLEX_CLIENT_ID`, `AIRWALLEX_API_KEY` |
| A12 | Treasury & Ops track positioning (proposal) | Done | README/landing describe Treasury & Ops (Adaptive Treasury Controller); not a connected-account platform |

## B. Shortlisted proposal promises

| # | Promise | Status | Evidence / gap |
|---|---|---|---|
| B1 | Listen for `deposit.settled` webhooks | Done+tested (local) · **Blocked** live | Per-org webhook URL `/api/webhooks/airwallex/{org_id}`; needs sandbox webhook registration + secret |
| B2 | Fallback: poll `GET /deposits` if webhooks unreliable | **Missing** | Documented in proposal; not implemented. Planned: owner-triggered "Sync deposits" using `from_created_at` |
| B3 | Clean match / bank-fee write-off / partial / duplicate / no reference / wrong currency | Done+tested | `test_matching.py`, accuracy harness (250 seeds, 64,215 checks, 0 mismatches) |
| B4 | Payment link for the exact balance; draft if links unavailable | Done+tested (local) · **Blocked** live | Sandbox `POST /pa/payment_links/create` payload matches the docs; local mode stores a labelled "Draft, not sent" note and never shows a URL |
| B5 | Payer agent over MCP, signed `explain_payment`, three checks | Done+tested | Real stdio MCP subprocess, Ed25519, replay/expiry/binding/records checks; malicious claim rejected (DEP-1004) |
| B6 | Claude reads emails/PDFs when no agent | Done+tested (fixture) · **Blocked** live | Strict tools + output validation + per-org daily cap; live call needs `ANTHROPIC_API_KEY` |
| B7 | Apparent duplicate becomes advance credit after signed evidence | Done+tested | DEP-1005 → verified_advance_credit; plan v1, evidence, v2 and journal preserved |
| B8 | FX: quote and convert only the shortfall above reserve | Done+tested (local) · **Blocked** live | Reserves, settled-only spendability, pending FX never spendable; sandbox quote/conversion payloads checked against docs |
| B9 | Refund over limit approved by a person, duplicate lock, SENT not final | Done+tested | Partial unique index, UUIDv5 ids, scope hash, SENT keeps liability; status map updated for approval_rejected/recalled |
| B10 | Pause switch for all money-out | Done+tested | Operator pauses, owner resumes |
| B11 | Conservation to the cent; scorecard | Done+tested | Per-currency conservation; scorecard computed from state |
| B12 | Beneficiary creation (`/beneficiaries/schema`, `/beneficiaries/create`) | **Missing** | Refund destinations must be existing sandbox beneficiary ids |
| B13 | `GET /fx/rates/current` | Partial | Quotes are used for decisions; local mode uses fixed synthetic rates |
| B14 | Demo video (~4 min) | **Blocked** (user) | `docs/DEMO_SCRIPT.md` to be written; recording is the user's |

## C. Deployment and SaaS (user briefs)

| # | Requirement | Status | Evidence / gap |
|---|---|---|---|
| C1 | Frontend on Vercel, same-origin `/api` proxy | Done (live) | https://ledgerline-black-iota.vercel.app (Vercel Hobby); `frontend/vercel.json` route, CSP, HSTS |
| C2 | Backend with persistent storage | Done (live, free) | Render Free + Neon Free PostgreSQL; `/api/health` `"storage":"postgresql"`; `LEDGERLINE_REQUIRE_DATABASE=1` refuses local fallback. No paid resources. Free-tier spin-down and Neon limits disclosed in `DEPLOYMENT.md` |
| C3 | Secure cookies, CSRF, origins through the public URL | Done+tested live | `scripts/smoke_deploy.py` 32/32 through the Vercel URL (27 Oct). Edge-proof check (`edge_proof: valid`) still to be observed after the Vercel redeploy |
| C4 | Judges cannot touch shared sandbox funds or other orgs | Done+tested | `LEDGERLINE_SANDBOX_ORGS` allow-list; readiness check hides shared account details; tenant isolation tests |
| C5 | Health check, migrations, persistence guard, restart persistence | Done+tested live | Data created on one Render instance verified 8/8 on another after a redeploy; restart-only check to be repeated |
| C6 | Judge docs: JUDGE_QUICKSTART, DEMO_SCRIPT, INTEGRATION_EVIDENCE, SUBMISSION_DRAFT, DEPLOYMENT_HANDOFF | Partial | DEPLOYMENT and DEPLOYMENT_HANDOFF current; integration evidence for Airwallex/Claude needs real credentials |

## D. Our own product improvements (not event requirements)

Product home page with 3D globe; Google/Apple sign-in (needs OAuth clients); randomized accuracy harness; Playwright browser suite; nightly SQLite backups for VM hosting.

## Exact settings still needed from the user

| Setting | Where | Unblocks |
|---|---|---|
| `AIRWALLEX_CLIENT_ID`, `AIRWALLEX_API_KEY` | Server environment only | A11, B1, B4, B8 live verification |
| `LEDGERLINE_SANDBOX_ORGS` | Server environment | Which organization (yours) may use the sandbox account |
| Airwallex webhook secret + registered URL | Ledgerline Settings (owner) + sandbox web app | B1 |
| `ANTHROPIC_API_KEY` (optional `LEDGERLINE_CLAUDE_MODEL`, default `claude-opus-5-5`) | Server environment only | B6 live extraction |
| PythonAnywhere API token (or Render cost approval) | User's PythonAnywhere account page / Render | C2 deployment |
| Vercel sign-in | Browser | C1 |
