# Resume point (updated 5 Nov 2026)

Branch `deploy/vercel-render` (snapshot also on `wip/payer-agent`); `main` moves only after the server reports the same
commit. **Live: `8d76391`** (read back 5 Nov; health shows the commit). Submit by 13 Nov 23:59 IST (owner). Feature
freeze 9 Nov; fixes only after.

## How releases are checked while CI is blocked

GitHub Actions is blocked by a billing hold (#164 onward): deploy on local checks (backend
`--ignore=tests/test_postgres.py`, `npm run e2e`) plus the reviewing session's own suite run, hash sent before each
deploy. Never claim CI green. Cloud reports (Linux, systemd, load, security, browser matrix, restore drill, product
audit) are on their `*-report` branches; never merge those.

## Done since 8d76391 (pushed or in the working tree; not deployed)

| Commit | What |
|---|---|
| `61637af` | PostgreSQL advisory lock per key in the sign-in reservation |
| `95f7da7` | New real companies start with zero reserves; wallets say whether cash is known; setup step for opening balances; CEO says when cash is short (audit P1-4) |
| `b8d3d79` | Plain wording: reasons (display-side, stored text unchanged for Replay), event labels, Integrations card, "Opening balance: Not set yet" (audit P1-5, P1-9, P2-1) |
| working tree | Propose return: confirmation with amount and a required note, approval titled "return <what> to <customer>: <note>", payment moves to "Refund for approval" (audit P1-10); full backend run pending |

## Next

1. Full backend + browser on the tip, commit P1-10, send the hash, deploy after the reviewer's OK.
2. Remaining audit P2 items in the audit's order (P2-2 ledger account labels, P2-4 "Reconciled" label, P2-5 date
   formats and file picker, P2-8 decision path, P2-10 remittance toast and pre-fill, P2-11 why-card money format,
   P2-12 tamper amounts as money, P2-13 tour stop 1 wording, P2-14 practice wording, P2-15 invite wording, P2-16
   approvals details, P2-17 pause reason, P2-19 one name for the no-bank state, P2-20 no 401 in the console).
3. Version 1.0.0 only when every check passes.

## Waiting on the owner

SERVER_STEPS 0-7 (7 only after reading its notes); LEDGERLINE_SECURITY_CONTACT if the owner gives a contact (never
invented); for judging day consider raising LEDGERLINE_SIGNUP_PER_IP_HOUR/DAY (load test problem 5); the video link;
the secrets scan; making the repository public; CI after public; submission.

## Access

SSH `ssh -i ~/.ssh/ledgerline_oracle ledgerline-deploy@35.207.220.110`. Deploy:
`bash C:/Users/HP/AppData/Local/Temp/claude/C--Users-HP-Desktop-Agentic-Banking-Hackathon/f3619b5a-c050-4883-a228-0413cab0b537/scratchpad/deploy.sh <full sha>`
(bundles the branch, runs update.sh, reads the commit back, pushes main only on MATCH; any branch ancestor). Never print
`/etc/ledgerline/ledgerline.env` or any key. No AI attribution in commits. No Slack or other messages on the owner's
behalf. Never create accounts or sign in on the live site.
