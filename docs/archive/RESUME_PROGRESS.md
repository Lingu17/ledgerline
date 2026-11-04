# Resume point (updated 4 Nov 2026, paused until after 12:10 at the owner's request)

Branch `deploy/vercel-render` (snapshot also on `wip/payer-agent`); `main` moves only after the server reports the same
commit. **Live: `d22f232`** (read back). Submit by 13 Nov 23:59 IST (owner). Feature freeze 9 Nov; fixes only after.

## How releases are checked while CI is blocked

GitHub Actions is blocked by an account billing hold since 3 Nov (#164 onward): deploy on local checks (backend
`--ignore=tests/test_postgres.py`, `npm run e2e`) plus the reviewing session's own suite run. Never claim CI green.
The Linux cloud check (branch `linux-check-report`) ran the PostgreSQL suite and Linux-only tests once; after the
repository goes public, trigger `ci` and check every job.

## Pushed, not deployed (in order)

| Commit | What | Reviewer |
|---|---|---|
| `d3821d1` | CSV export of a company's records (zip) | OK |
| `f02d0a9` | Version, running commit, CHANGELOG.md and #/changelog (version still 0.2.0) | OK |
| `ebd32f2` | #/help, in-app Page not found, crash screen, "Simulate bank" wording | OK (563 passed) |
| `9418445` | Policy form merges over the stored policy; approval expiry and planning window fields (audit P1-1, P1-2, P2-9) | not yet |
| `245da67` | Delete company: pause inside the check's transaction; a held context never recreates a database | not yet |
| `e2b3725` | Records-only mode for real companies with no bank (audit P1-3) | not yet; full backend suite not yet run |

## Next, in this order

1. Review and merge `origin/review/systemd-fixes` (`ceb5058`, on d22f232): `_ENV_KEYS` gains LEDGERLINE_SENDER_SOCKET,
   LEDGERLINE_CONNECTIONS_KEY_PATH, LEDGERLINE_SECURITY_CONTACT (without it the server ignored them), sender `ping`,
   harden.sh check_sender fixes, test_env_keys.py. Until merged, do not touch config.py, sender.py, harden.sh,
   test_sender.py. Then run both suites, send hashes, deploy the reviewed tip, confirm `/api/public/info` and
   `/.well-known/security.txt` (the owner sets LEDGERLINE_SECURITY_CONTACT; until then 404 is correct).
2. Product audit (`origin/product-audit-report`, docs/archive/PRODUCT_AUDIT_2026-11.md), remaining P1s, one commit
   each: P1-4 zero default reserves for My company + opening-balance step in the setup checklist and "Opening balance
   not set" instead of "Short by"; P1-5/P1-9/P2-1 plain-language pass (matching.py:92 "route remittance text…",
   matching.py:164/170 broken sentence, Settings Integrations internals behind "Technical details", audit codes as
   sentences); P1-8 own-agent wording (Settings.tsx:189, SUBMISSION_DRAFT.md:49); P1-10 refund proposal confirm step +
   status; then robots.txt, docs points 2 and 5, P2 items in the audit's order.
3. Version 1.0.0 only when every check passes; CHANGELOG top section already says 1.0.0.

## Waiting on the owner

SERVER_STEPS 0-6; step 7 (sending service) NOT until review/systemd-fixes is merged and deployed; the video link;
the secrets scan; optional LEDGERLINE_SECURITY_CONTACT; making the repository public; CI after public; submission.

## Access

SSH `ssh -i ~/.ssh/ledgerline_oracle ledgerline-deploy@35.207.220.110`. Deploy:
`bash <old scratchpad>/deploy.sh <full sha>` (C:/Users/HP/AppData/Local/Temp/claude/C--Users-HP-Desktop-Agentic-Banking-Hackathon/f3619b5a-c050-4883-a228-0413cab0b537/scratchpad/deploy.sh;
bundles the branch, runs update.sh, reads the commit back, pushes main only on MATCH; accepts any branch ancestor).
Never print `/etc/ledgerline/ledgerline.env` or any key. No AI attribution in commits. No Slack or other messages on
the owner's behalf.
