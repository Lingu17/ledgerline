# Resume point (updated 30 Oct 2026, ~04:00 UTC)

Branch `deploy/vercel-render` (not merged; merge only after the owner approves). Live https://35-207-220-110.sslip.io runs release `3ce6c32` (CI run 40999390871 all five jobs green; smoke 32/32; restart, reboot and redeploy each 8/8). Full status: docs/FULL_APPLICATION_ACCEPTANCE_REPORT.md.

## Only remaining work

1. **VM refund with a second real approver** (owner): Settings → Sandbox deposit verification, payer `Sandbox Refund Test GmbH`, EUR 1.23, new request id → Simulate; Payments → that deposit → *Propose return to sender*; Team → Invite member (Operator) for a real second person, who approves and executes. Then record SENT → PAID (owner sandbox transition controls), one provider transfer, liability and conservation in INTEGRATION_EVIDENCE and the acceptance report, commit, CI, redeploy, `--verify`.
2. Owner decisions: retire old Vercel/Render/Neon stack; judge repository access; demo video; HackerEarth submission; merge to main.
3. Optional: ask Airwallex to enable payment links (current: HTTP 400 configuration_error).

## Access

SSH `ssh -i ~/.ssh/ledgerline_oracle ledgerline-deploy@35.207.220.110`. Deploy: git bundle → `/srv/ledgerline.bundle` → `sudo bash /opt/ledgerline/src/deploy/vm/update.sh <sha>`. Smoke state for `--verify`: %TEMP%/llsmoke/final-state.json (throwaway account). Never print `/etc/ledgerline/ledgerline.env` values.
