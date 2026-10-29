# Ledgerline deployment handoff

Updated 29 October 2026. Continue on `deploy/vercel-render` until the final reviewed release is merged into `main`. Deadline: 13 November 2026, 23:59 IST. Never save or submit on HackerEarth.

## Infrastructure and immutable constraints

- Live frontend: https://ledgerline-black-iota.vercel.app (Vercel Hobby, root `frontend`).
- Existing backend: Render FREE Singapore `ledgerline-api`, `srv-dbgad6ijnfac73fo2e1g`, https://ledgerline-api-4dt3.onrender.com.
- Database: Neon FREE project `ledgerline` (`red-grass-80303368`), direct TLS endpoint; no `-pooler` or transaction pooling.
- Never change `LEDGERLINE_SECRET_KEY`: it encrypts durable payer signing identities. No credentials in chat, logs or Git; user enters credentials and provider logins.
- No paid resources, duplicate services, Supabase changes, PC tunnels or public posts. Four-eyes, scoped approval, reserves, pause, idempotency and SENT-versus-PAID remain enforced.
- Free services can sleep; cold-start failures have been observed. Always-on/permanent-free hosting is not guaranteed.

## Current observed state (29 October)

- Source HEAD at continuation: `6a7a2f96b42e02918a66e10944b404ed43135205`; latest application change `a4c9f2c` fixes locally enforced single-use FX quotes (Airwallex returns MULTI_USE quotes).
- Connector observations: Vercel production READY at `6a7a2f96b42e02918a66e10944b404ed43135205`; Render live deploy `dep-dbh3kt0n74is73bhff60` at `540dd93dfca1e13b1874e272b8e234513f268d30`. These differ; do not call them the final aligned release.
- GitHub run40746046892 for `6a7a2f9` reports completed/success. The final release still needs independently inspected five-job results at its final SHA.
- Ledgerline and Airwallex browser sessions require the user to sign in again. Do not sign in to providers for the user.
- Google is configured and a real user login/onboarding was observed on28Oct. OAuth Testing mode may restrict judge accounts; email/password signup remains available. Apple is hidden by user choice.
- Airwallex credentials, one-organization sandbox allowlist and dedicated EUR account are saved; webhook secret was saved under an earlier specifically approved private transfer. No further secret transfer is authorized or needed.
- Anthropic key is configured. The first actual read-remittance request was refused for insufficient credit; no successful extraction, stored proposal or resulting AI allocation is claimed.

## Actual sandbox banking evidence (28 October)

See INTEGRATION_EVIDENCE.md for amounts and redacted provider ids. Settlements arrived by authenticated polling, not verified signed delivery.

- EUR1.23 → INV-2301 and EUR4,000 → INV-2302 settled and exact-matched; ledger balanced.
- OP-CBAA2582 converted EUR1,811.36 → GBP1,501.00 and settled. EUR2,000 reserve kept; GBP1,500 reserve met; same-quote retry refused409; ledger balanced.
- EUR12.50 vague-reference deposit DEP-C63DAB2722 escalated. Real Claude request refused for insufficient credit. Operator then allocated manually to INV-2303 with a written note.
- EUR5 deposit DEP-377ABD25B9 escalated; return-to-sender approval APR-B40BC448 remains pending a second real operator/owner. Do not fabricate accounts or approvers. User must invite a second email they control and approve themselves. Then execute once, drive sandbox SENT then PAID, prove liability retained at SENT/released only at PAID and no duplicate transfer.
- Signed webhook delivery unverified. A historical real deposit callback returned400; do not weaken HMAC validation or trust caller-supplied secret headers. Inspect actual provider delivery and payload, then prove Render receipt, webhook_events row and replay dedupe; a saved subscription is not delivery proof.
- Payment-link capability unverified; attempt scoped sandbox API once for an actual partial balance. Display only a provider-returned URL or an explicitly labelled draft fallback.

## Evidence boundaries and database rerun

- Historical runtime9f07166: CI40734890246 allfivejobs passed; PostgreSQL-specific13/13 and wholePostgreSQL253/253; publicsmoke32/32; confirmed Render replacement7j2f6→fcpnp then saved-account/data/ledger/refund/signing-key8/8. Concurrent first-tenant reads5/5. Later source changes need their own evidence.
- a0fe23a owner sandbox receipt create/sync: local253passed9skipped, focused36/36, frontendbuildpass; CI40737882028 allfivejobs passed.
- a4c9f2c: local254passed9skipped recorded by Claude. Treat CI at finalSHA as release evidence.
- Accuracy harness:6287 checks,1064payments,508invoices,25companies/5walkthroughs, zero mismatches. This is synthetic reference-model evidence, not6287 live bank calls.
- Old isolated Neon12/12 in1574.55s is historical. Later branch-expiry rerun:8passed5failed1error,17.5min; endpoint disappeared. It is not a pass or an established code defect. Earlier wholeNeon suite stopped after3/232; not a completed pass.
- Fresh schema-only review branch created29Oct: `ledgerline-review-20261029`, `br-royal-rice-aocrqdzc`, direct pooling off, automatic deletion30Oct2026 13:04IST. User must place its direct URL in gitignored backend/.env.test; never reuse expired endpoint. Run tests/test_postgres.py to completion on this isolated branch only, record result/duration. CI PostgreSQL17 remains primary DB evidence; Neon production reports PostgreSQL18.

## Explicit proposal limitations

- Receipt sync is a bounded GET /deposits/{id} fallback for known Ledgerline-created receipts, not generic GET /deposits discovery/background polling.
- Beneficiary schema/create endpoints are not implemented; use existing sandbox beneficiary ids.
- GET /fx/rates/current display is absent; executable quotes are implemented.
- Remittance input is pasted text; direct PDF ingestion is absent.
- Judge workspaces use a local simulated bank and simulated payers over actual MCP/Ed25519. Shared sandbox banking is restricted to the allowlisted operator organization.

## Remaining release sequence

1. Finish user-approved refund, signed webhook, credit-backed Claude extraction and payment-link attempt; record exact observations/refusals, never inference as success.
2. Complete fresh isolated Neon specific suite, avoid production schemas.
3. Keep JUDGE_QUICKSTART, DEMO_SCRIPT, SUBMISSION_DRAFT, matrix and integration evidence consistent with results.
4. After final commit passes allfiveCIjobs, fast-forward or reviewed-merge deploy/vercel-render into main. Point existing Vercel production branch and Render branch at main; deploy exact reviewed revisions.
5. Record backend/frontendSHAs separately. Run scripts/smoke_deploy.py through publicfrontend --save(private temporary state), expect32/32. Actually restart Render and confirm a new instance, THEN --verify saved state, expect8/8. Prior proof is not final-release proof.
6. Repository is private; ask user to arrange judge access or approve public visibility. User records demo video. OAuthTesting-mode audience may restrict judges. No HackerEarth submission authorized.

RESUME.md was folded into this handoff and removed on29Oct because its top checkpoint predated the observed sandbox deposit/FX actions. Prefer dated evidence here and INTEGRATION_EVIDENCE over older chat checkpoints. No active owned test process at this checkpoint. Monitoring is paused; do not claim continuous background work.
