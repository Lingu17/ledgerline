# Resume point (updated 3 Nov 2026)

Branch `deploy/vercel-render`; `main` follows it after green CI. Live https://35-207-220-110.sslip.io runs `f27335a`
(deployed and read back from the server on 3 Nov). Submit by 13 Nov 23:59 IST (owner).

## Committed, waiting to deploy

`2e70545`…`0a12f2a` on the branch: sign-up limit per address (10/h, 40/day, 500/day for the server), hash-pinned
dependencies (`--require-hashes`), `update.sh` that rolls back a failed or unhealthy release, encrypted off-server
backup code (`deploy/vm/backup.py`, `restore_check.py`), owner-run `deploy/vm/harden.sh` and `docs/SERVER_STEPS.md`.
CI: #137 green (b0996bc); #138–#140 failed only on the postgres job (backup tests, fixed in 2ce45c0); #141 (2ce45c0)
and #142 (0a12f2a) pending. Deploy the branch tip once its CI is green on all five jobs, read the commit back from the
server, check the update log shows the hashed install, then move `main`.

## In progress, not committed on the branch

The outside payer agent. A snapshot is on the private branch `wip/payer-agent` (`4cb880a`); the same changes are in the
working tree. Pieces: `tools/payer_agent/` (standalone reference agent with its own key, MCP streamable HTTP),
`backend/ledgerline/payer_agents/remote.py` (https only, connect-time address checks, timeouts, size cap, no cookies),
`client.ask_agents` (own agent by URL, else simulated), tenant migration 10 (`customers.agent_url`), owner-only
`PUT/DELETE /api/customers/{id}/payer-agent`, `tests/test_remote_agent.py` (39 passing). Still to do: the UI (register
on a customer; "Your own agent" vs "Simulated agent" labels on answers), the quickstart's four commands, docs within
what tests prove (localhost unless run from another machine), full suite, browser ×3, CI, deploy.

## Waiting on the owner

Run `docs/SERVER_STEPS.md` in order (step 0 first): bucket and VM service account (Cloud Shell; VM stop/start, only
with the IP reserved), then `harden.sh` backup, files, systemd, journald, opsagent-why, ssh. Store `backup.key` and
`connections.key` in a password manager. Production reads (logs, sign-ups by day, restore test on the VM, live books)
need the owner's approval in the session doing them. Also: video link in the README, judge repo access, submission.

## After that (plan for 10/10)

Payer agent run from a separate machine; uptime check plus email alert and a backup-age alert (owner-run gcloud);
an agent-proposed refund on the real Airwallex sandbox with a second real person; timed restore onto a fresh VM.

## Access

SSH `ssh -i ~/.ssh/ledgerline_oracle ledgerline-deploy@35.207.220.110` (sometimes times out; retry). Deploy: git
bundle of `deploy/vercel-render` → `/srv/ledgerline.bundle` → `sudo bash /opt/ledgerline/src/deploy/vm/update.sh
<sha>`, then read the commit back. Never print `/etc/ledgerline/ledgerline.env` or any key. Commits carry no AI
attribution line (owner's instruction).
