# Ledgerline deployment handoff

Updated 30 Oct 2026. Deadline 13 Nov 2026, 23:59 IST. No HackerEarth save/submit or public posts. Repository private.

## Current production: Google Cloud single host

- **Live URL: https://35-207-220-110.sslip.io** (website, API, assets, data and payer-agent keys on one always-on VM; no cold start).
- VM `ledgerline`, project `project-0b143378-307b-4214-818`, asia-south1-a, e2-small, Ubuntu 24.04, 20 GB balanced disk, static IP 35.207.220.110. Free Trial credit ₹28,797, ends 28 Jan 2027 (the VM stops then unless billing is upgraded; no upgrade was made). Billing showed ₹0.00 used on 29 Oct (usage reporting lags). Budget alert ₹2,000/month at 50/90/100/150%.
- Code is shipped as a git bundle (private repository) to `/srv/ledgerline.bundle`; `deploy/vm/update.sh <commit>` deploys an exact commit. The deployed commit, CI run and persistence results are in the release record of [FULL_APPLICATION_ACCEPTANCE_REPORT](FULL_APPLICATION_ACCEPTANCE_REPORT.md).
- Keys in `/etc/ledgerline/ledgerline.env` (root:ledgerline 640), entered by the owner, never printed: Airwallex, Anthropic, Google OAuth. `LEDGERLINE_SANDBOX_ORGS=org_66646a497151` (Ledgerline Operations). Google OAuth client "Ledgerline web" has the VM origin and callback.
- Airwallex webhook for the operator organization: `/api/webhooks/airwallex/org_66646a497151`, secret saved in Settings (write-only).
- Operations: systemd hardening, nightly backup timer (ran 30 Oct 03:15 UTC), isolated restore test passed 29 Oct, journald default retention.

## Pending with the owner

1. **VM refund test.** Settings → Sandbox deposit verification: payer `Sandbox Refund Test GmbH`, amount 1.23 EUR, new request id → Simulate. Payments → that deposit → *Propose return to sender*. Team → Invite member (Operator) for a second real person; they accept, then Approvals → *Approve…* → *Execute refund*. Claude then records SENT → PAID, liability and conservation.
2. Retire the old Vercel/Render/Neon stack (still running, untouched, holds its own key copies) when approved.
3. Ask Airwallex to enable hosted payment links on the sandbox account if that capability matters for judging.
4. Record the demo video; grant judges repository access; submit on HackerEarth.

## Historical (superseded)

27–29 Oct: Vercel Hobby → Render Free → Neon Free. Verified there: smoke 32/32 and 8/8 persistence after a Render instance replacement; sandbox deposits, FX conversion, signed delivery, and an independently approved EUR 5 refund through SENT → PAID. Details in [INTEGRATION_EVIDENCE](INTEGRATION_EVIDENCE.md). `LEDGERLINE_SECRET_KEY` there encrypts payer keys in Neon and must never change; it is not used on the VM.
