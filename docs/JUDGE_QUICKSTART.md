# Ledgerline: judge quickstart

Updated 29 October 2026: verified runtime `98d6ad4653aa3701b38a81577650377f2ad30792`, CI 40839628066 all five jobs passed. Actual signed Airwallex deposit delivery and fresh EUR5 refund processing→SENT→PAID completed; liability/conservation verified. Payment-link request refused HTTP 401 (honest draft); provider external replay returned success:false. Successful Claude extraction waits for credit (user expects it in one day). Fresh isolated Neon 13/13 passed in 1,629.50s at baseline 6c43626; final-code CI PostgreSQL 17 is primary evidence. Final main-branch deployed SHAs/smoke/restart will be recorded separately after release.


**Live app:** https://35-207-220-110.sslip.io (always on).

The whole application (website, API and database) runs on one always-on Google Cloud server, so there is no wake-up delay.

## Five-minute path

1. Open the link and click **Get started**.
2. Enter any name, organization and email (it does not need to be real; nothing is emailed) and a password of 12+ characters with upper- and lower-case letters and a digit. Choose **Sample data** and create the organization. You get your own isolated workspace; other judges cannot see it.
3. **Inbox**: cash by currency, and the payments that need a decision.
4. **Payments → DEP-1005** (Dunmore, looks like a duplicate): click **Ask payer agent** (about 9 seconds: it starts the payer's real MCP agent process on a small free server). The payer's agent answers over MCP with a signed claim; all three checks pass (signature, freshness and binding, our records) and the plan is revised: the money becomes **advance credit** instead of a refund.
5. **Payments → DEP-1004** (Fjord): **Ask payer agent**. The agent claims another customer's invoice; the signature verifies but the records check fails, so the claim is **rejected** and the case goes to a person.
6. **Walkthrough** (left menu) runs the full six-payment story step by step: payment link draft for the short payment, FX for the EUR bill, a refund that needs a person's approval, bank SENT (not final) then PAID, and the closing scorecard.
7. **Ledger**: deposits = allocated + credits + refunds + unapplied, per currency, to the cent.

Ordinary work without the walkthrough: create an organization with **An empty workspace**, then add customers and invoices (Customers & invoices), record or import payments (Payments → Record payment / Import CSV), resolve escalations, and invite teammates with roles (Team).

## What is real and what is simulated

| Part | Status |
|---|---|
| Matching rules, ledger, approvals, locks, roles, tenant isolation | Real application code |
| Storage | Real PostgreSQL (Neon free tier); your organization survives backend restarts and redeploys |
| Sign in with Google / Apple | Google configured and real user login observed; Testing mode may restrict accounts. Apple hidden from login by user choice. Email/password remains available. |
| Payer agents | Simulated customer agents, real MCP protocol and real Ed25519 signatures |
| Bank | Built-in **simulated bank** (labelled in the top bar). No real money |
| Airwallex sandbox | Operator-only sandbox deposits settled and reconciled, and EUR→GBP FX settled on 28 Oct 2026 (`a4c9f2c`). Earlier receipts were polled. On29 Oct, signed deposit delivery and a separately approved EUR5 refund through SENT→PAID were verified; external replay was refused by Airwallex. Judge workspaces use local simulations. |
| Claude remittance reading | API key configured on Render; first actual call on 28 Oct 2026 refused for insufficient Anthropic credit. Successful live extraction is **not verified**. Workspaces without a key use labelled offline rules. |

See `docs/INTEGRATION_EVIDENCE.md` for exactly what has and has not been verified.
