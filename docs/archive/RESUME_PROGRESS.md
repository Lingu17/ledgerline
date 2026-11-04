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

## Done since e928861 (pushed; deploy after the reviewer's run on the latest hash)

- `07d0eef`: the judge path at 375 x 812 as a browser test; errors shown as the server's own sentence; test numbers
  and the blocked-CI wording; Before-submitting gains "CI after public" and "no LICENSE file" (owner's choice).
- `ab86e26`: `docs/PAYER_AGENT_SPEC.md` + JSON schema + signed test vector (`test_payer_agent_spec.py`);
  `docs/MEASURED_VALUE.md` (`scripts/measure_value.py`, synthetic, 30.4% decided with no person); Replay this decision
  (tenant migration 11 `plans.inputs`, `replay.py`, every accuracy run replays every decision); the walkthrough's
  send step completes itself once the refund exists.
- `ff10cfa`: Try to tamper (`tamper_demo.py`, `/api/practice/tamper[/restore]`, 403 in real companies, reset clears
  it, `restore_check.py` checks a mid-demo backup with the change put back); the Show me tour
  (`frontend/src/components/ShowMe.tsx`, practice only); accuracy rerun 61,063 checks, 8,826 decisions replayed.
- Next commit, on its own so it can be reverted alone: Sender B (`ledgerline/sender.py`, `@through_sender` on
  `payouts.execute_refund`, `bill_payments.execute`, `treasury.execute_conversion`, `wrong_currency.convert`;
  `SenderProxy` for bank reads, `create_transfer`/`create_conversion` never forwarded; `LEDGERLINE_SENDER_SOCKET`,
  `LEDGERLINE_CONNECTIONS_KEY_PATH`; `deploy/vm/ledgerline-send.service`; `harden.sh sender` / `sender-off`;
  `update.sh` restarts it; SERVER_STEPS step 7). Ships switched off until the owner runs step 7.

## Build order still to do

Nothing left from the approved list except deploying and the owner's server step 7 (Claude mode for the reference
payer agent was skipped by decision). Feature freeze 9 Nov; fixes only after.

After each step: send the hash to the reviewing session before deploying, deploy, read the commit back, move `main`,
update this note and the `wip/payer-agent` snapshot.

## Waiting on the owner

`docs/SERVER_STEPS.md` steps 0 to 7 (bucket and service account, keys in a password manager, harden steps, alerts,
recovery drill, the sending service), the video upload and README link, the secrets scan, making the repository public, CI after public,
submission. Production reads need the owner's approval in the session doing them.

## Access

SSH `ssh -i ~/.ssh/ledgerline_oracle ledgerline-deploy@35.207.220.110` (sometimes times out; retry). Deploy: git
bundle of `deploy/vercel-render` → `/srv/ledgerline.bundle` → `sudo bash /opt/ledgerline/src/deploy/vm/update.sh
<sha>`, then read the commit back. Never print `/etc/ledgerline/ledgerline.env` or any key. Commits carry no AI
attribution line (owner's instruction). No messages in Slack or anywhere on the owner's behalf.
