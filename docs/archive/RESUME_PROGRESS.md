# Resume point (updated 5 Nov 2026)

Branch `deploy/vercel-render` (snapshot also on `wip/payer-agent`); `main` moves only after the server reports the same
commit. **Live: `f9be55d`** (read back 5 Nov; health shows the commit). Submit by 13 Nov 23:59 IST (owner). Feature
freeze 9 Nov; fixes only after.

## How releases are checked while CI is blocked

GitHub Actions is blocked by a billing hold (#164 onward): deploy on local checks (backend
`--ignore=tests/test_postgres.py`, `npm run e2e`) plus the reviewing session's own suite run, hash sent before each
deploy. Never claim CI green. Cloud reports (Linux, systemd, load, security, browser matrix, restore drill, product
audit) are on their `*-report` branches; never merge those.

## Done since f9be55d (pushed, not deployed)

| Commit | What |
|---|---|
| `2045ea5` | Audit P2 polish: ledger account names, "Books balance", date message + CSV file picker, decision path cases, remittance toast, why-card money format, tamper amounts as money, tour/practice/invite/bank wording, approvals Details, capitalised pills, pause reason required, `GET /api/auth/session` (no 401 for visitors). Local: backend 582 passed 2 skipped; browser 30/30. Sent to the reviewer 5 Nov |

## Next

1. Deploy `2045ea5` after the reviewer's OK; read the commit back; live checks (health, /auth/session 200 for a visitor).
2. Remaining audit items: P2-6 (own invoice numbers), P2-7 (say which currencies: USD, EUR, GBP), P2-10 pre-fill
   Resolve from the reader's proposal, P2-18 time zones, then P3. Docs: expiry is configurable; drop "SaaS" claims.
   Feature freeze 9 Nov.
3. Version 1.0.0 only when every check passes (CHANGELOG top already says 1.0.0; `__version__` is 0.2.0).

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
