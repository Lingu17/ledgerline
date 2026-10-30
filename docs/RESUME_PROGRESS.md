# Resume point (updated 30 Oct 2026, ~04:00 UTC)

Branch `deploy/vercel-render` (not merged; merge only after the owner approves). Live https://35-207-220-110.sslip.io runs release `6ef43c5` (CI run 41002935918 all five jobs green; smoke 32/32; restart, reboot and redeploy each 8/8). The VM refund is done (30 Oct). Full status: docs/FULL_APPLICATION_ACCEPTANCE_REPORT.md.

## Only remaining work

1. **VM refund COMPLETE 30 Oct.** DEP-A5F71B22E4 → APR-FC97829A → OP-46BAA6D1, second real member approved/executed. Provider SENT 04:20:43 → PAID 04:20:56 UTC. Independent provider GET and request-id lookup confirm one PAID EUR 1.23 transfer (`a6c5d55a-…`); one local attempt. Timestamped journal reconstruction proves payable EUR 1.23 at SENT, zero at PAID; all five EUR checks pass. Do not submit or simulate this refund again. Documentation release/CI/deploy follows this evidence update.
2. Owner decisions: retire old Vercel/Render/Neon stack; judge repository access; demo video; HackerEarth submission; merge to main.
3. Optional: ask Airwallex to enable payment links (current: HTTP 400 configuration_error).

## Access

SSH `ssh -i ~/.ssh/ledgerline_oracle ledgerline-deploy@35.207.220.110`. Deploy: git bundle → `/srv/ledgerline.bundle` → `sudo bash /opt/ledgerline/src/deploy/vm/update.sh <sha>`. Smoke state for `--verify`: %TEMP%/llsmoke/final-state.json (throwaway account). Never print `/etc/ledgerline/ledgerline.env` values.
