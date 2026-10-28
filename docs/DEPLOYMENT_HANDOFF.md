# Ledgerline deployment handoff

Updated 28 October 2026. Branch `deploy/vercel-render`. No HackerEarth save/submission is authorized.

## Live sandbox money actions — 28 Oct 2026 (Claude)

- Code `a4c9f2c` fixed a live-only bug: Airwallex sandbox returns `usage: MULTI_USE` quotes and the request cannot ask for single use; Ledgerline now enforces single use itself. Backend 254 passed / 9 skipped.
- Executed on the live deployment, owner account, allowlisted organization: EUR 1.23 → INV-2301 and EUR 4,000.00 → INV-2302 (settled, exact match); EUR→GBP conversion `OP-CBAA2582` (EUR 1,811.36 → GBP 1,501.00, settled; quote reuse refused; reserves kept); EUR 12.50 with a vague reference escalated, then allocated to INV-2303 by the operator; EUR 5.00 unknown reference escalated, return-to-sender approval `APR-B40BC448` pending a second real approver. Ledger balanced in every currency after each step. Airwallex sandbox emails confirmed the deposits and the conversion.
- `ANTHROPIC_API_KEY` added to Render; health reports Claude configured. The first live read was refused by Anthropic (account credit too low); nothing was stored or applied.
- Details: [INTEGRATION_EVIDENCE](INTEGRATION_EVIDENCE.md).
- Neon isolated rerun of `tests/test_postgres.py` (started 23:44 IST, 13 minutes before the review branch expired): 8 passed, 5 failed, 1 error in 17.5 minutes; the failures are pool/connection timeouts, and the branch endpoint was gone when checked afterwards ("endpoint could not be found"). This is not a pass and not a code finding; the same tests passed on PostgreSQL 17 in CI. A fresh Neon test branch is needed to repeat it.

## Latest review continuation

Sandbox input/finality commit739936e was confirmed live on Render and Vercel. CI40733133154 passed all five jobs (including the whole backend on PostgreSQL), and public smoke passed32/32. The owner readiness check on that release returned real Airwallex authentication/accounts/balances and retained the saved webhook secret across deployment.

A historical production audit failure exposed a separate startup race: concurrent requests ran schema ACL hardening at once, producing PostgreSQL `tuple concurrently updated`. Follow-up commit `9f07166dfe342a33a8506c344f392c191f0f40f4` uses a context initialization lock, closes failed initialization connections, and holds the existing transaction-scoped schema advisory lock throughout hardening. Focused local tests46/46 passed. Real Neon privilege isolation passed; the new concurrent-hardening test passed in22.27 seconds after correcting its signup fixture from invalid `workspace` to valid `empty`.

Final runtime `9f07166` is confirmed live on Render and Vercel. [CI40734890246](https://github.com/Lingu17/ledgerline/actions/runs/40734890246) passed all five jobs: PostgreSQL-specific13/13, whole PostgreSQL253/253, Linux244 passed9 skipped, Windows/backend, browser and frontend successful. Public synthetic workflow32/32. After logs confirmed actual Render replacement7j2f6 to fcpnp, saved-account/data/ledger/refund/signing-key continuity passed8/8. Five simultaneous first reads (including audit) returned200 JSON. This is new redeploy proof; earlier restart-only evidence is distinct. Later documentation-only commits do not imply a different tested runtime.

HackerEarth read-only inspection confirmed a published shortlisted idea and Build Phase0 submissions. No submission was created/saved. Public detailed criteria sections still contain dots; no complete organizer rubric is assumed. The repository is private; judge source access must be arranged by the owner if required. Actual sandbox deposit delivery/actions and actual model use remain unverified, and proposal gaps remain as listed below.

## Current infrastructure

- Frontend: https://ledgerline-black-iota.vercel.app — existing Vercel Hobby project, root frontend, same-origin /api proxy.
- Backend: existing Render FREE Singapore service ledgerline-api, srv-dbgad6ijnfac73fo2e1g, https://ledgerline-api-4dt3.onrender.com.
- Database: existing Neon FREE project ledgerline, direct TLS endpoint. No transaction-mode pooler, local hosted-storage fallback, paid disk, new service or PC tunnel.
- Never change LEDGERLINE_SECRET_KEY: it encrypts durable payer signing identities. No credential values belong in logs, chat or Git.
- Render auto-deploys backend changes; frontend-only commits can leave backend and frontend Git SHAs different. Record each deployed revision independently.

## Observed configuration and verification

- Public health recovered after an observed idle wake-up: HTTP 200, storage postgresql, edge_proof valid. Direct backend health reports edge proof missing as expected for a direct request.
- Google is configured; exact public callback/client redirect verified. The user completed real sign-in and organization onboarding. Google remains subject to its owner's OAuth Testing-mode audience. Email/password judge signup is available. Apple is hidden from login by user choice.
- Airwallex credentials and a single-organization sandbox allowlist are saved. Owner readiness exercised real authentication, accounts and balances. Dedicated EUR receiving account is configured.
- Approved deposit.settled-only webhook is registered. Secret was privately transferred under a specific user exception; Ledgerline confirmed organization Airwallex secret and the write-only Set hint. No secret is included here.
- Actual sandbox simulation, signed receipt, FX, refund and payment-link execution remain unverified. The test-event dialog did not produce an observed receipt. Never report a saved webhook as delivered.
- Anthropic key is absent: no actual Claude extraction has been verified. The labelled rules reader is advisory.

## Review evidence by source boundary

- Historical a528ca9: all five CI jobs passed (https://github.com/Lingu17/ledgerline/actions/runs/40569405112), public smoke32/32, edge spoof refusal, actual Render instance replacement b9fnc to djx6n followed by persistence/MCP checks8/8.
- Historical isolated Neon suite: 12/12 in 1574.55 seconds. Whole-backend Neon attempt was intentionally stopped after3/232 collected; not a completed pass. The review branch expires 28 October23:57 IST; never use an expired test endpoint or production schemas for tests.
- Source0da71a5 before this review: backend225 passed/8 skipped; browser12/12; frontend build passed.
- Sandbox-fix review: backend237 passed/8 skipped, focused regressions for further header validation separately recorded. Accuracy run6287 checks,1064 payments,508 invoices,25 companies and5 walkthroughs: zero mismatches. Frontend rebuilt successfully.
- New source changes require their own CI/deployment evidence. Previous restart proof does not automatically establish the new release.

## Next verification

1. Publish the reviewed sandbox input/finality fixes and inspect final CI, especially the real PostgreSQL whole-backend job.
2. Confirm final Render/Vercel revisions and public health, then run scripts/smoke_deploy.py against the public frontend. Save its synthetic account state outside the repository.
3. Finish real sandbox deposit simulation and authenticated receipt evidence, then intended FX/refund lifecycle and actual model invocation with authorized credentials. Keep provider and local-simulation results separate.
4. Proposal gaps: deposit polling fallback, beneficiary creation, direct PDF input, current-rate flow and final demo recording. Close or clearly disclose them before final user submission.

## Free-host limitations

Render can sleep and an idle request can fail while the instance starts; wake-up is not guaranteed to finish before proxy deadlines. Neon can suspend and free quotas/eligibility can change. This deployment is not guaranteed always-on or permanently free. No existing Supabase project was modified.
