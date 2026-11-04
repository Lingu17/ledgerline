# Resume point (updated 4 Nov 2026)

Branch `deploy/vercel-render`; `main` moves only after the server reports the same commit. Live
https://35-207-220-110.sslip.io runs `e928861` (deployed and read back on 4 Nov). Submit by 13 Nov 23:59 IST (owner).
No new features after 9 Nov; fixes only.

## How releases are checked while CI is blocked

GitHub Actions has been blocked by an account billing hold since 3 Nov (run #164 onward). The owner chose to deploy
on local checks: the full backend suite here (Windows; `--ignore=tests/test_postgres.py`), a second backend run by the
reviewing session on its own worktree, and the browser suite (`npm run e2e`). **The PostgreSQL suite has not run since
CI #163.** Do not claim CI green for these deploys. After the repository goes public, Actions minutes are free:
trigger `ci` (it has a manual trigger) and check every job, PostgreSQL included, before submitting.

## Done since e928861 (committed, not yet deployed)

- `07d0eef`: the judge path at 375 x 812 as a browser test; sign-up 429 and other errors shown as the server's own
  sentence; test numbers and the blocked-CI wording in the docs; Before-submitting gains "CI after public" and "no
  LICENSE file" (owner's choice: all rights reserved).
- Next commit: `docs/PAYER_AGENT_SPEC.md` with `docs/schemas/explain_payment.v1.schema.json` and a signed test vector
  (`tests/test_payer_agent_spec.py` keeps them in step with the verifier); the walkthrough marks the send step done
  once the DEP-1006 refund exists (sent from Approvals, no Run press left); `scripts/measure_value.py` and
  `docs/MEASURED_VALUE.md` (synthetic, first plan per payment, minutes-per-payment stated as an assumption).

## Build order still to do (approved by the owner: "dont ask me anything")

1. Replay this decision: store the rules' exact inputs with each plan (tenant migration 11, `plans.inputs`, hash in
   the audit detail), re-run the pure rules (`matching.initial_plan`, `evidence.verify` + plan from verdict) and show
   "same plan" or the difference. Read-only.
2. Try to tamper, practice companies only: edit one audit row, `verify_chain` fails at that row, Restore. Server 403
   in real companies, with a test.
3. Guided "Show me" demo in practice companies.
4. Sender B by 8 Nov: Airwallex keys only in a separate `ledgerline-send` process; docs say "the Airwallex keys live
   only in a separate process; the app cannot read them" and "a compromised app could still request a send that its
   own database says was approved"; the AWS-rules comparison row becomes "Partly"; owner-run harden.sh
   `sender`/`sender-off`.
5. Skipped by decision: Claude mode for the reference payer agent.

After each step: send the hash to the reviewing session before deploying, deploy, read the commit back, move `main`,
update this note and the `wip/payer-agent` snapshot.

## Waiting on the owner

`docs/SERVER_STEPS.md` steps 0 to 6 (bucket and service account, keys in a password manager, harden steps, alerts,
recovery drill), the video upload and README link, the secrets scan, making the repository public, CI after public,
submission. Production reads need the owner's approval in the session doing them.

## Access

SSH `ssh -i ~/.ssh/ledgerline_oracle ledgerline-deploy@35.207.220.110` (sometimes times out; retry). Deploy: git
bundle of `deploy/vercel-render` → `/srv/ledgerline.bundle` → `sudo bash /opt/ledgerline/src/deploy/vm/update.sh
<sha>`, then read the commit back. Never print `/etc/ledgerline/ledgerline.env` or any key. Commits carry no AI
attribution line (owner's instruction). No messages in Slack or anywhere on the owner's behalf.
