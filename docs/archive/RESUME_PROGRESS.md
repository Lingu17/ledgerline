# Resume point (updated 5 Nov 2026)

Branch `deploy/vercel-render` (snapshot also on `wip/payer-agent`); `main` moves only after the server reports the same
commit. **Live and on `main`: `b3ba221`** (read back 5 Nov; health shows the commit; an old tab gets the new bundle on reload). This is the state to freeze from; the reviewer agreed. Submit by 13 Nov 23:59 IST (owner). Feature
freeze 9 Nov; fixes only after.

## How releases are checked while CI is blocked

GitHub Actions is blocked by a billing hold (#164 onward): deploy on local checks (backend
`--ignore=tests/test_postgres.py`, `npm run e2e`) plus the reviewing session's own suite run, hash sent before each
deploy. Never claim CI green. Cloud reports (Linux, systemd, load, security, browser matrix, restore drill, product
audit) are on their `*-report` branches; never merge those.

## Where things stand

The product audit's P1, P2 and P3 lists are done and live, apart from P2-6 (own invoice numbers), which is deferred
and stated in README and SUBMISSION_DRAFT. Local on `b3ba221`'s code: backend 584 passed, 2 skipped; the reviewer's
machine 587 passed, 12 skipped; browser 30/30.

## Next

1. Fixes only, and anything the owner asks for. Feature freeze 9 Nov; submit by 13 Nov 23:59 IST (owner).
2. Every change still goes: full suites, hash to the reviewer, deploy on OK, read back, `main` moves on MATCH.
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
