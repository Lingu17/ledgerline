# Resume point: full-application acceptance work (29 Oct 2026, ~16:00 UTC)

Branch `deploy/vercel-render` (not merged; merge only after the owner approves). Live: https://35-207-220-110.sslip.io running commit `718660e` (update.sh deploy, healthy). No HackerEarth save/submit. Repo stays private. Old Vercel/Render/Neon stack kept running, untouched (retire only on explicit approval).

## Done and verified

| Area | Result |
|---|---|
| Google Cloud only | All page resources from the one origin; VM env has no DATABASE_URL (SQLite under /var/lib/ledgerline); only 22/80/443 reachable from outside (8000, 2019, 20201/20202 time out). Billing ₹0.00 shown, ₹28,797 credit, trial ends 28 Jan 2027. Budget alert ₹2,000/month exists |
| Old stack | Vercel→Render→Neon health 200 (33 s cold start); still holds integration keys; retirement plan in docs/DEPLOYMENT.md (needs approval) |
| Official requirements | HackerEarth page: only dates (build phase ends 13 Nov 23:59 IST); tracks/criteria/prizes blank; submission fields hidden behind "New Submission" (not clicked). airwallexdev.com/guide: general demo rules, no judging criteria |
| New features (commit bf3b65a + 10e07d0 + 718660e) | Deposit discovery fallback (GET /deposits), beneficiaries (schema → validate → create), Treasury current rates (GET /fx/rates/current, normalised to buy-per-sell: real bug found and fixed), PDF remittance to Claude, quote rate from booked amounts, #/architecture 3D page, skip link, README screenshots (docs/screenshots, frontend/e2e/screenshots.spec.ts) |
| Defect fixed from live run | Claude reader rejected valid reasons over 500 chars; now 1,200, prompt asks for short reasons, rejected tool name recorded (718660e) |
| Tests | Backend 289+ passed (excluding PG-only file), new tests/test_proposal_gaps.py; Playwright 12 passed (+1 opt-in screenshot spec); frontend build ok |
| Local browser QA | All 11 app pages render without errors; walkthrough end-to-end in UI; scorecard 6/4/1/1/0 balanced; 375px: no page overflow |
| Live security | HSTS, CSP, XFO, nosniff, Referrer, Permissions headers; forged X-Forwarded-For ignored; unauth 401; cross-site 403; http→https 308; Apple not configured/absent |
| Live webhooks (synthetic) | missing sig 401, malformed sig 401, well-formed wrong sig 401 "signature mismatch", stale timestamp 401 "timestamp outside tolerance", unknown org 404 |
| Backup/restore | Manual backup run; isolated restore: 7 DBs integrity ok, row counts equal live, payer key restored, second instance served health/auth; removed after |
| Live Claude (browser, owner session) | DEP-7CDAEF2A79: EV-…-2 rejected (old 500-char limit), EV-…-3 malicious text → escalate, injection ignored and flagged; EV-…-4 PDF (869 bytes, sha256 1a5ffc3f…) → propose_refund, advisory; 0 approvals, 0 operations created |
| Live rates | Treasury shows Airwallex rates (USD→EUR 0.886677, GBP→EUR 1.185829 …) |
| Live discovery | "Checked 7 provider deposits: 0 new, 1 already booked, 0 not settled, 6 outside this organization" |
| Live beneficiary | Created 4f5abe34-a270-43c5-884d-fdbe3b0d50fd (EUR DE LOCAL, …3000) via validate+create, linked to CUST-SANDBOXREFUND |
| Payment link retry | POST /pa/payment_links/create → HTTP 400 configuration_error "Invalid request against merchant configuration. Please contact your account manager." (account-level blocker) |
| Earlier Claude (operator-cli) | EV-DEP-7CDAEF2A79-1 escalate, claude-opus-5-5, daily budget row succeeded |

## Remaining (in order)

1. **Refund (needs owner + second real person):** owner simulates sandbox deposit in Settings with payer `Sandbox Refund Test GmbH` (EUR 1.23, reference e.g. "sent in error"), owner clicks **Propose return to sender** on it, owner invites second member (Team → Invite, Operator), they join and **Approve…** then **Execute refund**; then observe SENT→PAID (Settings/Approvals; sync), check one transfer, liability, conservation.
2. Update docs/INTEGRATION_EVIDENCE.md (split current VM vs historical old stack), docs/HACKATHON_REQUIREMENTS_MATRIX.md (B2/B6/B12/B13 now done; B4 blocker text), docs/DEPLOYMENT_HANDOFF.md.
3. Write docs/FULL_APPLICATION_ACCEPTANCE_REPORT.md (feature→test matrix, PASS/FAIL/BLOCKED/NOT TESTED, defects + fixes).
4. Commit, push, wait for all 5 CI jobs on the final SHA (GitHub Actions page in Chrome; `gh` not installed).
5. Deploy that exact SHA (git bundle → /srv/ledgerline.bundle → `sudo bash /opt/ledgerline/src/deploy/vm/update.sh <sha>`).
6. `scripts/smoke_deploy.py https://35-207-220-110.sslip.io --save <state>` (32 checks), then `systemctl restart ledgerline` → `--verify`; real reboot (boot id must change) → `--verify`; update.sh redeploy → `--verify`.
7. Final report to the owner.

## How to reach things

- SSH: `ssh -i ~/.ssh/ledgerline_oracle ledgerline-deploy@35.207.220.110`
- Keys: `/etc/ledgerline/ledgerline.env` (never print values). `LEDGERLINE_SANDBOX_ORGS=org_66646a497151`.
- Owner org: Ledgerline Operations `org_66646a497151`; EUR global account fc116c57-01d3-4461-9275-c2b6864a332e; webhook `/api/webhooks/airwallex/org_66646a497151`.
