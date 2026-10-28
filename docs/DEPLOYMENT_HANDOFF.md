# Ledgerline deployment handoff

Updated 28 October 2026. Branch `deploy/vercel-render`. No HackerEarth save/submission is authorized.

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
