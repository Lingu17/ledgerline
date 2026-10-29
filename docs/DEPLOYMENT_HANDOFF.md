# Ledgerline deployment handoff

## Google Cloud single host (29 Oct 2026, Claude) — current recommended deployment

- **Live URL: https://35-207-220-110.sslip.io** (website, API and database on one always-on server; no cold start).
- VM `ledgerline`, project `project-0b143378-307b-4214-818`, zone asia-south1-a (Mumbai), e2-small (2 vCPU, 2 GB), Ubuntu 24.04 LTS, 20 GB balanced disk, Standard network tier, static IP `ledgerline-ip` = 35.207.220.110. Console estimate $17.09/month plus the static IP, paid from the Free Trial credits (₹28,797, ends 28 Jan 2027; the VM stops then unless the account is upgraded). No paid upgrade was made.
- Deployed with `deploy/vm/setup.sh 35-207-220-110.sslip.io self <commit>` (single-host mode: frontend built with Node 22 and served by the API; Caddy automatic HTTPS; Caddy trusts no upstream proxy and `LEDGERLINE_TRUSTED_PROXY_HOPS=1`; SQLite + payer-agent keys in `/var/lib/ledgerline` on the persistent boot disk; nightly backups). The repository is private, so code is delivered as a git bundle over SSH (`git bundle create ledgerline.bundle HEAD deploy/vercel-render`, copied to `/srv/ledgerline.bundle`, `LEDGERLINE_REPO=/srv/ledgerline.bundle`). Deployed commit `23ba6cab406f`.
- Observed: `/api/health` ok, `storage: persistent mount`; client address resolved to the real browser address and a forged `X-Forwarded-For` was ignored; `scripts/smoke_deploy.py` **32/32**; real VM reboot (boot id `937d4f03…` → `c6b952ab…`, services active on boot) then `--verify` **8/8** (account, invoice balance, payment decision, ledger, refund lifecycle, payer signing keys); redeploy with `update.sh 23ba6cab406f` then `--verify` **8/8**.
- Not yet configured on the VM: Airwallex, Anthropic and Google OAuth credentials (user enters them in `/etc/ledgerline/ledgerline.env`, then `sudo systemctl restart ledgerline`); Google OAuth redirect URI for the new host; a new operator organization for the Airwallex allowlist and webhook. The old Vercel + Render + Neon deployment is still running and unchanged.

Updated 29 October 2026. Deadline: 13 November 2026, 23:59 IST. No HackerEarth create/save/submit or public posts.

## Observed application release

- Live: https://ledgerline-black-iota.vercel.app (Vercel Hobby) → existing Render FREE Singapore ledgerline-api (`srv-dbgad6ijnfac73fo2e1g`) → Neon FREE direct TLS PostgreSQL. No transaction pooler, paid disk, duplicate infrastructure or PC tunnel.
- Backend and frontend were independently confirmed live/READY at `98d6ad4653aa3701b38a81577650377f2ad30792` before this documentation update. [CI 40839628066](https://github.com/Lingu17/ledgerline/actions/runs/40839628066) passed all five jobs: Linux/Windows backend, PostgreSQL 17, browser E2E and frontend.
- Public health returned HTTP 200, storage postgresql, edge_proof valid. Prior public smoke/restart evidence is historical; repeat after final main-branch deployment.
- This documentation commit follows that verified runtime. Final release procedure below records its own final deployed SHAs and CI, without treating older evidence as final-release proof.

## Completed live sandbox work — 29 October

- Actual provider event inspection found integer Unix-millisecond resource timestamps in API version 2026-08-21. Fixed ISO-only parsing; raw-byte HMAC and dedupe unchanged. Booleans/fractions/out-of-range epochs and unzoned timestamps are refused. Focused webhook/receipt/link tests 41/41 passed; frontend build passed.
- Fresh EUR1.23 receipt for INV-2304 arrived through actual signed webhook (not polling): Render HTTP 200 at07:52:52UTC, instancegqfv9. Provider event f59fe557-…_deposit.settled showed Succeeded/HTTP 200. Neon read-only query returned one webhook_events row, result processed. Local DEP-E2CC08C928 allocated EUR1.23 against EUR2.00; EUR0.77 remains due.
- Provider external replay was requested, but Airwallex's retriggerWebhookWebapp returned success:false, no listed errors. No second callback or duplicate_ignored row was observed. External replay proof remains incomplete. Local signed replay tests and CI/Neon concurrent dedupe are separate evidence; never claim they are a second Airwallex delivery.
- Real POST /pa/payment_links/create for INV-2304's exact EUR0.77 balance returned HTTP401 unauthorized. Labelled draft retained; no invented URL, no email, no automatic retry. New owner-only/allowlisted publisher claims each draft before dispatch and refuses changed balances.
- APR-B40BC448 was already invalidated28 Oct18:31UTC when DEP-377ABD25B9 became customer credit. Its old pending handoff was stale. Kept that EUR5 credit intact.
- User approved a fresh EUR5 sandbox case, DEP-A5772C9AEC (REFUND-VERIFY-20261029), received by signed webhook. New APR-8B78F0CB approved by the user's second real member29 Oct08:00UTC; proposer and approver differ. No account was created by the agent.
- Executed once: OP-37093F21, request23d22f6c-…, provider transfera9f8a91f-…. Processing08:01UTC → SENT08:07UTC → PAID08:08UTC through real sandbox transition API and provider reads. SENT retained EUR5 refund payable/refund_pending and EUR0 refunded. PAID released payable to0 and recorded EUR5 refunded. Airwallex list showed exactly one paid EUR5 transfer with this reference; detail request id matched.
- All currencies balanced. EUR conservation after PAID: deposits4,024.96 = applied4,014.96 + credits5.00 + refunds paid5.00 + refunds pending0 + unapplied0. Earlier EUR5 customer credit retained. Owner-only sandbox transition controls enforce processing→SENT→PAID before dispatch; terminal repeats refused. Refund/security regressions 70/70 passed in 29.42s; frontend build passed. Tests overlap with other focused sets; do not add counts as unique tests.

## Earlier observed banking actions — 28 October

- EUR1.23/INV-2301 and EUR4,000/INV-2302 settled via authenticated polling and exact-matched.
- OP-CBAA2582 settled EUR1,811.36→GBP1,501.00. EUR2,000 reserve kept; GBP1,500 reserve met; quote reuse refused 409. Airwallex returns MULTI_USE quotes; local single-use enforcement was fixed in a4c9f2c.
- EUR12.50 vague-reference DEP-C63DAB2722 escalated. First actual Claude call reached Anthropic but was refused for insufficient credit; no evidence stored/applied. Owner subsequently allocated it manually to INV-2303 with a written note.

## Database verification

- Fresh disposable schema-only Neon branch ledgerline-review-20261029 / br-royal-rice-aocrqdzc, direct TLS/pooling off, free plan, automatic deletion30 Oct2026 at13:04IST. User authorized private connection setup; URL only gitignored backend/.env.test, never printed/committed. No production schemas used for tests.
- tests/test_postgres.py completed **13/13 in 1,629.50s**, exit0, on29 Oct. Process started at baseline 6c43626; PostgreSQL test/adapter files were unchanged by later webhook/UI edits. Includes real concurrent hardening, walkthrough/restart, privileges/tenants, concurrent refund/FX, random-company reference checks, webhook dedupe, rollback/pool recovery and MCP signing continuity. Current Neon reports PostgreSQL 18; CI PostgreSQL 17 remains primary final-code DB evidence.
- Old branch-expiry run8passed5failed1error is historical, not a pass or established code defect. Older whole-Neon suite stopped after 3/232, not complete. No owned test remains running after this13/13 completion.
- Historical9f07166 public smoke32/32 and actual Render instance replacement followed by8/8 persistence are distinct from the final main release still to verify.

## Credentials, access and remaining blockers

- Never change LEDGERLINE_SECRET_KEY (encrypted signing identities). Preserve existing edge secret. No credentials in chat, logs or Git. No purchases.
- Google configured; real login/onboarding observed. OAuth Testing mode may restrict judges; email/password signup available. Apple hidden by user choice; no paid membership.
- Anthropic key is saved, but successful extraction is unverified. User expects hackathon credits in one day (29 Oct statement). Organizer discussion says guidance/credits go to shortlisted teams in Build Phase; no redemption link visible. Wait for credit, then one real escalated-deposit read, validate model/tool output and record the human decision. No purchase authorized.
- Repository remains private; user will decide public visibility/judge access later. Do not expose it. User records the video.
- Missing proposal features are disclosed in matrix/submission draft: generic GET /deposits discovery/background polling (known-receipt GET /deposits/{id} sync exists), beneficiary schema/create, GET /fx/rates/current display and direct PDF input.
- Scoped payment-link capability refused HTTP 401; no hosted link claimed. Signed external delivery is verified; external replay remains refused/unverified.

## Main release procedure

After this final documentation commit passes all five CI jobs: fast-forward/review-merge deploy/vercel-render into main, point existing Vercel production branch and Render branch at main, redeploy and independently record backend/frontend SHAs. Run scripts/smoke_deploy.py through the public frontend --save to a private temporary file (expect32/32); actually restart Render, verify a new instance, then --verify (expect8/8). Save the exact final release report in the chat outputs folder. Do not equate a redeploy or pre-restart check with restart proof.

render.yaml now describes Free/direct-Neon/main/checksPass, with secret placeholders; public JSON-schema validation passed. No Blueprint was applied, no service created and no signing/edge secret changed. Free services sleep and cold starts have failed previously; no always-on/permanent-free guarantee.

RESUME.md was folded into this handoff and removed29 Oct because it predated completed bank actions. Monitoring is paused; do not claim an active background monitor. Continue from this handoff and the final dated report.
